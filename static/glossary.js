// Glossary tooltips: every piece of jargon / every measurement in the UI is wrapped in
// <span class="term" data-term="key">…</span>. Hover (or tap) shows a plain-language explanation,
// the Wikipedia intro (fetched once via /api/wiki and cached server-side) and links to Wikipedia and
// to the data source the app actually uses.
"use strict";

const SRC = {
  swpcXray: ["NOAA SWPC · GOES X-ray flux", "https://www.swpc.noaa.gov/products/goes-x-ray-flux"],
  ncei: ["NOAA NCEI · GOES-R space weather data", "https://www.ncei.noaa.gov/products/satellite/goes-r"],
  nceiXrs: ["NOAA NCEI · GOES XRS science data", "https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/"],
  warehouse: ["NOAA SWPC · Warehouse (event lists, FTP)", "ftp://ftp.swpc.noaa.gov/pub/warehouse/"],
  scales: ["NOAA SWPC · Space weather scales (R, S, G)", "https://www.swpc.noaa.gov/noaa-scales-explanation"],
  drap: ["NOAA SWPC · D-RAP (D-region absorption)", "https://www.swpc.noaa.gov/products/d-region-absorption-predictions-d-rap"],
  solcalc: ["NOAA GML · Solar position calculator", "https://gml.noaa.gov/grad/solcalc/"],
  omni: ["NASA SPDF · OMNIWeb", "https://omniweb.gsfc.nasa.gov/"],
  hapi: ["NASA CDAWeb · HAPI server", "https://cdaweb.gsfc.nasa.gov/hapi"],
  kp: ["GFZ Potsdam · Kp index", "https://kp.gfz.de/en/"],
  dst: ["WDC for Geomagnetism, Kyoto · Dst", "https://wdc.kugi.kyoto-u.ac.jp/dstdir/"],
  protons: ["NOAA SWPC · GOES proton flux", "https://www.swpc.noaa.gov/products/goes-proton-flux"],
  donki: ["NASA CCMC · DONKI", "https://ccmc.gsfc.nasa.gov/tools/DONKI/"],
  cdaw: ["NASA CDAW · SOHO/LASCO CME catalog", "https://cdaw.gsfc.nasa.gov/CME_list/"],
  hek: ["LMSAL · Heliophysics Event Knowledgebase", "https://www.lmsal.com/hek/"],
  helioviewer: ["Helioviewer (ESA/NASA)", "https://helioviewer.org/"],
  sdo: ["NASA · Solar Dynamics Observatory", "https://sdo.gsfc.nasa.gov/"],
  soho: ["ESA/NASA · SOHO", "https://soho.nascom.nasa.gov/"],
  stereo: ["NASA · STEREO", "https://stereo.gsfc.nasa.gov/"],
  proba2: ["ROB · PROBA2 Science Center", "https://proba2.sidc.be/"],
  hinode: ["NAOJ/NASA · Hinode XRT", "https://xrt.cfa.harvard.edu/"],
  gong: ["NSO · GONG H-alpha network", "https://gong.nso.edu/"],
  solo: ["ESA · Solar Orbiter", "https://www.esa.int/Science_Exploration/Space_Science/Solar_Orbiter"],
  f107: ["NRCan · 10.7 cm solar radio flux", "https://www.spaceweather.gc.ca/forecast-prevision/solar-solaire/solarflux/sx-en.php"],
  silso: ["SILSO (Royal Observatory of Belgium) · sunspot number", "https://www.sidc.be/SILSO/"],
  regions: ["NOAA SWPC · Solar region summary", "https://www.swpc.noaa.gov/products/solar-region-summary"],
  aurora: ["NOAA SWPC · Aurora forecast (OVATION)", "https://www.swpc.noaa.gov/products/aurora-30-minute-forecast"],
};

