"""Where on the Sun a flare happened, in helioprojective arcseconds (as seen from Earth).

Primary: the Heliophysics Event Knowledgebase (HEK, lmsal.com/hek) flare events near the peak time.
Fallback (2010 →): NASA DONKI flare source location (Stonyhurst lat/lon) converted to helioprojective.
"""
from __future__ import annotations

import json
import math
import re
import threading
from datetime import datetime, timedelta

from .core import CACHE, HTTP

HEK = "https://www.lmsal.com/hek/her"
PREFER = ["SSW Latest Events", "Flare Detective - Trigger Module", "SolarSoft", "SWPC"]
_cache_path = CACHE / "cme" / "flareloc.json"
_lock = threading.Lock()
try:
    _cache: dict = json.loads(_cache_path.read_text())
except Exception:
    _cache = {}


def _hek(peak: datetime, cls: str | None) -> dict | None:
    r = HTTP.get(HEK, timeout=60, params={
        "cosec": 2, "cmd": "search", "type": "column", "event_type": "fl",
        "event_starttime": (peak - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"),
        "event_endtime": (peak + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"),
        "event_coordsys": "helioprojective", "x1": -1500, "x2": 1500, "y1": -1500, "y2": 1500,
        "result_limit": 100, "return": "hpc_x,hpc_y,event_peaktime,fl_goescls,frm_name"})
    r.raise_for_status()
    rows = r.json().get("result", [])
    best, score = None, None
    for e in rows:
        x, y = e.get("hpc_x"), e.get("hpc_y")
        if x is None or y is None or (abs(x) < 1e-6 and e.get("frm_name") == "SWPC"):
            continue                     # SWPC entries carry a placeholder x = 0 when the location is unknown
        try:
            dt = abs((datetime.fromisoformat(e["event_peaktime"]) - peak).total_seconds()) / 60
        except Exception:
            continue
        frm = e.get("frm_name") or ""
        rank = PREFER.index(frm) if frm in PREFER else len(PREFER)
        same_cls = 0 if cls and (e.get("fl_goescls") or "").upper() == cls.upper() else 1
        s = (same_cls, rank, dt)
        if dt <= 20 and (score is None or s < score):
            best, score = {"x": float(x), "y": float(y), "source": f"HEK · {frm}"}, s
    return best


def _b0_deg(t: datetime) -> float:
    """Heliographic latitude of the disc centre (B0), low-precision."""
    jd = (t - datetime(2000, 1, 1, 12)).total_seconds() / 86400 + 2451545.0
    n = jd - 2451545.0
    L = math.radians((280.460 + 0.9856474 * n) % 360)
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = L + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)
    omega = math.radians(73.6667 + 1.3958333 * (jd - 2396758.0) / 36525)
    return math.degrees(math.asin(math.sin(lam - omega) * math.sin(math.radians(7.25))))


def _donki(peak: datetime, cls: str | None) -> dict | None:
    from . import cmes
    if peak < cmes.DONKI_FROM:
        return None
    rows = cmes._donki("FLR", peak - timedelta(days=1), peak + timedelta(days=1))
    for f in rows:
        try:
            dt = abs((cmes._t(f.get("peakTime")) - peak).total_seconds()) / 60
        except Exception:
            continue
        m = re.match(r"^([NS])(\d+)([EW])(\d+)$", f.get("sourceLocation") or "")
        if dt > 15 or not m:
            continue
        lat = math.radians(int(m.group(2)) * (1 if m.group(1) == "N" else -1))
        lon = math.radians(int(m.group(4)) * (1 if m.group(3) == "W" else -1))
        b0 = math.radians(_b0_deg(peak))
        rsun = 959.6                       # arcsec at 1 AU; good enough for a crosshair
        x = rsun * math.cos(lat) * math.sin(lon)
        y = rsun * (math.sin(lat) * math.cos(b0) - math.cos(lat) * math.cos(lon) * math.sin(b0))
        return {"x": round(x, 1), "y": round(y, 1), "source": f"DONKI · {f['sourceLocation']}"}
    return None


def locate(peak: datetime, cls: str | None) -> dict | None:
    key = f"{peak:%Y%m%dT%H%M}_{cls or ''}"
    with _lock:
        if key in _cache:
            return _cache[key]
    loc = None
    try:
        loc = _hek(peak, cls)
    except Exception:
        loc = None
    if loc is None:
        try:
            loc = _donki(peak, cls)
        except Exception:
            loc = None
    with _lock:
        _cache[key] = loc
        try:
            _cache_path.write_text(json.dumps(_cache))
        except Exception:
            pass
    return loc
