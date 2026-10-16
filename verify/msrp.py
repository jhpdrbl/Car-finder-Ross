"""Original new-car sticker price (MSRP) for a listing.

1. The dealer's page, when it states the original MSRP / window-sticker price (`Listing.msrp_new` from the parser).
2. Otherwise the trim's base MSRP when new (destination included, no options) from data/msrp.json, researched
   from the makers' own press and pricing pages. Shown as an estimate ("~"), because options add to it.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

TABLE = Path(__file__).resolve().parent.parent / "data" / "msrp.json"


@lru_cache(maxsize=1)
def _rows() -> list[dict]:
    try:
        rows = json.loads(TABLE.read_text(encoding="utf-8")).get("rows") or []
    except (OSError, ValueError):
        return []
    for r in rows:
        r["_re"] = re.compile(r.get("trim_regex") or ".*", re.I)
    return rows


def lookup(make: str, model: str, trim_text: str, year: int | None, fuel: str = "") -> tuple[float, str] | None:
    """(base MSRP, note) for the first matching row: same make, model name contains the row's model,
    year in range, fuel matches (or 'any'), and the trim regex matches model + trim + title + URL."""
    if not year:
        return None
    mk, md = (make or "").lower(), (model or "").lower().replace("-", " ")
    text = (trim_text or "").lower().replace("-", " ").replace("_", " ")
    for r in _rows():
        if r["make"].lower() not in mk:
            continue
        if r["model"].lower().replace("-", " ") not in md and r["model"].lower().replace("-", " ") not in text:
            continue
        if year < int(r.get("min_year") or 0) or year > int(r.get("max_year") or 9999):
            continue
        f = (r.get("fuel") or "any").lower()
        if f not in ("any", "") and fuel and f != fuel:
            continue
        if r["_re"].search(text):
            return float(r["msrp"]), r.get("note") or ""
    return None


def fill(L) -> None:
    """Set L.msrp_new / L.msrp_source when the page didn't say."""
    if L.msrp_new:
        L.msrp_source = L.msrp_source or "listing"
        return
    hit = lookup(L.make, L.model, f"{L.model} {L.trim} {L.title} {L.listing_url}", L.year, L.fuel_type)
    if hit:
        L.msrp_new, L.msrp_source = hit[0], "trim base"
