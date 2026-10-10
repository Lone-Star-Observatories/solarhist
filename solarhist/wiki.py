"""Wikipedia intro summaries for the glossary tooltips.

Uses the MediaWiki Action API (up to 20 titles per request) and caches results on disk for 30 days,
so hovering terms never hammers Wikipedia. Rate-limit (429) responses are backed off, not retried in a loop.
"""
from __future__ import annotations

import json
import threading
import time

from .core import CACHE, HTTP

API = "https://en.wikipedia.org/w/api.php"
UA = "solarhist/1.0 (https://github.com/Lone-Star-Observatories/solarhist; glossary tooltips)"
PATH = CACHE / "wiki.json"
TTL = 30 * 86400
_lock = threading.Lock()
_backoff_until = 0.0
try:
    _cache: dict = json.loads(PATH.read_text())
except Exception:
    _cache = {}


def _fetch(titles: list[str]) -> dict:
    r = HTTP.get(API, timeout=30, headers={"User-Agent": UA}, params={
        "action": "query", "format": "json", "prop": "extracts|info", "exintro": 1, "explaintext": 1,
        "exsentences": 3, "exlimit": 20, "inprop": "url", "redirects": 1, "titles": "|".join(titles)})
    if r.status_code == 429:
        raise RuntimeError("rate limited")
    r.raise_for_status()
    q = r.json().get("query", {})
    alias = {}
    for m in (q.get("normalized") or []) + (q.get("redirects") or []):
        alias[m["to"]] = alias.get(m["from"], m["from"])
    out = {}
    for p in q.get("pages", {}).values():
        req = alias.get(p.get("title"), p.get("title"))
        req = alias.get(req, req)
        if "missing" in p:
            out[req] = None
        else:
            out[req] = {"title": p["title"], "extract": (p.get("extract") or "").strip(),
                        "url": p.get("fullurl") or f"https://en.wikipedia.org/wiki/{p['title'].replace(' ', '_')}"}
    for t in titles:               # requested titles the API didn't echo back
        out.setdefault(t, None)
    return out


def summaries(titles: list[str]) -> dict:
    global _backoff_until
    titles = [t for t in dict.fromkeys(titles) if t][:200]
    now = time.time()
    with _lock:
        todo = [t for t in titles if t not in _cache or now - _cache[t].get("_t", 0) > TTL]
    if todo and now >= _backoff_until:
        for i in range(0, len(todo), 20):
            try:
                got = _fetch(todo[i:i + 20])
            except Exception:
                _backoff_until = time.time() + 300     # wait 5 min after a 429 / network error
                break
            with _lock:
                for k, v in got.items():
                    _cache[k] = {"_t": time.time(), "page": v}
        with _lock:
            try:
                PATH.write_text(json.dumps(_cache))
            except Exception:
                pass
    with _lock:
        return {t: (_cache[t]["page"] if t in _cache else None) for t in titles}
