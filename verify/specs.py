"""Ground clearance and EPA electric range per model / year / trim, from data/specs.json
(hand-researched from manufacturer spec sheets and fueleconomy.gov). The first matching entry wins,
so the file lists trim-specific entries (Wilderness, Badlands, Extended Range...) before a model's default."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

SPECS = Path(__file__).resolve().parent.parent / "data" / "specs.json"


@lru_cache(maxsize=1)
def _specs() -> dict:
    return json.loads(SPECS.read_text(encoding="utf-8")) if SPECS.exists() else {}


def _norm(s: str) -> str:
    return re.sub(r"[\s-]+", " ", (s or "").lower()).strip()


def _find(kind: str, make: str, model: str, trim: str, year, fuel: str = "") -> dict | None:
    text = _norm(f"{model} {trim}")
    try:
        year = int(year)
    except (TypeError, ValueError):
        year = None
    for e in _specs().get(kind, []):
        if _norm(e.get("make")) != _norm(make) or _norm(e.get("model")) not in text:
            continue
        if year and not (int(e.get("from_year") or 0) <= year <= int(e.get("to_year") or 9999)):
            continue
        if e.get("fuel") and fuel and e["fuel"] != fuel:
            continue
        if e.get("trim_regex") and not re.search(e["trim_regex"], text, re.I):
            continue
        return e
    return None


def clearance(make: str, model: str, trim: str, year) -> tuple[float, str] | None:
    """(inches, source) for the model / trim's published ground clearance."""
    e = _find("clearance", make, model, trim, year)
    return (float(e["inches"]), e.get("source", "")) if e else None


def approx_clearance(model: str, trim: str) -> float | None:
    """The rough per-model figure from config.yaml (ground_clearance_in), longest name first so a CX-50 isn't a CX-5."""
    from scrapers.base import CONFIG
    table = CONFIG.get("ground_clearance_in") or {}
    text = _norm(f"{model} {trim}")
    for k in sorted(table, key=len, reverse=True):
        words = _norm(k).split()
        if words and words[0] in text.split() and all(w in text for w in words[1:]):
            return float(table[k])
    return None


def best_clearance(make: str, model: str, trim: str, year, page_value=None) -> tuple[float | None, str]:
    """One ground clearance per model / year / trim: the maker's published figure first, then the figure from
    the dealer's spec data, then the rough per-model figure. Returns (inches, where it came from)."""
    hit = clearance(make, model, trim, year)
    if hit:
        how = hit[1].lower()
        return hit[0], ("Car and Driver" if "car and driver" in how else "maker's spec (outside US)" if "outside us" in how
                        else "dealer spec data" if how.startswith("same model") else "maker's spec")
    try:
        pv = float(page_value) if page_value not in (None, "") else None
    except ValueError:
        pv = None
    if pv:
        return pv, "dealer spec data"
    ap = approx_clearance(model, trim)
    return (ap, "approximate") if ap else (None, "")


def ev_range(make: str, model: str, trim: str, year, fuel: str) -> tuple[float, str] | None:
    """(miles, source) of electric driving for plug-in hybrids (all-electric range) and EVs (total range)."""
    if fuel not in ("phev", "ev"):
        return None
    e = _find("ev_range", make, model, trim, year, fuel)
    return (float(e["miles"]), e.get("source", "")) if e else None