// key: [display name, plain-language explanation, Wikipedia title (or null), data source key (or null)]
const GLOSSARY = {
  goes: ["GOES", "NOAA's Geostationary Operational Environmental Satellites. GOES-8 to GOES-19 carry the X-ray Sensor (XRS) this app plots. \"G16\" in the flare list means the event was measured by GOES-16. \"Auto\" uses whichever satellite was NOAA's primary at the time.", "Geostationary Operational Environmental Satellite", "ncei"],
  xrs: ["XRS (X-Ray Sensor)", "Two-channel solar X-ray photometer on GOES. Measures the Sun's total X-ray brightness every second; the app uses NOAA's science-quality 1-minute averages.", "X-ray", "nceiXrs"],
  xrsb: ["XRS-B, 1–8 Å", "The 'long' X-ray channel (0.1–0.8 nm). It defines the flare class: the peak 1–8 Å flux sets A/B/C/M/X. Orange line on the chart.", "Solar flare", "swpcXray"],
  xrsa: ["XRS-A, 0.5–4 Å", "The 'short', harder X-ray channel (0.05–0.4 nm). Rises sharply in hotter flares. Blue line on the chart.", "X-ray", "swpcXray"],
  flux: ["X-ray flux (W/m²)", "Power per square metre arriving at Earth in that wavelength band (irradiance). The quiet Sun is ~10⁻⁷ W/m²; an X1 flare peaks at 10⁻⁴ W/m².", "Irradiance", "swpcXray"],
  angstrom: ["Ångström (Å)", "Unit of length: 10⁻¹⁰ m = 0.1 nm. 1–8 Å is the soft X-ray band.", "Angstrom", null],
  flareclass: ["Flare class (A, B, C, M, X)", "Logarithmic scale from the peak 1–8 Å flux: A < 10⁻⁷, B 10⁻⁷, C 10⁻⁶, M 10⁻⁵, X ≥ 10⁻⁴ W/m². The number multiplies it: M5 = 5×10⁻⁵, X8.7 = 8.7×10⁻⁴ W/m².", "Solar flare", "swpcXray"],
  flare: ["Solar flare", "A sudden release of magnetic energy in the Sun's atmosphere that brightens across the spectrum, especially X-rays. Times in the list are begin / peak / end as seen by GOES at Earth.", "Solar flare", "warehouse"],
  eventlist: ["SWPC edited event list", "NOAA's daily reports of solar events (flares, radio bursts …) as originally published. The app reads the X-ray flares (XRA) from them; values are preliminary.", "Solar flare", "warehouse"],
  ar: ["Active region (AR)", "A magnetically complex area of the Sun, usually with sunspots, numbered by NOAA (e.g. AR 3664). Most big flares and CMEs come from them.", "Active region", "regions"],
  utc: ["UTC", "Coordinated Universal Time. All times in this app are UTC, as used by every space-weather data set.", "Coordinated Universal Time", null],
  intflux: ["Integrated flux (J/m²)", "The 1–8 Å energy that arrived per square metre over the whole flare (flux added up over time), from SWPC's event list.", "Radiant exposure", "warehouse"],
  resolution: ["Points / max per bucket", "Long windows have more 1-minute samples than the screen can show, so each plotted point is the maximum in its time bucket (the faint line is the minimum). Flare peaks are never averaged away. Zoom in to see true 1-minute data.", null, null],
  f107: ["F10.7 radio flux (sfu)", "The Sun's radio brightness at 10.7 cm wavelength, measured daily in Canada since 1947. A standard proxy for solar activity. 1 sfu = 10⁻²² W m⁻² Hz⁻¹.", "Solar flux unit", "f107"],
  ssn: ["Sunspot number", "Daily count of sunspots and sunspot groups (Wolf number), the oldest solar-activity index.", "Sunspot number", "silso"],
  au: ["Astronomical unit (AU)", "The mean Sun–Earth distance, 149.6 million km. Earth's actual distance varies from 0.983 AU (early January) to 1.017 AU (early July), which changes the light travel time.", "Astronomical unit", null],
  lighttime: ["Light travel time", "X-rays travel at the speed of light: 499 s per AU, so 490–507 s depending on the date. GOES timestamps are when the light arrived; the flare happened ~8.3 minutes earlier.", "Astronomical unit", null],
  peakpower: ["Peak power hitting Earth", "Peak 1–8 Å flux × Earth's cross-section (πR⊕², 1.28×10¹⁴ m²). The energy that actually reached our planet in that band.", "Irradiance", "swpcXray"],
  tnt: ["kt TNT", "Energy expressed as kilotons of TNT: 1 kt = 4.184×10¹² J. The X-ray energy is absorbed 60–100 km up, not at the ground.", "TNT equivalent", null],
  joule: ["Joule (J)", "SI unit of energy. 1 W for 1 s.", "Joule", null],
  fraction: ["Fraction that hits Earth", "If a flare shines equally in all directions, Earth catches only its cross-section divided by a sphere 1 AU in radius: πR⊕² / 4πr² ≈ 4.5×10⁻¹⁰.", "Inverse-square law", null],
  rscale: ["R-scale (radio blackout)", "NOAA's radio-blackout scale from the peak X-ray class: R1 Minor (M1), R2 Moderate (M5), R3 Strong (X1), R4 Severe (X10), R5 Extreme (X20). HF radio fades on the sunlit side of Earth.", "Sudden ionospheric disturbance", "scales"],
  gscale: ["G-scale (geomagnetic storm)", "NOAA's storm scale from Kp: G1 Minor (Kp 5), G2 Moderate (6), G3 Strong (7), G4 Severe (8), G5 Extreme (9).", "Geomagnetic storm", "scales"],
  sscale: ["S-scale (radiation storm)", "NOAA's solar-radiation-storm scale from the >10 MeV proton flux: S1 ≥10 pfu, S2 ≥100, S3 ≥10³, S4 ≥10⁴, S5 ≥10⁵.", "Solar particle event", "scales"],
  hf: ["HF radio", "High-frequency radio, 3–30 MHz: shortwave, aviation and maritime, amateur radio. It relies on the ionosphere, which flares disturb.", "High frequency", null],
  drap: ["D-RAP absorption model", "NOAA's D-Region Absorption Prediction. The highest HF frequency blacked out is ≈ (10·log₁₀F + 65) MHz where the Sun is overhead (F = 1–8 Å flux in W/m²), falling off with cos^0.75 of the solar zenith angle. Only the dayside is affected.", "Ionosphere", "drap"],
  subsolar: ["Subsolar point", "The spot on Earth where the Sun is directly overhead at that moment. X-ray absorption, and the radio blackout, is strongest there. Computed with NOAA's solar-position formulas.", "Subsolar point", "solcalc"],
  zenith: ["Solar zenith angle", "Angle between straight up and the Sun. 0° at the subsolar point, 90° at sunrise/sunset.", "Solar zenith angle", "solcalc"],
  auroraoval: ["Auroral oval (approx.)", "The rings around the magnetic poles where aurora occur. During storms they expand toward the equator; here approximated as 66° − 2°×Kp magnetic latitude. Rough guide only.", "Aurora", "aurora"],
  spaceweather: ["Space weather", "Conditions in space driven by the Sun (flares, CMEs, solar wind) that affect satellites, radio, power grids and aurora.", "Space weather", "scales"],
  solarwind: ["Solar wind speed & density", "The stream of plasma flowing from the Sun, measured upstream of Earth (shifted to Earth's bow shock in OMNI). Typical: 300–500 km/s and ~5 protons/cm³; CME shocks jump it to 700–2000 km/s.", "Solar wind", "omni"],
  bz: ["Bz (IMF, GSM)", "North–south component of the interplanetary magnetic field carried by the solar wind, in Earth's GSM frame. Strongly negative (southward) Bz lets energy into the magnetosphere and drives storms. The band shows min–max per bucket.", "Interplanetary magnetic field", "omni"],
  nT: ["nanotesla (nT)", "Unit of magnetic field: 10⁻⁹ tesla. Earth's surface field is ~50,000 nT; the solar wind's is ~5 nT.", "Tesla (unit)", null],
  kp: ["Kp index", "Planetary 3-hour index of geomagnetic disturbance from 0 (quiet) to 9 (extreme), from a global network of magnetometers. Bars are coloured by NOAA G-level.", "K-index", "kp"],
  dst: ["Dst index (nT)", "Disturbance storm-time index: the drop in Earth's equatorial magnetic field caused by the storm-time ring current. −50 nT moderate, −100 intense, below −300 is a superstorm (May 2024 reached about −410).", "Disturbance storm time index", "dst"],
  protons: [">10 MeV protons (pfu)", "Flux of energetic protons above 10 MeV at GOES, in particle flux units (1 pfu = 1 proton cm⁻² s⁻¹ sr⁻¹). Big flares/CMEs can raise it within 20 min to hours. Before 2020 from OMNI; from 2020 computed from GOES-16+ SGPS channels.", "Solar particle event", "protons"],
  mev: ["MeV", "Mega-electronvolt, a unit of particle energy: 1 MeV ≈ 1.6×10⁻¹³ J. A 10 MeV proton moves at ~15% of the speed of light.", "Electronvolt", null],
  omni: ["NASA OMNI", "NASA's merged, quality-checked solar-wind data set from many spacecraft (ACE, Wind, DSCOVR …), time-shifted to Earth, plus Kp, Dst and protons. Lags real time by ~10 days, so the newest hours come from NOAA SWPC.", null, "omni"],
  cme: ["Coronal mass ejection (CME)", "A huge cloud of magnetised plasma thrown off the Sun, often with a big flare. Earth-directed CMEs arrive in 1–3 days and cause geomagnetic storms. Diamonds on the chart mark launches (size = speed).", "Coronal mass ejection", "donki"],
  halo: ["Halo CME", "A CME that appears as an expanding ring all around the Sun in coronagraph images, meaning it's heading toward (or directly away from) Earth.", "Coronal mass ejection", "cdaw"],
  cmetype: ["CME type (S, C, O, R, ER)", "DONKI's speed classes: S < 500 km/s, C 500–999, O 1000–1999, R 2000–2999, ER ≥ 3000 km/s.", "Coronal mass ejection", "donki"],
  shock: ["Shock arrival at Earth", "The interplanetary shock ahead of a CME reaching the spacecraft upstream of Earth: a sudden jump in solar-wind speed, density and field. Storms usually follow within hours.", "Shock wave", "donki"],
  storm: ["Geomagnetic storm", "A major disturbance of Earth's magnetosphere when a CME or fast wind couples to it. Measured by Kp (G-scale) and Dst.", "Geomagnetic storm", "donki"],
  donki: ["NASA DONKI", "The Space Weather Database Of Notifications, Knowledge, Information at NASA's CCMC. Links flares, CMEs, shocks and storms to each other (2010 →).", null, "donki"],
  cdaw: ["SOHO/LASCO CDAW catalog", "NASA's catalog of every CME seen by SOHO's LASCO coronagraphs since 1996, with speeds and widths. Used here before 2010.", "Large Angle and Spectrometric Coronagraph", "cdaw"],
  hek: ["HEK", "The Heliophysics Event Knowledgebase (LMSAL), an index of solar events detected by people and automated pipelines, with positions on the Sun.", null, "hek"],
  helioprojective: ["Helioprojective arcsec", "Position on the solar disc as seen from Earth: x (west +) and y (north +) in arcseconds from disc centre. The Sun's edge is at ~960″.", "Solar coordinate systems", "hek"],
  helioviewer: ["Helioviewer", "ESA/NASA service that serves archived solar images from many missions; the app asks it for the closest image to the selected time from each instrument.", null, "helioviewer"],
  euv: ["Extreme ultraviolet (EUV)", "Light at ~10–120 nm, emitted by the hot corona. Different wavelengths (94, 131, 171, 193, 211, 304, 335 Å …) show plasma at different temperatures.", "Extreme ultraviolet", null],
  sdo: ["SDO AIA / HMI", "NASA's Solar Dynamics Observatory (2010 →). AIA images the corona in 10 EUV/UV wavelengths every 12 s; HMI maps the surface magnetic field (magnetogram) and visible light (continuum).", "Solar Dynamics Observatory", "sdo"],
  suvi: ["GOES SUVI", "The Solar Ultraviolet Imager on GOES-16 and later: six EUV channels every few minutes from the same satellites as the X-ray data.", "Geostationary Operational Environmental Satellite", "ncei"],
  soho: ["SOHO (EIT, MDI, LASCO)", "ESA/NASA observatory at the L1 point since 1996. EIT: EUV imager; MDI: magnetograms (to 2011); LASCO: coronagraphs that see CMEs.", "Solar and Heliospheric Observatory", "soho"],
  stereo: ["STEREO", "Twin NASA spacecraft orbiting the Sun ahead of/behind Earth (STEREO-B lost in 2014), seeing the Sun and CMEs from the side.", "STEREO", "stereo"],
  coronagraph: ["Coronagraph", "A telescope that blocks the bright solar disc (the dark circle) to see the faint corona and CMEs leaving the Sun.", "Coronagraph", "soho"],
  swap: ["PROBA2 SWAP", "ESA microsatellite EUV imager at 174 Å with a wide field of view (2010 →).", "PROBA-2", "proba2"],
  xrt: ["Hinode XRT", "The X-Ray Telescope on JAXA/NASA's Hinode (2006 →), imaging hot coronal plasma.", "Hinode (satellite)", "hinode"],
  sxt: ["Yohkoh SXT", "The Soft X-ray Telescope on Japan's Yohkoh mission (1991–2001).", "Yohkoh", null],
  trace: ["TRACE", "NASA's Transition Region and Coronal Explorer (1998–2010): high-resolution EUV images of part of the Sun.", "TRACE", null],
  gong: ["GONG H-alpha", "Ground-based network of six observatories imaging the Sun in red hydrogen-alpha light, which shows flares and filaments.", "Hydrogen-alpha", "gong"],
  solo: ["Solar Orbiter EUI", "ESA/NASA's Solar Orbiter (2020 →) Extreme Ultraviolet Imager. Sees the Sun from a different angle than Earth.", "Solar Orbiter", "solo"],
  magnetogram: ["Magnetogram", "Map of the magnetic field on the Sun's surface: white and black are opposite polarities.", "Sunspot", "sdo"],
  stardate: ["Stardate", "Just for fun in the LCARS skin: here it's the year + day-of-year + tenth of a day of the selected time, not a canon formula.", "Stardate", null],
};

