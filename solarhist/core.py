"""Data layer: fetch, cache and query GOES XRS flux + SWPC Warehouse event lists.

Sources
  * 1-minute XRS flux (science quality, NOAA NCEI)
      GOES-16..19 : one file per satellite-year (current year refreshed daily)
      GOES-8..15  : one file per day, grouped into per-month cache units
  * Last few hours : SWPC 7-day JSON (primary satellite)
  * Flare events  : SWPC Warehouse FTP (ftp.swpc.noaa.gov/pub/warehouse), 1996 -> today
  * Daily indices : SWPC Warehouse YYYY_DSD.txt (F10.7, sunspot number, flare counts)
"""
from __future__ import annotations

import ftplib
import io
import json
import re
import tarfile
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr

CACHE = Path(__file__).resolve().parent.parent / "cache"
(CACHE / "flux").mkdir(parents=True, exist_ok=True)
(CACHE / "events").mkdir(parents=True, exist_ok=True)
(CACHE / "tmp").mkdir(parents=True, exist_ok=True)

NEW_URL = ("https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/"
           "goes{n}/l2/data/xrsf-l2-avg1m_science/sci_xrsf-l2-avg1m_g{n}_y{y}_v2-2-1.nc")
OLD_DIR = ("https://www.ncei.noaa.gov/data/goes-space-environment-monitor/access/science/xrs/"
           "goes{n:02d}/xrsf-l2-avg1m_science/{y}/{m:02d}/")
SWPC_7DAY = "https://services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json"
FTP_HOST = "ftp.swpc.noaa.gov"
FTP_ROOT = "/pub/warehouse"

# Years of science data on NCEI per satellite (None = still running).
SAT_YEARS = {8: (1995, 2003), 9: (1996, 1998), 10: (1998, 2009), 11: (2006, 2008), 12: (2003, 2007),
             13: (2013, 2017), 14: (2009, 2020), 15: (2010, 2020),
             16: (2017, 2025), 17: (2018, 2023), 18: (2022, None), 19: (2024, None)}
NEW_SATS = {16, 17, 18, 19}

# Satellite preference in "auto" mode; first one with data for a cache unit wins.
PRIORITY = [
    (date(2025, 4, 7), date(2100, 1, 1), [19, 18, 16]),
    (date(2017, 2, 7), date(2025, 4, 7), [16, 18, 17]),
    (date(2010, 4, 1), date(2017, 2, 7), [15, 13, 14]),
    (date(2010, 1, 1), date(2010, 4, 1), [14, 15]),
    (date(2008, 1, 1), date(2010, 1, 1), [10, 14, 11]),
    (date(2003, 4, 1), date(2008, 1, 1), [12, 10, 11]),
    (date(1995, 1, 1), date(2003, 4, 1), [8, 10, 9]),
]
EARLIEST = date(1995, 1, 1)

HTTP = requests.Session()
HTTP.headers["User-Agent"] = "solarhist/1.0 (personal GOES XRS history viewer)"

# --------------------------------------------------------------------------- progress

_progress_lock = threading.Lock()
_progress: dict[str, str] = {}


def _set_progress(key: str, msg: str | None):
    with _progress_lock:
        if msg is None:
            _progress.pop(key, None)
        else:
            _progress[key] = msg


def progress() -> list[str]:
    with _progress_lock:
        return list(_progress.values())


# --------------------------------------------------------------------------- flux cache units

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sat_has_year(sat: int, year: int) -> bool:
    lo, hi = SAT_YEARS[sat]
    return lo <= year <= (hi if hi is not None else _utcnow().year)


def _unit_path(sat: int, year: int, month: int | None) -> Path:
    name = f"g{sat}_{year}" + (f"_{month:02d}" if month else "") + ".parquet"
    return CACHE / "flux" / name


def _missing_path(path: Path) -> Path:
    return path.with_suffix(".missing")


def _is_current(year: int, month: int | None) -> bool:
    now = _utcnow()
    return year == now.year and (month is None or month == now.month)


def _fresh(path: Path, year: int, month: int | None) -> bool:
    """A cached unit is final unless it covers the current period (then 6 h TTL)."""
    if not path.exists():
        return False
    if not _is_current(year, month):
        return True
    return time.time() - path.stat().st_mtime < 6 * 3600


