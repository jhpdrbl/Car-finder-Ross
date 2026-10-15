"""EPA fuel economy from fueleconomy.gov (US government) for listings whose page
doesn't show MPG. Cached forever per year/make/model in data/cache/fueleconomy.json.

For plug-in hybrids the figure is the gas-only MPG (after the battery is used up).
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from urllib.parse import quote

from scrapers.base import FetchError, fetcher

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "fueleconomy.json"
API = "https://www.fueleconomy.gov/ws/rest"
HDR = {"Accept": "application/json"}

MAKE_NAMES = {"Mercedes-Benz": "Mercedes-Benz", "Volkswagen": "Volkswagen", "Bmw": "BMW", "Gmc": "GMC"}


def _cache() -> dict:
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def _save(c: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(c, indent=0), encoding="utf-8")


def _items(j) -> list[dict]:
    it = (j or {}).get("menuItem") or []
    return it if isinstance(it, list) else [it]


def _get(url: str, cache: dict):
    if url in cache:
        return cache[url]
    try:
        data = fetcher().get_json(url, headers=HDR)
    except FetchError:
        return None
    cache[url] = data
    return data


def _pick_model(names: list[str], model: str, trim: str, fuel: str) -> str | None:
    want = f"{model} {trim}".lower()
    base = re.sub(r"\s+e$", "", model.lower()).replace("-", " ").split()[0] if model else ""
    best, best_score = None, -99
    for n in names:
        nl = n.lower()
        if base and base not in nl.replace("-", " ").replace(" ", "") and base not in nl:
            continue
        s = 0
        hybrid_name = bool(re.search(r"hybrid|tfsi e|recharge|t8|450h|350h|electrified|plug-in|\bphev\b", nl))
        if fuel in ("hybrid", "phev") and hybrid_name:
            s += 5
        elif fuel in ("gas", "") and hybrid_name:
            s -= 6
        if fuel == "ev" and "electrified" in nl:
            s += 6
        for tok in ("wilderness", "sportback", "sport/touring", "s-line", "350h", "450h+", "b5", "b6", "t8"):
            if tok in nl and tok.split("/")[0] in want:
                s += 3
            elif tok in nl and tok in ("wilderness", "sportback"):
                s -= 4
        if re.search(r"\bsq5\b|\bm40i\b|\bx3 m\b|\bamg\b|\bm competition", nl):
            s -= 10
        if re.search(r"sdrive|2wd|fwd|rwd", nl):
            s -= 5
        if re.search(r"awd|4wd|quattro|xdrive|4matic", nl):
            s += 1
        if s > best_score:
            best, best_score = n, s
    return best


def lookup(year: int | None, make: str, model: str, trim: str, fuel: str) -> tuple[float, float, float] | None:
    """(city, highway, combined) EPA MPG, or None."""
    if not (year and make and model):
        return None
    make = MAKE_NAMES.get(make.title(), make.title() if make.lower() not in ("bmw",) else "BMW")
    cache = _cache()
    models = _get(f"{API}/vehicle/menu/model?year={year}&make={quote(make)}", cache)
    names = [i["value"] for i in _items(models)]
    name = _pick_model(names, model, trim, fuel)
    if not name:
        _save(cache)
        return None
    opts = _items(_get(f"{API}/vehicle/menu/options?year={year}&make={quote(make)}&model={quote(name)}", cache))
    if not opts:
        _save(cache)
        return None
    # choose the engine the trim names (GV70 2.5T vs 3.5T, Q5 45 vs 55...), else take the median of all
    t = f"{model} {trim}".lower()
    disp = re.search(r"\b([1-6]\.\d)\s?t?\b", t)
    if not disp and re.search(r"\bxt\b", t):           # Subaru XT = 2.4L turbo
        disp = re.match(r"(2\.4)", "2.4")
    chosen = [o for o in opts if disp and f"{disp.group(1)} l" in o["text"].lower()] or opts
    vals = []
    for o in chosen[:4]:
        v = _get(f"{API}/vehicle/{o['value']}", cache)
        if v and v.get("comb08"):
            vals.append((float(v["city08"]), float(v["highway08"]), float(v["comb08"])))
    _save(cache)
    if not vals:
        return None
    return tuple(statistics.median(x[i] for x in vals) for i in range(3))
