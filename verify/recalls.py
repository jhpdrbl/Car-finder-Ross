"""NHTSA recall campaigns by make/model/year, cached for 7 days.

These are model-level campaigns; whether a specific VIN's recall was completed
has to be checked by the buyer at https://www.nhtsa.gov/recalls (VIN lookup).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import quote

from scrapers.base import FetchError, fetcher

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "recalls.json"
TTL = 7 * 86400

# NHTSA's model names differ from marketing names for a few of ours
MODEL_ALIASES = {("AUDI", "Q5 E"): "Q5", ("MERCEDES-BENZ", "GLC-CLASS"): "GLC", ("MERCEDES-BENZ", "GLC 300"): "GLC"}


def _atomic_write(text: str) -> None:
    import os
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, CACHE)


def campaigns(make: str, model: str, year: int | None) -> list[str]:
    if not (make and model and year):
        return []
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    m = MODEL_ALIASES.get((make.upper(), model.upper()), model)
    key = f"{make.upper()}|{m.upper()}|{year}"
    hit = cache.get(key)
    if hit and time.time() - hit["t"] < TTL:
        return hit["ids"]
    url = (f"https://api.nhtsa.gov/recalls/recallsByVehicle?make={quote(make)}&model={quote(m)}&modelYear={year}")
    try:
        data = fetcher().get_json(url)
    except FetchError:
        return hit["ids"] if hit else []
    ids = [f'{r["NHTSACampaignNumber"]} ({(r.get("Component") or "").split(":")[0].title()})'
           for r in data.get("results", [])]
    cache[key] = {"t": time.time(), "ids": ids}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(json.dumps(cache, indent=0))
    return ids