def _nc_to_frame(ds: xr.Dataset) -> pd.DataFrame:
    a = ds["xrsa_flux"].values.astype("float32")
    b = ds["xrsb_flux"].values.astype("float32")
    if "xrsa_flag" in ds:
        a = np.where(ds["xrsa_flag"].values == 0, a, np.nan)
    if "xrsb_flag" in ds:
        b = np.where(ds["xrsb_flag"].values == 0, b, np.nan)
    a = np.where(a > 0, a, np.nan)
    b = np.where(b > 0, b, np.nan)
    return pd.DataFrame({"a": a.astype("float32"), "b": b.astype("float32")},
                        index=pd.DatetimeIndex(ds["time"].values, name="t"))


def _fetch_new_year(sat: int, year: int, path: Path) -> bool:
    url = NEW_URL.format(n=sat, y=year)
    _set_progress(path.name, f"Downloading GOES-{sat} {year} (NCEI yearly file)…")
    tmp = CACHE / "tmp" / f"{path.stem}.nc"
    try:
        with HTTP.get(url, stream=True, timeout=120) as r:
            if r.status_code == 404:
                return False
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        with xr.open_dataset(tmp, engine="h5netcdf") as ds:
            df = _nc_to_frame(ds)
        df.to_parquet(path)
        return True
    finally:
        tmp.unlink(missing_ok=True)
        _set_progress(path.name, None)


def _fetch_old_day(url: str) -> pd.DataFrame | None:
    for attempt in range(3):
        try:
            r = HTTP.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            with xr.open_dataset(io.BytesIO(r.content), engine="h5netcdf") as ds:
                return _nc_to_frame(ds)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def _fetch_old_month(sat: int, year: int, month: int, path: Path) -> bool:
    base = OLD_DIR.format(n=sat, y=year, m=month)
    r = HTTP.get(base, timeout=60)
    if r.status_code == 404:
        return False
    r.raise_for_status()
    names = sorted(set(re.findall(r'href="(sci_xrsf-l2-avg1m_g\d+_d\d{8}_v[\d-]+\.nc)"', r.text)))
    if not names:
        return False
    done = 0
    frames = []

    def job(n):
        return _fetch_old_day(base + n)

    with ThreadPoolExecutor(12) as pool:
        for df in pool.map(job, names):
            done += 1
            _set_progress(path.name, f"Downloading GOES-{sat} {year}-{month:02d} ({done}/{len(names)} days)…")
            if df is not None:
                frames.append(df)
    _set_progress(path.name, None)
    if not frames:
        return False
    pd.concat(frames).sort_index().to_parquet(path)
    return True


_unit_locks: dict[Path, threading.Lock] = {}
_unit_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    with _unit_locks_guard:
        return _unit_locks.setdefault(path, threading.Lock())


def ensure_unit(sat: int, year: int, month: int | None) -> Path | None:
    """Make sure a cache unit is on disk; returns its path or None if NOAA has no data."""
    if not _sat_has_year(sat, year):
        return None
    if sat in NEW_SATS:
        month = None
    path = _unit_path(sat, year, month)
    miss = _missing_path(path)
    with _lock_for(path):
        if _fresh(path, year, month):
            return path
        if miss.exists() and (not _is_current(year, month) or time.time() - miss.stat().st_mtime < 6 * 3600):
            return None
        try:
            ok = (_fetch_new_year(sat, year, path) if sat in NEW_SATS
                  else _fetch_old_month(sat, year, month, path))
        except Exception:
            if path.exists():          # stale copy is better than nothing
                return path
            raise
        if ok:
            miss.unlink(missing_ok=True)
            return path
        miss.touch()
        return None


# --------------------------------------------------------------------------- flux query

_frame_cache: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()
_frame_lock = threading.Lock()


def _read_unit(path: Path) -> pd.DataFrame:
    key = (path, path.stat().st_mtime)
    with _frame_lock:
        if key in _frame_cache:
            _frame_cache.move_to_end(key)
            return _frame_cache[key]
    df = pd.read_parquet(path)
    with _frame_lock:
        _frame_cache[key] = df
        while len(_frame_cache) > 40:
            _frame_cache.popitem(last=False)
    return df


