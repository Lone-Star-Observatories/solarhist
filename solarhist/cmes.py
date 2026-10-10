"""CMEs and their consequences (flare → CME → shock at Earth → geomagnetic storm).

Sources
  * NASA CCMC DONKI (2010 →): CME, FLR, IPS (interplanetary shocks), GST (geomagnetic storms),
    linked to each other by their `linkedEvents` fields.  https://ccmc.gsfc.nasa.gov/DONKI-API/get/
  * SOHO/LASCO CDAW CME catalog (1996 → 2009 here): launch time, speed, width; no linkage.
  * Dst minimum for a linked storm comes from OMNI (omni.py).
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta

import pandas as pd

from .core import CACHE, HTTP, _set_progress, _utcnow

DONKI = "https://ccmc.gsfc.nasa.gov/DONKI-API/get/"
CDAW = "https://cdaw.gsfc.nasa.gov/CME_list/UNIVERSAL_ver2/text_ver/univ_all.txt"
DONKI_FROM = datetime(2010, 4, 1)
CME_CACHE = CACHE / "cme"
CME_CACHE.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()


def _t(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "")).replace(tzinfo=None)


def _months(start: datetime, end: datetime):
    cur = datetime(start.year, start.month, 1)
    while cur < end:
        nxt = datetime(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        yield cur, nxt
        cur = nxt


def _donki_month(kind: str, m0: datetime, m1: datetime) -> list[dict]:
    path = CME_CACHE / f"donki_{kind}_{m0:%Y_%m}.json"
    current = m1 > _utcnow() - timedelta(days=45)
    if path.exists() and (not current or time.time() - path.stat().st_mtime < 3600):
        return json.loads(path.read_text())
    _set_progress(path.name, f"Fetching DONKI {kind} events {m0:%Y-%m}…")
    try:
        r = HTTP.get(DONKI + kind, timeout=90, params={"startDate": f"{m0:%Y-%m-%d}",
                                                       "endDate": f"{(m1 - timedelta(days=1)):%Y-%m-%d}"})
        r.raise_for_status()
        rows = r.json() if r.text.strip() else []
        path.write_text(json.dumps(rows))
        return rows
    except Exception:
        if path.exists():
            return json.loads(path.read_text())
        raise
    finally:
        _set_progress(path.name, None)


def _donki(kind: str, start: datetime, end: datetime) -> list[dict]:
    out = []
    for m0, m1 in _months(start, end):
        out += _donki_month(kind, m0, m1)
    return out


def _speed(c: dict):
    an = c.get("cmeAnalyses") or []
    best = next((a for a in an if a.get("isMostAccurate")), an[0] if an else None)
    if not best:
        return None, None, None
    return best.get("speed"), best.get("type"), best.get("halfAngle")


def _dst_min(t0: datetime, hours: int = 48):
    try:
        from . import omni
        h = omni._hourly(t0 - timedelta(hours=3), t0 + timedelta(hours=hours))
        v = h["dst"].dropna()
        return float(v.min()) if len(v) else None
    except Exception:
        return None


def donki_chain(start: datetime, end: datetime) -> list[dict]:
    pad = timedelta(days=5)        # shocks/storms arrive up to ~5 days after launch
    cmes = [c for c in _donki("CME", start - timedelta(days=1), end) if c.get("startTime")]
    if not cmes:
        return []
    ips = {e["activityID"]: e for e in _donki("IPS", start, end + pad)}
    gst = {e["gstID"]: e for e in _donki("GST", start, end + pad)}
    flr = {e["flrID"]: e for e in _donki("FLR", start - timedelta(days=1), end)}
    out = []
    for c in cmes:
        t0 = _t(c["startTime"])
        if not (start <= t0 < end):
            continue
        links = [e["activityID"] for e in (c.get("linkedEvents") or [])]
        speed, typ, half = _speed(c)
        flares = [{"id": f, "peak": _t(flr[f].get("peakTime")).isoformat() if flr[f].get("peakTime") else None,
                   "cls": flr[f].get("classType"), "loc": flr[f].get("sourceLocation")} for f in links if f in flr]
        arrivals = sorted((_t(ips[i]["eventTime"]) for i in links if i in ips and ips[i].get("location") == "Earth"))
        arrivals = [a for a in arrivals if a and a > t0]
        storms = [gst[g] for g in links if g in gst]
        storm = None
        if storms:
            g = max(storms, key=lambda s: max((k["kpIndex"] for k in s.get("allKpIndex") or []), default=0))
            gs = _t(g["startTime"])
            storm = {"start": gs.isoformat(), "kp_max": max((k["kpIndex"] for k in g.get("allKpIndex") or []), default=None),
                     "dst_min": _dst_min(gs)}
        out.append({
            "id": c["activityID"], "time": t0.isoformat(), "speed": speed, "type": typ, "half_angle": half,
            "source": c.get("sourceLocation") or None, "ar": c.get("activeRegionNum"),
            "flares": flares, "arrival": arrivals[0].isoformat() if arrivals else None, "storm": storm,
            "catalog": "DONKI",
        })
    return out


_cdaw_df: pd.DataFrame | None = None


def _cdaw() -> pd.DataFrame:
    global _cdaw_df
    with _lock:
        if _cdaw_df is not None:
            return _cdaw_df
        path = CME_CACHE / "cdaw_univ_all.txt"
        if not path.exists() or time.time() - path.stat().st_mtime > 7 * 86400:
            _set_progress("cdaw", "Fetching SOHO/LASCO CDAW CME catalog…")
            try:
                r = HTTP.get(CDAW, timeout=180)
                r.raise_for_status()
                path.write_text(r.text)
            except Exception:
                if not path.exists():
                    raise
            finally:
                _set_progress("cdaw", None)
        rows = []
        for line in path.read_text(errors="replace").splitlines():
            m = re.match(r"^(\d{4}/\d\d/\d\d)\s+(\d\d:\d\d:\d\d)\s+(\S+)\s+(\d+)\s+(\S+)", line)
            if not m:
                continue
            try:
                t = datetime.strptime(m.group(1) + " " + m.group(2), "%Y/%m/%d %H:%M:%S")
            except ValueError:
                continue
            speed = int(m.group(5)) if m.group(5).isdigit() else None
            rows.append((t, m.group(3), int(m.group(4)), speed))
        _cdaw_df = pd.DataFrame(rows, columns=["time", "pa", "width", "speed"])
        return _cdaw_df


def cdaw_list(start: datetime, end: datetime, min_width: int = 60) -> list[dict]:
    df = _cdaw()
    sub = df[(df["time"] >= start) & (df["time"] < end) & (df["width"] >= min_width)]
    return [{"id": f"CDAW-{r.time:%Y%m%dT%H%M%S}", "time": r.time.isoformat(), "speed": r.speed,
             "type": "halo" if r.pa == "Halo" else None, "half_angle": r.width / 2, "width": r.width,
             "source": None, "ar": None, "flares": [], "arrival": None, "storm": None, "catalog": "CDAW"}
            for r in sub.itertuples()]


def cmes(start: datetime, end: datetime) -> list[dict]:
    out = []
    if start < DONKI_FROM:
        out += cdaw_list(start, min(end, DONKI_FROM))
    if end > DONKI_FROM:
        out += donki_chain(max(start, DONKI_FROM), end)
    return out
