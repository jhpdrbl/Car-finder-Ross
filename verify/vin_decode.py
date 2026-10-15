"""NHTSA vPIC VIN decode (batch), cached forever per VIN in data/cache/vpic.json."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from scrapers.base import FetchError, fetcher

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "vpic.json"
URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesBatch/"
KEEP = ("ModelYear", "Make", "Model", "Trim", "Series", "DriveType", "BodyClass", "ElectrificationLevel",
        "FuelTypePrimary", "FuelTypeSecondary", "Seats", "SeatRows", "ErrorCode", "ErrorText")


_lock = threading.Lock()      # dealer threads decode in parallel; one shared cache
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
        except ValueError:          # a damaged cache file just means re-decoding
            _cache = {}
    return _cache


def _save(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=0), encoding="utf-8")
    os.replace(tmp, CACHE)          # atomic: readers never see a half-written file


def decode_many(vins: list[str]) -> dict[str, dict]:
    with _lock:
        return _decode_many(vins)


def _decode_many(vins: list[str]) -> dict[str, dict]:
    cache = _load()
    todo = [v for v in dict.fromkeys(vins) if v not in cache]
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        try:
            res = fetcher().post_json(URL, {"format": "json", "data": ";".join(chunk)})
        except FetchError as e:
            print(f"  VIN decode failed for {len(chunk)} VINs: {e}")
            continue
        for r in res.get("Results", []):
            cache[r["VIN"].upper()] = {k: (r.get(k) or "") for k in KEEP}
    if todo:
        _save(cache)
    return {v: cache.get(v, {}) for v in vins}


def fuel_class(d: dict) -> str:
    """gas / hybrid / phev / ev from the decode. Mild hybrids (48V) count as gas."""
    e = (d.get("ElectrificationLevel") or "").lower()
    if "phev" in e or "plug-in" in e:
        return "phev"
    if "bev" in e or "battery electric" in e or (d.get("FuelTypePrimary", "").lower() == "electric" and not d.get("FuelTypeSecondary")):
        return "ev"
    if "strong hev" in e or ("hev" in e and "mild" not in e):
        return "hybrid"
    return "gas"


def drive_class(d: dict) -> str:
    s = (d.get("DriveType") or "").lower()
    if "awd" in s or "all-wheel" in s:
        return "AWD"
    if "4wd" in s or "4x4" in s or "4-wheel" in s:
        return "4WD"
    if "fwd" in s or "front" in s:
        return "FWD"
    if "rwd" in s or "rear" in s:
        return "RWD"
    if "4x2" in s or "2wd" in s:
        return "2WD"
    return ""