def _periods(start: datetime, end: datetime, sat: int | None):
    """Yield (unit_start, unit_end, [candidate sats]) covering [start, end)."""
    cur = datetime(start.year, start.month, 1)
    while cur < end:
        nxt = datetime(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        if sat is not None:
            cands = [sat]
        else:
            cands = []
            for lo, hi, sats in PRIORITY:
                lo_dt, hi_dt = datetime.combine(lo, datetime.min.time()), datetime.combine(hi, datetime.min.time())
                if lo_dt < nxt and hi_dt > cur:
                    cands += [s for s in sats if s not in cands]
            # Prefer the priority of the period containing most of the month.
            mid = cur + (nxt - cur) / 2
            for lo, hi, sats in PRIORITY:
                if lo <= mid.date() < hi:
                    cands = sats + [s for s in cands if s not in sats]
                    break
        yield cur, nxt, cands
        cur = nxt


def load_flux(start: datetime, end: datetime, sat: int | None = None) -> tuple[pd.DataFrame, list[int]]:
    """1-minute flux for [start, end). sat=None → auto (primary satellite per period)."""
    start = max(start, datetime.combine(EARLIEST, datetime.min.time()))
    pieces, used = [], []
    for m0, m1, cands in _periods(start, end, sat):
        for s in cands:
            month = None if s in NEW_SATS else m0.month
            path = ensure_unit(s, m0.year, month)
            if path is None:
                continue
            df = _read_unit(path)
            lo, hi = max(m0, start), min(m1, end)
            part = df.loc[lo:hi - timedelta(microseconds=1)]
            if part["b"].notna().any():
                pieces.append(part.assign(sat=np.int8(s)))
                if s not in used:
                    used.append(s)
                break
    df = pd.concat(pieces) if pieces else pd.DataFrame(
        {"a": pd.Series(dtype="float32"), "b": pd.Series(dtype="float32"), "sat": pd.Series(dtype="int8")},
        index=pd.DatetimeIndex([], name="t"))
    df = df[~df.index.duplicated(keep="first")]

    # Science files lag ~1 day; patch the tail with the SWPC real-time feed.
    if end > _utcnow() - timedelta(days=8):
        rt = realtime()
        if not rt.empty:
            last = df["b"].last_valid_index() if df["b"].notna().any() else None
            if last is None:
                last = start - timedelta(minutes=1)
            df = df.loc[:last]          # drop NaN placeholder rows at the end of the science file
            if sat is None or (rt["sat"] == sat).all():
                tail = rt.loc[(rt.index > last) & (rt.index >= start) & (rt.index < end)]
                if len(tail):
                    df = pd.concat([df, tail])
                    for s in tail["sat"].unique():
                        if int(s) not in used:
                            used.append(int(s))
    return df, used


_rt = {"t": 0.0, "df": None}
_rt_lock = threading.Lock()


def realtime() -> pd.DataFrame:
    with _rt_lock:
        if _rt["df"] is not None and time.time() - _rt["t"] < 300:
            return _rt["df"]
        try:
            rows = HTTP.get(SWPC_7DAY, timeout=30).json()
            j = pd.DataFrame(rows)
            j["t"] = pd.to_datetime(j["time_tag"]).dt.tz_localize(None)
            j["flux"] = j["flux"].where(j["flux"] > 0)
            a = j[j["energy"] == "0.05-0.4nm"].set_index("t")
            b = j[j["energy"] == "0.1-0.8nm"].set_index("t")
            df = pd.DataFrame({"a": a["flux"].astype("float32"), "b": b["flux"].astype("float32")})
            df["sat"] = b["satellite"].reindex(df.index).fillna(a["satellite"].reindex(df.index)).astype("int8")
            df.index.name = "t"
            _rt.update(t=time.time(), df=df.sort_index())
        except Exception:
            if _rt["df"] is None:
                return pd.DataFrame()
        return _rt["df"]


def downsample(df: pd.DataFrame, start: datetime, end: datetime, points: int) -> dict:
    span_min = max(1, (end - start).total_seconds() / 60)
    step = max(1, int(np.ceil(span_min / points)))   # minutes per bucket
    if df.empty:
        return {"t": [], "b": [], "a": [], "bmin": [], "step_min": step}
    if step == 1:
        t = df.index.astype("int64") // 10**6
        return {"t": t.tolist(), "b": _clean(df["b"]), "a": _clean(df["a"]), "bmin": None, "step_min": 1}
    g = df.resample(f"{step}min", origin=pd.Timestamp(start))
    agg = pd.DataFrame({"b": g["b"].max(), "a": g["a"].max(), "bmin": g["b"].min()})
    t = agg.index.astype("int64") // 10**6
    return {"t": t.tolist(), "b": _clean(agg["b"]), "a": _clean(agg["a"]),
            "bmin": _clean(agg["bmin"]), "step_min": step}


def _clean(s: pd.Series) -> list:
    v = s.to_numpy(dtype="float64")
    return [None if not np.isfinite(x) else float(f"{x:.4g}") for x in v]


# --------------------------------------------------------------------------- SWPC Warehouse FTP

class Warehouse:
    """Thin ftplib wrapper; one connection, reconnects on failure."""

    def __init__(self):
        self._ftp: ftplib.FTP | None = None
        self._lock = threading.Lock()

    def _conn(self) -> ftplib.FTP:
        if self._ftp is not None:
            try:
                self._ftp.voidcmd("NOOP")
                return self._ftp
            except Exception:
                self._ftp = None
        ftp = ftplib.FTP(FTP_HOST, timeout=60)
        ftp.login()
        self._ftp = ftp
        return ftp

    def _retry(self, fn):
        with self._lock:
            for attempt in range(3):
                try:
                    return fn(self._conn())
                except (ftplib.error_temp, OSError, EOFError):
                    self._ftp = None
                    if attempt == 2:
                        raise
                    time.sleep(1 + attempt)

    def listdir(self, path: str) -> list[str]:
        def go(ftp):
            try:
                return [n.rsplit("/", 1)[-1] for n in ftp.nlst(path)]
            except ftplib.error_perm:
                return []
        return self._retry(go)

    def get(self, path: str) -> bytes | None:
        def go(ftp):
            buf = io.BytesIO()
            try:
                ftp.retrbinary(f"RETR {path}", buf.write)
            except ftplib.error_perm:
                return None
            return buf.getvalue()
        return self._retry(go)


WAREHOUSE = Warehouse()

_EV_COLS = ["begin", "peak", "end", "cls", "peak_flux", "int_flux", "region", "obs"]
_CLASS_SCALE = {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}


def class_to_flux(c: str) -> float:
    m = re.match(r"^([ABCMX])(\d+(?:\.\d+)?)$", c or "")
    return _CLASS_SCALE[m.group(1)] * float(m.group(2)) if m else float("nan")


def _hhmm(tok: str, day: date) -> datetime | None:
    d = re.sub(r"\D", "", tok)
    if len(d) != 4:
        return None
    h, m = int(d[:2]), int(d[2:])
    if h > 23 or m > 59:
        return None
    return datetime(day.year, day.month, day.day, h, m)


def parse_events(text: str, day: date | None = None) -> list[dict]:
    """Extract X-ray (XRA 1-8A) flares from an SWPC Edited Events file."""
    m = re.search(r":Date:\s*(\d{4})\s+(\d{1,2})\s+(\d{1,2})", text)
    if m:
        day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if day is None:
        return []
    out = []
    for line in text.splitlines():
        if not line.strip() or line.startswith(("#", ":")):
            continue
        tok = line.split()
        if "XRA" not in tok:
            continue
        i = tok.index("XRA")
        # Work backwards from the type: [... begin max end obs q] XRA
        obs_i = next((k for k in range(i - 1, max(i - 3, 0) - 1, -1) if re.match(r"^G\d{1,2}$", tok[k])), None)
        if obs_i is None or obs_i < 3:
            continue
        b, p, e = (_hhmm(t, day) for t in tok[obs_i - 3:obs_i])
        rest = tok[i + 1:]
        if len(rest) < 2 or not re.match(r"^[ABCMX]\d", rest[1]):
            continue
        cls = rest[1]
        intf = float(rest[2]) if len(rest) > 2 and re.match(r"^\d\.\d+E[-+]?\d+$", rest[2]) else None
        reg = rest[-1] if len(rest) > 3 and re.match(r"^\d{4,5}$", rest[-1]) else None
        if b is None and p is None:
            continue
        b = b or p
        p = p or b
        if p < b:
            p += timedelta(days=1)
        if e is not None and e < b:
            e += timedelta(days=1)
        out.append({"begin": b, "peak": p, "end": e, "cls": cls, "peak_flux": class_to_flux(cls),
                    "int_flux": intf, "region": reg, "obs": tok[obs_i]})
    return out


def _events_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=_EV_COLS)
    if not df.empty:
        df = df.drop_duplicates(subset=["begin", "cls", "obs"]).sort_values("peak").reset_index(drop=True)
    return df


