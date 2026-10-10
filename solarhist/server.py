"""FastAPI server: JSON API + static single-page UI."""
from __future__ import annotations

import io
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import core, images, omni

STATIC = Path(__file__).resolve().parent.parent / "static"
app = FastAPI(title="Solar X-ray History")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _parse(s: str) -> datetime:
    try:
        ts = pd.Timestamp(s)
    except Exception:
        raise HTTPException(400, f"bad time: {s}")
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.to_pydatetime()


def _range(start: str, end: str) -> tuple[datetime, datetime]:
    a, b = _parse(start), _parse(end)
    if b <= a:
        raise HTTPException(400, "end must be after start")
    return a, b


def _sat(sat: str) -> int | None:
    if sat == "auto":
        return None
    try:
        n = int(sat)
    except ValueError:
        raise HTTPException(400, "sat must be auto or a GOES number")
    if n not in core.SAT_YEARS:
        raise HTTPException(400, f"no science XRS data for GOES-{n}")
    return n


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/flux")
def flux(start: str, end: str, sat: str = "auto", points: int = Query(3000, ge=100, le=20000)):
    a, b = _range(start, end)
    df, used = core.load_flux(a, b, _sat(sat))
    out = core.downsample(df, a, b, points)
    out["sats"] = used
    out["first"] = df.index.min().isoformat() if len(df) else None
    out["last"] = df.index.max().isoformat() if len(df) else None
    return out


@app.get("/api/flares")
def flares(start: str, end: str, min_class: str = "C"):
    a, b = _range(start, end)
    ev = core.load_events(a, b)
    thresh = core.class_to_flux(min_class + "1.0") if min_class in "ABCMX" else 0
    ev = ev[ev["peak_flux"] >= thresh]
    rows = []
    for r in ev.itertuples():
        rows.append({"begin": r.begin.isoformat(), "peak": r.peak.isoformat(),
                     "end": r.end.isoformat() if pd.notna(r.end) else None,
                     "cls": r.cls, "flux": r.peak_flux, "region": r.region if isinstance(r.region, str) else None,
                     "int_flux": float(r.int_flux) if pd.notna(r.int_flux) else None,
                     "obs": r.obs})
    return {"flares": rows}


@app.get("/api/daily")
def daily(start: str, end: str):
    a, b = _range(start, end)
    return core.daily_summary(a, b)


@app.get("/api/status")
def status():
    return {"progress": core.progress(), "cache": core.cache_info()}


@app.get("/api/export.csv")
def export(start: str, end: str, sat: str = "auto"):
    a, b = _range(start, end)
    if b - a > timedelta(days=400):
        raise HTTPException(400, "export is limited to 400 days of 1-minute data per file")
    df, _ = core.load_flux(a, b, _sat(sat))
    buf = io.StringIO()
    buf.write("time_utc,xrsa_0.5-4A_Wm2,xrsb_1-8A_Wm2,goes_sat\n")
    for t, r in zip(df.index, df.itertuples(index=False)):
        buf.write(f"{t:%Y-%m-%dT%H:%M:%SZ},{'' if pd.isna(r.a) else f'{r.a:.4e}'},"
                  f"{'' if pd.isna(r.b) else f'{r.b:.4e}'},{r.sat}\n")
    name = f"goes_xrs_{a:%Y%m%d}_{b:%Y%m%d}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/images")
def images_at(time: str):
    t = _parse(time)
    return {"time": t.isoformat(), "images": images.images_at(t)}


@app.get("/api/img")
def img(key: str, date: str, size: int = 512):
    if key not in images.BY_KEY:
        raise HTTPException(404, "unknown sensor")
    try:
        datetime.fromisoformat(date)
    except ValueError:
        raise HTTPException(400, "bad date")
    try:
        png = images.render(key, date, size)
    except Exception as e:
        raise HTTPException(502, f"Helioviewer: {e}")
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/effects")
def effects(start: str, end: str, points: int = Query(1500, ge=100, le=10000)):
    a, b = _range(start, end)
    return omni.effects(a, b, points)