// Which term a solar-image sensor key belongs to.
const SENSOR_TERM = k => /^aia|^hmi/.test(k) ? "sdo" : /^suvi/.test(k) ? "suvi" : /^(eit|mdi|c2|c3)/.test(k) ? "soho"
  : /^(euvi|cor)/.test(k) ? "stereo" : /^swap/.test(k) ? "swap" : /^xrt/.test(k) ? "xrt" : /^sxt/.test(k) ? "sxt"
  : /^trace/.test(k) ? "trace" : /^halpha/.test(k) ? "gong" : /^fsi/.test(k) ? "solo" : null;

// <span class="term"> wrapper for templates
function gl(key, text) {
  return GLOSSARY[key] ? `<span class="term" data-term="${key}" tabindex="0">${text ?? GLOSSARY[key][0]}</span>` : (text ?? key);
}

// ---------------------------------------------------------------------------- popover
(function () {
  const pop = document.createElement("div");
  pop.id = "gloss";
  pop.setAttribute("role", "tooltip");
  document.body.appendChild(pop);
  let wikiData = null, wikiReq = null, cur = null, hideT = null, showT = null, pinned = false;

  function loadWiki() {
    if (wikiReq) return wikiReq;
    const titles = [...new Set(Object.values(GLOSSARY).map(g => g[2]).filter(Boolean))];
    wikiReq = fetch("/api/wiki?titles=" + encodeURIComponent(titles.join("|")))
      .then(r => r.ok ? r.json() : {}).then(d => (wikiData = d)).catch(() => (wikiData = {}));
    return wikiReq;
  }
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function render(key) {
    const [name, what, wt, sk] = GLOSSARY[key];
    const w = wt && wikiData ? wikiData[wt] : null;
    const src = sk ? SRC[sk] : null;
    let wikiHtml = "";
    if (wt) {
      wikiHtml = !wikiData ? `<div class="gw dim">Loading Wikipedia summary…</div>`
        : w && w.extract ? `<div class="gw"><span class="gl">Wikipedia${w.title !== wt ? ` · ${esc(w.title)}` : ""}:</span> ${esc(w.extract)}</div>`
        : `<div class="gw dim">Wikipedia summary unavailable right now.</div>`;
    }
    const wurl = w && w.url ? w.url : wt ? `https://en.wikipedia.org/wiki/${encodeURIComponent(wt.replace(/ /g, "_"))}` : null;
    const links = [wurl ? `<a href="${wurl}" target="_blank" rel="noopener">Wikipedia ↗</a>` : "",
      src ? `<a href="${src[1]}" target="_blank" rel="noopener">${esc(src[0])} ↗</a>` : ""].filter(Boolean).join("");
    pop.innerHTML = `<div class="gt">${esc(name)}</div><div class="gd">${esc(what)}</div>${wikiHtml}` +
      (links ? `<div class="glinks">${links}</div>` : "");
  }

  function place(el) {
    const r = el.getBoundingClientRect(), pw = pop.offsetWidth, ph = pop.offsetHeight;
    let x = Math.min(Math.max(8, r.left + r.width / 2 - pw / 2), window.innerWidth - pw - 8);
    let y = r.bottom + 8;
    if (y + ph > window.innerHeight - 8) y = Math.max(8, r.top - ph - 8);
    pop.style.left = x + "px"; pop.style.top = y + "px";
  }

  function show(el, pin = false) {
    const key = el.dataset.term;
    if (!GLOSSARY[key]) return;
    clearTimeout(hideT);
    cur = el; pinned = pin;
    render(key);
    pop.classList.add("open");
    place(el);
    if (!wikiData) loadWiki().then(() => { if (cur === el) { render(key); place(el); } });
  }
  function hide(now = false) {
    clearTimeout(showT);
    if (pinned && !now) return;
    hideT = setTimeout(() => { pop.classList.remove("open"); cur = null; pinned = false; }, now ? 0 : 220);
  }

  document.addEventListener("mouseover", e => {
    const el = e.target.closest(".term");
    if (el) { clearTimeout(hideT); if (el !== cur) { clearTimeout(showT); showT = setTimeout(() => show(el), 180); } }
    else if (e.target.closest("#gloss")) clearTimeout(hideT);
  });
  document.addEventListener("mouseout", e => {
    const from = e.target.closest(".term, #gloss"), to = e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest(".term, #gloss");
    if (from && !to) hide();
  });
  document.addEventListener("click", e => {
    const el = e.target.closest(".term");
    if (el) {
      // Inside a control (sort header, button, image tile, table row) let the control act; hover still explains.
      if (el.closest("button, th, .tile, tr[data-p], select, label")) { show(el); return; }
      e.preventDefault(); e.stopPropagation();
      if (cur === el && pinned) hide(true); else show(el, true);
      return;
    }
    if (!e.target.closest("#gloss")) hide(true);
  }, true);
  document.addEventListener("focusin", e => { const el = e.target.closest && e.target.closest(".term"); if (el) show(el); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") hide(true); });
  window.addEventListener("scroll", () => { if (cur && !pinned) hide(true); else if (cur) place(cur); }, { passive: true });
})();
