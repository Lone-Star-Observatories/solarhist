"""Effects at Earth: solar wind, geomagnetic indices and energetic protons.

Sources
  * NASA OMNI via the CDAWeb HAPI server (cdaweb.gsfc.nasa.gov/hapi)
      OMNI2_H0_MRG1HR  hourly: Bz(GSM), density, speed, Kp, Dst, >10 MeV protons (to ~2019)
      OMNI_HRO_1MIN    1-min:  Bz(GSM), speed, density, SYM-H      (used for windows <= 20 days)
      OMNI_HRO_5MIN    5-min:  >10 MeV proton flux                   (to early 2020)
  * GOES-16+ SGPS 5-min differential protons (NOAA NCEI) → >10 MeV integral flux, 2020 onward
  * NOAA SWPC real-time JSON for the last few days, which OMNI hasn't reached yet
"""
from __future__ import annotations

import io
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import xarray as xr

from .core import CACHE, HTTP, _set_progress, _utcnow

HAPI = "https://cdaweb.gsfc.nasa.gov/hapi/data"
SGPS_DIR = ("https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/"
            "goes{n}/l2/data/sgps-l2-avg5m/{y}/{m:02d}/")
SWPC = "https://services.swpc.noaa.gov"
OMNI_CACHE = CACHE / "omni"
OMNI_CACHE.mkdir(parents=True, exist_ok=True)

HOURLY = ("OMNI2_H0_MRG1HR", ["BZ_GSM1800", "N1800", "V1800", "PR-FLX_101800", "KP1800", "DST1800"],
          ["bz", "n", "v", "p10", "kp", "dst"])
MINUTE = ("OMNI_HRO_1MIN", ["BZ_GSM", "flow_speed", "proton_density", "SYM_H"], ["bz", "v", "n", "symh"])
PROTON5 = ("OMNI_HRO_5MIN", ["PR-FLX_10"], ["p10"])
SGPS_FROM = datetime(2020, 3, 1)          # OMNI's GOES proton record ends with GOES-15
FILLS = {"bz": 999, "n": 999, "v": 9999, "p10": 99999, "kp": 99, "dst": 99999, "symh": 99999}

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def _hapi(dataset: str, params: list[str], names: list[str], start: datetime, end: datetime) -> pd.DataFrame:
    r = HTTP.get(HAPI, timeout=180, params={
        "id": dataset, "parameters": ",".join(params), "format": "csv",
        "time.min": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "time.max": end.strftime("%Y-%m-%dT%H:%M:%SZ")})
    if r.status_code == 404 or not r.text.strip() or r.text.lstrip().startswith("{"):
        # HAPI answers out-of-range requests (e.g. past OMNI's last day) with a JSON status, not CSV.
        return pd.DataFrame({c: pd.Series(dtype="float32") for c in names}, index=pd.DatetimeIndex([], name="t"))
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), header=None, names=["t"] + names)
    df["t"] = pd.to_datetime(df["t"]).dt.tz_localize(None)
    df = df.set_index("t").astype("float32")
    for c in names:                       # OMNI fill values are 9s: 999.9, 9999., 99999.99 …
        df.loc[df[c].abs() >= FILLS[c] * 0.999, c] = np.nan
    if "kp" in df:
        df["kp"] = df["kp"] / 10.0        # OMNI stores Kp×10 (e.g. 83 = 8+)
    return df


def _cached(key: str, start: datetime, end: datetime, fetch) -> pd.DataFrame:
    """Cache one period (month or year) as parquet; refresh the current period every 6 h."""
    path = OMNI_CACHE / f"{key}.parquet"
    current = end > _utcnow() - timedelta(days=40)
    with _lock(key):
        if path.exists() and (not current or time.time() - path.stat().st_mtime < 6 * 3600):
            return pd.read_parquet(path)
        _set_progress(key, f"Fetching {key.replace('_', ' ')} (Earth effects)…")
        try:
            df = fetch(start, end)
            df.to_parquet(path)
            return df
        except Exception:
            if path.exists():
                return pd.read_parquet(path)
            raise
        finally:
            _set_progress(key, None)