def ensure_events_year(year: int) -> pd.DataFrame:
    path = CACHE / "events" / f"events_{year}.parquet"
    now = _utcnow()
    current = year >= now.year - (1 if now.month == 1 and now.day < 3 else 0)
    with _lock_for(path):
        if path.exists() and (not current or time.time() - path.stat().st_mtime < 1800):
            return pd.read_parquet(path)
        _set_progress(path.name, f"Fetching {year} flare events from SWPC Warehouse FTP…")
        try:
            rows = []
            blob = WAREHOUSE.get(f"{FTP_ROOT}/{year}/{year}_events.tar.gz")
            if blob:
                with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
                    for mem in tf.getmembers():
                        if mem.isfile() and mem.name.endswith("events.txt"):
                            txt = tf.extractfile(mem).read().decode("latin-1")
                            rows += parse_events(txt, _day_from_name(mem.name))
            else:
                rows = _events_from_dir(year)
            df = _events_frame(rows)
            if df.empty and path.exists():
                return pd.read_parquet(path)
            df.to_parquet(path)
            return df
        finally:
            _set_progress(path.name, None)


def _day_from_name(name: str) -> date | None:
    m = re.search(r"(\d{4})(\d{2})(\d{2})events", name)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _events_from_dir(year: int) -> list[dict]:
    """Current year: one file per day in /pub/warehouse/YYYY/YYYY_events/. Raw files are cached."""
    raw = CACHE / "events" / str(year)
    raw.mkdir(exist_ok=True)
    remote = f"{FTP_ROOT}/{year}/{year}_events"
    names = sorted(n for n in WAREHOUSE.listdir(remote) if n.endswith("events.txt") and n.startswith(str(year)))
    today = _utcnow().date()
    rows = []
    for k, n in enumerate(names):
        local = raw / n
        d = _day_from_name(n)
        stale = d is not None and (today - d).days <= 3     # recent days are still being edited
        if not local.exists() or stale:
            _set_progress(f"events_{year}.parquet", f"Fetching {year} flare events from SWPC Warehouse FTP ({k + 1}/{len(names)})…")
            data = WAREHOUSE.get(f"{remote}/{n}")
            if data is not None:
                local.write_bytes(data)
        if local.exists():
            rows += parse_events(local.read_text("latin-1"), d)
    return rows


