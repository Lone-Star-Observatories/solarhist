"""Solar imagery around a moment in time, via the Helioviewer API (api.helioviewer.org).

For a requested time we ask Helioviewer for the closest image from every sensor that was
operating then, and serve rendered PNGs (cached on disk, keyed by the real image time).
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from .core import CACHE, HTTP

API = "https://api.helioviewer.org/v2/"
IMG_CACHE = CACHE / "img"
IMG_CACHE.mkdir(parents=True, exist_ok=True)

# scale = arcsec/pixel at 512 px (disk imagers ~4.8 → Sun fills the frame; coronagraphs wider).
# max_gap = how far (minutes) from the requested time an image may be before we call it "not available".
SENSORS = [
    # key,            label,                group,          sourceId, scale, max_gap
    ("aia94",   "AIA 94 Å",        "SDO AIA",      8,  4.8, 60),
    ("aia131",  "AIA 131 Å",       "SDO AIA",      9,  4.8, 60),
    ("aia171",  "AIA 171 Å",       "SDO AIA",      10, 4.8, 60),
    ("aia193",  "AIA 193 Å",       "SDO AIA",      11, 4.8, 60),
    ("aia211",  "AIA 211 Å",       "SDO AIA",      12, 4.8, 60),
    ("aia304",  "AIA 304 Å",       "SDO AIA",      13, 4.8, 60),
    ("aia335",  "AIA 335 Å",       "SDO AIA",      14, 4.8, 60),
    ("aia1600", "AIA 1600 Å",      "SDO AIA",      15, 4.8, 60),
    ("hmimag",  "HMI magnetogram", "SDO HMI",      19, 4.8, 90),
    ("hmicont", "HMI continuum",   "SDO HMI",      18, 4.8, 90),
    ("suvi94",  "SUVI 94 Å",       "GOES SUVI",    2000, 4.8, 60),
    ("suvi131", "SUVI 131 Å",      "GOES SUVI",    2001, 4.8, 60),
    ("suvi171", "SUVI 171 Å",      "GOES SUVI",    2002, 4.8, 60),
    ("suvi195", "SUVI 195 Å",      "GOES SUVI",    2003, 4.8, 60),
    ("suvi284", "SUVI 284 Å",      "GOES SUVI",    2004, 4.8, 60),
    ("suvi304", "SUVI 304 Å",      "GOES SUVI",    2005, 4.8, 60),
    ("eit171",  "EIT 171 Å",       "SOHO",         0,  4.8, 360),
    ("eit195",  "EIT 195 Å",       "SOHO",         1,  4.8, 120),
    ("eit284",  "EIT 284 Å",       "SOHO",         2,  4.8, 360),
    ("eit304",  "EIT 304 Å",       "SOHO",         3,  4.8, 360),
    ("mdimag",  "MDI magnetogram", "SOHO",         6,  4.8, 360),
    ("mdicont", "MDI continuum",   "SOHO",         7,  4.8, 720),
    ("swap174", "SWAP 174 Å",      "Other EUV / X-ray", 32, 4.8, 60),
    ("xrt",     "Hinode XRT",      "Other EUV / X-ray", 10001, 4.8, 360),
    ("sxt",     "Yohkoh SXT",      "Other EUV / X-ray", 33, 4.8, 360),
    ("trace171", "TRACE 171 Å",    "Other EUV / X-ray", 75, 2.4, 120),
    ("fsi174",  "SolO EUI 174 Å",  "Other EUV / X-ray", 84, 4.8, 120),
    ("halpha",  "GONG H-alpha",    "Other EUV / X-ray", 94, 4.8, 60),
    ("euvia195", "STEREO-A EUVI 195", "STEREO",    21, 4.8, 120),
    ("euvia304", "STEREO-A EUVI 304", "STEREO",    23, 4.8, 120),
    ("euvib195", "STEREO-B EUVI 195", "STEREO",    25, 4.8, 120),
    ("c2",      "LASCO C2",        "Coronagraphs", 4,  24,  120),
    ("c3",      "LASCO C3",        "Coronagraphs", 5,  110, 120),
    # GOES CCOR-1 (sourceId 132): Helioviewer's takeScreenshot currently fails for it server-side
    # ("Class Image_ImageType_CCOR-1Image not found"), so it's left out until that's fixed.
    ("cor1a",   "STEREO-A COR1",   "Coronagraphs", 28, 12,  120),
    ("cor2a",   "STEREO-A COR2",   "Coronagraphs", 29, 60,  120),
]
BY_KEY = {s[0]: s for s in SENSORS}
ENABLE = "[GOES,STEREO_A,STEREO_B,PROBA2,Hinode,SOLO,GONG,TRACE,Yohkoh]"

_ranges: dict[int, tuple[datetime, datetime]] = {}
_ranges_t = 0.0
_ranges_lock = threading.Lock()


def _source_ranges() -> dict[int, tuple[datetime, datetime]]:
    """sourceId → (first, last) image time, refreshed daily."""
    global _ranges_t
    with _ranges_lock:
        path = IMG_CACHE / "sources.json"
        if not _ranges or time.time() - _ranges_t > 86400:
            try:
                r = HTTP.get(API + "getDataSources/", params={"verbose": "true", "enable": ENABLE}, timeout=60)
                r.raise_for_status()
                tree = r.json()
                path.write_text(json.dumps(tree))
            except Exception:
                if not path.exists():
                    return {}
                tree = json.loads(path.read_text())
            out = {}

            def walk(n):
                if isinstance(n, dict) and "sourceId" in n:
                    try:
                        out[int(n["sourceId"])] = (datetime.fromisoformat(n["start"]), datetime.fromisoformat(n["end"]))
                    except Exception:
                        pass
                elif isinstance(n, dict):
                    for v in n.values():
                        walk(v)
            walk(tree)
            _ranges.clear()
            _ranges.update(out)
            _ranges_t = time.time()
        return dict(_ranges)


_closest: dict[tuple[int, str], dict | None] = {}


def _closest_image(source_id: int, t: datetime) -> dict | None:
    key = (source_id, t.strftime("%Y-%m-%dT%H:%M"))
    if key in _closest:
        return _closest[key]
    try:
        r = HTTP.get(API + "getClosestImage/", params={"date": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "sourceId": source_id},
                     timeout=30)
        j = r.json()
        res = {"date": datetime.fromisoformat(j["date"]), "id": j.get("id")} if "date" in j else None
    except Exception:
        return None                     # don't cache transient failures
    _closest[key] = res
    return res


def images_at(t: datetime) -> list[dict]:
    ranges = _source_ranges()
    cands = []
    for key, label, group, sid, scale, gap in SENSORS:
        rng = ranges.get(sid)
        if rng and not (rng[0] - timedelta(minutes=gap) <= t <= rng[1] + timedelta(minutes=gap)):
            continue
        cands.append((key, label, group, sid, scale, gap))
    with ThreadPoolExecutor(12) as pool:
        found = list(pool.map(lambda c: _closest_image(c[3], t), cands))
    out = []
    for (key, label, group, sid, scale, gap), hit in zip(cands, found):
        if not hit:
            continue
        delta = (hit["date"] - t).total_seconds() / 60
        if abs(delta) > gap:
            continue
        d = hit["date"].strftime("%Y-%m-%dT%H:%M:%S")
        out.append({"key": key, "label": label, "group": group, "sourceId": sid, "date": d,
                    "delta_min": round(delta, 1), "img": f"/api/img?key={key}&date={d}"})
    return out


_img_locks: dict[str, threading.Lock] = {}
_img_guard = threading.Lock()


def render(key: str, date: str, size: int = 512) -> bytes:
    """PNG of one sensor at (exactly) its image time; cached forever."""
    s = BY_KEY[key]
    size = 1024 if size > 512 else 512
    scale = s[4] * 512 / size
    path = IMG_CACHE / f"{key}_{date.replace(':', '')}_{size}.png"
    with _img_guard:
        lock = _img_locks.setdefault(str(path), threading.Lock())
    with lock:
        if path.exists():
            return path.read_bytes()
        r = HTTP.get(API + "takeScreenshot/", timeout=90, params={
            "date": date + "Z", "imageScale": scale, "layers": f"[{s[3]},1,100]",
            "x0": 0, "y0": 0, "width": size, "height": size, "display": "true", "watermark": "false"})
        r.raise_for_status()
        if not r.headers.get("content-type", "").startswith("image/"):
            raise RuntimeError(f"Helioviewer returned {r.headers.get('content-type')}")
        path.write_bytes(r.content)
        return r.content