def _months(start: datetime, end: datetime):
    cur = datetime(start.year, start.month, 1)
    while cur < end:
        nxt = datetime(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        yield cur, nxt
        cur = nxt


def _hourly(start: datetime, end: datetime) -> pd.DataFrame:
    parts = []
    for y in range(start.year, end.year + 1):
        a, b = datetime(y, 1, 1), datetime(y + 1, 1, 1)
        parts.append(_cached(f"omni2_h_{y}", a, b, lambda s, e: _hapi(HOURLY[0], HOURLY[1], HOURLY[2], s, e)))
    return pd.concat(parts).loc[start:end] if parts else pd.DataFrame()


def _minute(start: datetime, end: datetime) -> pd.DataFrame:
    parts = [_cached(f"omni_1min_{a:%Y_%m}", a, b, lambda s, e: _hapi(MINUTE[0], MINUTE[1], MINUTE[2], s, e))
             for a, b in _months(start, end)]
    return pd.concat(parts).loc[start:end] if parts else pd.DataFrame()


def _sgps_day(url: str) -> pd.Series | None:
    r = HTTP.get(url, timeout=90)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with xr.open_dataset(io.BytesIO(r.content), engine="h5netcdf") as d:
        lo = d["DiffProtonLowerEnergy"].values          # keV, (sensor_units, channels)
        hi = d["DiffProtonUpperEnergy"].values
        flux = d["AvgDiffProtonFlux"].values             # protons/(cm2 sr keV s), (time, sensor, channel)
        t = d["time"].values
    # >10 MeV integral: sum differential flux × the part of each channel above 10 MeV (both sensor heads,
    # averaged). Leaving out the >500 MeV P11 channel matches SWPC's operational >=10 MeV values to within ~5 %
    # (checked against the SWPC 7-day feed, Oct 2026).
    width = np.where(lo >= 1e4, hi - lo, np.clip(hi - 1e4, 0, None))
    flux = np.where(flux >= 0, flux, np.nan)
    p10 = np.nansum(flux * width[None], axis=2)
    p10 = np.where(np.isnan(flux).all(axis=2), np.nan, p10)
    with np.errstate(all="ignore"):
        return pd.Series(np.nanmean(p10, axis=1).astype("float32"), index=pd.DatetimeIndex(t, name="t"), name="p10")


def _sgps_month(start: datetime, end: datetime) -> pd.DataFrame:
    sats = [19, 18, 16] if start >= datetime(2025, 4, 1) else [16, 18, 17]
    for sat in sats:
        base = SGPS_DIR.format(n=sat, y=start.year, m=start.month)
        r = HTTP.get(base, timeout=60)
        if r.status_code != 200:
            continue
        names = sorted(set(re.findall(r'href="(sci_sgps-l2-avg5m_g\d+_d\d{8}_v[\d-]+\.nc)"', r.text)))
        if not names:
            continue
        with ThreadPoolExecutor(8) as pool:
            series = [s for s in pool.map(lambda n: _sgps_day(base + n), names) if s is not None]
        if series:
            return pd.concat(series).sort_index().to_frame()
    return pd.DataFrame({"p10": pd.Series(dtype="float32")}, index=pd.DatetimeIndex([], name="t"))


def _protons(start: datetime, end: datetime, long_range: bool) -> pd.DataFrame:
    parts = []
    if start < SGPS_FROM:
        e = min(end, SGPS_FROM)
        if long_range:
            h = _hourly(start, e)
            if "p10" in h:
                parts.append(h[["p10"]])
        else:
            parts += [_cached(f"omni_5min_p_{a:%Y_%m}", a, b, lambda s, e2: _hapi(PROTON5[0], PROTON5[1], PROTON5[2], s, e2))
                      for a, b in _months(start, e)]
    if end > SGPS_FROM and (not long_range or end - start <= timedelta(days=200)):
        s = max(start, SGPS_FROM)
        parts += [_cached(f"sgps_p10_{a:%Y_%m}", a, b, _sgps_month) for a, b in _months(s, end)]
    if not parts:
        return pd.DataFrame({"p10": pd.Series(dtype="float32")}, index=pd.DatetimeIndex([], name="t"))
    return pd.concat(parts).sort_index().loc[start:end]


# ---- SWPC real-time tail (OMNI lags several days)

_rt: dict[str, tuple[float, pd.DataFrame]] = {}


def _swpc_table(path: str) -> pd.DataFrame:
    hit = _rt.get(path)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    try:
        rows = HTTP.get(SWPC + path, timeout=30).json()
        if rows and isinstance(rows[0], list):          # products/*.json: header row + rows
            df = pd.DataFrame(rows[1:], columns=rows[0])
        else:
            df = pd.DataFrame(rows)
    except Exception:
        df = pd.DataFrame()
    _rt[path] = (time.time(), df)
    return df


def _num(s):
    return pd.to_numeric(s, errors="coerce").astype("float32")


def realtime() -> pd.DataFrame:
    cols = {}
    # Real-time solar wind: several spacecraft (IMAP, DSCOVR, ACE) are mixed in one file; use the active one.
    w = _swpc_table("/json/rtsw/rtsw_wind_1m.json")
    if not w.empty and "active" in w:
        w = w[w["active"] == True]  # noqa: E712
        t = pd.to_datetime(w["time_tag"])
        cols["n"] = pd.Series(_num(w["proton_density"]).values, index=t)
        cols["v"] = pd.Series(_num(w["proton_speed"]).values, index=t)
    m = _swpc_table("/json/rtsw/rtsw_mag_1m.json")
    if not m.empty and "active" in m:
        m = m[m["active"] == True]  # noqa: E712
        cols["bz"] = pd.Series(_num(m["bz_gsm"]).values, index=pd.to_datetime(m["time_tag"]))
    k = _swpc_table("/products/noaa-planetary-k-index.json")
    if not k.empty:
        cols["kp"] = pd.Series(_num(k["Kp"] if "Kp" in k else k["kp_index"]).values, index=pd.to_datetime(k["time_tag"]))
    d = _swpc_table("/products/kyoto-dst.json")
    if not d.empty:
        cols["dst"] = pd.Series(_num(d["dst"]).values, index=pd.to_datetime(d["time_tag"]))
    pr = _swpc_table("/json/goes/primary/integral-protons-7-day.json")
    if not pr.empty and "energy" in pr:
        sub = pr[pr["energy"] == ">=10 MeV"]
        cols["p10"] = pd.Series(_num(sub["flux"]).values, index=pd.to_datetime(sub["time_tag"]).dt.tz_localize(None))
    out = {}
    for k_, s in cols.items():
        s.index = pd.DatetimeIndex(s.index).tz_localize(None) if getattr(s.index, "tz", None) else pd.DatetimeIndex(s.index)
        out[k_] = s[~s.index.duplicated()].sort_index()
    return out


# ---- public

def _bucket(s: pd.Series, start: datetime, step_min: int, how: str) -> pd.Series:
    s = s.dropna()
    if s.empty:
        return s
    if step_min <= 1:
        return s
    return getattr(s.resample(f"{step_min}min", origin=pd.Timestamp(start)), how)()


def _pack(s: pd.Series) -> dict:
    s = s.dropna()
    return {"t": _ms(s.index), "y": [float(f"{v:.4g}") for v in s.to_numpy()]}


def _ms(idx: pd.DatetimeIndex) -> list[int]:
    """Epoch milliseconds whatever the index resolution (pandas 3 may use s/us units)."""
    return pd.DatetimeIndex(idx).as_unit("ms").asi8.tolist()


def effects(start: datetime, end: datetime, points: int = 1500) -> dict:
    span = end - start
    long_range = span > timedelta(days=20)
    h = _hourly(start - timedelta(hours=3), end)
    m = _minute(start, end) if not long_range else None
    wind = m if m is not None and not m.empty else h
    pr = _protons(start, end, long_range)

    # Append the SWPC real-time tail after the last OMNI sample of each series.
    rt = realtime() if end > _utcnow() - timedelta(days=8) else {}

    def series(df, col):
        s = df[col] if df is not None and col in df else pd.Series(dtype="float32")
        s = s.dropna()
        if col in rt:
            last = s.index.max() if len(s) else start - timedelta(seconds=1)
            tail = rt[col].loc[(rt[col].index > last) & (rt[col].index >= start) & (rt[col].index <= end)]
            s = pd.concat([s, tail.dropna()])
        return s.loc[start:end]

    step = max(1, int(np.ceil(span.total_seconds() / 60 / points)))
    v, n, bz = series(wind, "v"), series(wind, "n"), series(wind, "bz")
    kp, dst, p10 = series(h, "kp"), series(h, "dst"), series(pr, "p10")
    kp_step, dst_step = max(step, 180), max(step, 60)
    out = {
        "v": _pack(_bucket(v, start, step, "max")),
        "n": _pack(_bucket(n, start, step, "max")),
        "bz_min": _pack(_bucket(bz, start, step, "min")),
        "bz_max": _pack(_bucket(bz, start, step, "max")),
        "kp": _pack(_bucket(kp, start - timedelta(minutes=start.minute, hours=start.hour % 3), kp_step, "max")),
        "dst": _pack(_bucket(dst, start, dst_step, "min")),
        "p10": _pack(_bucket(p10, start, max(step, 5), "max")),
        "wind_res": "1-min" if wind is m else "hourly",
        "step_min": step,
        "protons_note": None,
    }
    if long_range and end > SGPS_FROM and span > timedelta(days=200):
        out["protons_note"] = "zoom in to ≤ 200 days to load GOES-16+ proton data (2020 →)"
    return out
