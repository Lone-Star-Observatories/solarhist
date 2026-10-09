# Solar X-ray History

A local web app for browsing GOES X-ray flux (the same 0.5–4 Å and 1–8 Å channels as the SWPC
"GOES X-ray Flux" plot) over any window from **1995 to now**, not only the last 7 days.

```
./run.sh            # starts http://127.0.0.1:8765 and opens it
```

## Where the data comes from (fetched on demand, cached in `cache/`)

| What | Source | Coverage |
|---|---|---|
| 1-min XRS flux, GOES-16/17/18/19 | NCEI `data.ngdc.noaa.gov/.../goesNN/l2/data/xrsf-l2-avg1m_science/` (yearly files) | 2017 → yesterday |
| 1-min XRS flux, GOES-8…15 | NCEI `ncei.noaa.gov/data/goes-space-environment-monitor/access/science/xrs/` (daily files) | 1995 → 2020 |
| Last few hours | SWPC `services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json` | last 7 days |
| Flare event lists | SWPC Warehouse FTP `ftp.swpc.noaa.gov/pub/warehouse/YYYY/` | 1996 → today |
| Solar images (EUV, X-ray, H-alpha, magnetograms, coronagraphs) | Helioviewer API (`api.helioviewer.org`) | 1991 → now |
| F10.7 / sunspot number | SWPC Warehouse `YYYY_DSD.txt` | 1996 → last full year |

"Auto" picks the operational primary satellite for each period (G8 → G12 → G10 → G15 → G16 → G19) and
falls back to the others when the primary has no data. You can also pick one satellite directly.

The first view of a new period downloads it: about 30 MB per year for GOES-16+, and about 365 small files
per year for older satellites. After that it loads instantly from cache.

## Using it
- Presets: 1d … 11y / All. Drag on the chart to zoom, and the app refetches at full resolution.
  Double-click zooms out ×4.
- For long ranges, each point is the **max** flux in its time bucket, so flare peaks are never lost.
  The faint line is the bucket minimum (the background level).
- Flare markers and the flare list come from SWPC's edited event lists. Click a flare to zoom to it.
- **Solar imagery**: click anywhere on the chart (or on a flare) to show images from every sensor that was
  imaging at that time. That includes SDO AIA/HMI, GOES SUVI, SOHO EIT/MDI/LASCO, STEREO, PROBA2 SWAP,
  Hinode XRT, GONG H-alpha, TRACE, Yohkoh and GOES CCOR-1. Each tile shows how far its image is from the
  selected time. Click a tile to enlarge it, and use ◀ ▶ / play (or ←, →, space) to step through time.
- **LCARS skin**: the LCARS / Standard button in the header switches to a TNG-style interface (or open
  `/?skin=lcars`). In that skin the time presets move to the sidebar, the sidebar shows live readouts, and the
  AUDIO button turns the console chirps on or off. The app remembers your choice.
- **CSV** exports the 1-minute data for the current window (up to 400 days).
- The URL hash holds the view, so you can bookmark a window.

Notes: science-quality data for GOES-8…15 has SWPC's old scaling factors removed. Their 1–8 Å flux is
about 1.4× (and 0.5–4 Å about 1.18×) what SWPC's historical plots showed, which matches what GOES-16+ reports. The Warehouse event
lists are SWPC's preliminary values. For example, the 2003-11-04 flare is listed there as X17.4
(saturated), but the science flux reconstructs it at about X25.