def load_events(start: datetime, end: datetime) -> pd.DataFrame:
    frames = [ensure_events_year(y) for y in range(start.year, end.year + 1) if y >= 1996]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return _events_frame([])
    df = pd.concat(frames)
    return df[(df["peak"] >= start) & (df["peak"] < end)].reset_index(drop=True)


def ensure_dsd_year(year: int) -> pd.DataFrame:
    """Daily Solar Data (F10.7, sunspot number, X-ray background, flare counts). Published at year end."""
    path = CACHE / "events" / f"dsd_{year}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    if year >= _utcnow().year:
        return pd.DataFrame()
    blob = WAREHOUSE.get(f"{FTP_ROOT}/{year}/{year}_DSD.txt")
    if not blob:
        return pd.DataFrame()
    rows = []
    for line in blob.decode("latin-1").splitlines():
        t = line.split()
        if len(t) < 10 or not re.match(r"^\d{4}$", t[0]):
            continue
        try:
            d = date(int(t[0]), int(t[1]), int(t[2]))
        except ValueError:
            continue

        def num(x):
            try:
                v = float(x)
                return None if v < 0 else v
            except ValueError:
                return None
        rows.append({"day": pd.Timestamp(d), "f107": num(t[3]), "ssn": num(t[4])})
    df = pd.DataFrame(rows)
    df.to_parquet(path)
    return df


def daily_summary(start: datetime, end: datetime) -> dict:
    ev = load_events(start, end)
    days = pd.date_range(start.date(), (end - timedelta(seconds=1)).date(), freq="D")
    counts = {}
    for letter in "CMX":
        sub = ev[ev["cls"].str.startswith(letter)]
        counts[letter] = sub.groupby(sub["peak"].dt.normalize()).size().reindex(days, fill_value=0).astype(int).tolist()
    dsd = [ensure_dsd_year(y) for y in range(start.year, end.year + 1) if y >= 1996]
    dsd = [d for d in dsd if not d.empty]
    f107 = ssn = [None] * len(days)
    if dsd:
        d = pd.concat(dsd).drop_duplicates("day").set_index("day").reindex(days)
        f107 = [None if pd.isna(v) else float(v) for v in d["f107"]]
        ssn = [None if pd.isna(v) else float(v) for v in d["ssn"]]
    return {"days": [x.strftime("%Y-%m-%d") for x in days], **counts, "f107": f107, "ssn": ssn}


def cache_info() -> dict:
    files = list((CACHE / "flux").glob("*.parquet")) + list((CACHE / "events").glob("*.parquet"))
    return {"files": len(files), "bytes": sum(f.stat().st_size for f in files)}
