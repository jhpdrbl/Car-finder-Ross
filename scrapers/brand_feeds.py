"""Automakers' own national certified pre-owned (CPO) inventory searches.

These are official brand sites (genesis.com, subaru.com), not aggregators: every
car they return carries the selling dealer and a link to that dealer's own
listing page, which is what results link to. They cover dealers whose websites
block automated access, so they are the primary source for these brands.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .base import CONFIG, FetchError, fetcher
from .generic_jsonld import classify_drivetrain
from .listing import Listing, integer, money

ROOT = Path(__file__).resolve().parent.parent


def _dealers(brand: str) -> list[dict]:
    with (ROOT / "data" / "dealers.csv").open(encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r["brand"] == brand]


def _match_dealer(dealers: list[dict], name: str, url: str) -> dict | None:
    host = re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0].lower()
    for d in dealers:
        if host and host in d["homepage"].lower():
            return d
    n = re.sub(r"[^a-z]", "", (name or "").lower())
    for d in dealers:
        if n and n == re.sub(r"[^a-z]", "", d["dealer_name"].lower()):
            return d
    return None


# --------------------------------------------------------------------------
# Genesis: genesis.com/us/en/certified/inventory
# --------------------------------------------------------------------------

GENESIS_MODELS = ["gv70", "electrified-gv70"]


def genesis() -> tuple[list[Listing], dict]:
    dealers = _dealers("Genesis")
    codes = {}
    raw = ROOT / "data" / "locator_raw" / "genesis.json"
    if raw.exists():
        for d in json.loads(raw.read_text(encoding="utf-8"))["result"]["dealers"]:
            codes[d["dealerCd"]] = d
    out, stats = [], {"seen": 0, "in_area": 0}
    for model in GENESIS_MODELS:
        url = f"https://www.genesis.com/us/en/cpo/services/certifiedinventory.js?model={model}&type=inventory"
        data = fetcher().get_json(url)
        for row in (data.get("data") or {}).get("Vehicles", []):
            v = row["Veh"]
            stats["seen"] += 1
            d = None
            if v.get("DealerCd") in codes:
                c = codes[v["DealerCd"]]
                d = _match_dealer(dealers, c["dealerNm"], c.get("dealerUrl", ""))
            d = d or _match_dealer(dealers, v.get("DlrName", ""), v.get("DealerVINUrl", ""))
            if not d:
                continue  # not one of our dealers (outside 60 mi)
            stats["in_area"] += 1
            L = Listing(vin=v["VIN"].upper(), source="genesis.com CPO search")
            L.listing_url = (v.get("DealerVINUrl") or "").replace("http://", "https://")
            L.year = integer(v.get("ModelYear"))
            L.make, L.model = "Genesis", ("Electrified GV70" if "electrified" in model else "GV70")
            L.trim = (v.get("TrimDesc") or "").strip()
            L.title = (v.get("ModelTitle") or "").strip().title()
            L.price = money(v.get("SortablePrice") or v.get("FormattedPrice"))
            L.mileage = integer(v.get("SortableMileage") or v.get("Mileage"))
            L.ext_color = v.get("ExtColorDesc") or v.get("ExtColor") or ""
            L.int_color = v.get("IntColor") or v.get("IntColorCd") or ""
            L.drivetrain = classify_drivetrain(v.get("Drivetrain") or v.get("DrivetrainDesc") or L.title)
            L.stock = v.get("StockNumber") or ""
            L.packages = v.get("Package") or ""
            L.condition = "used"
            L.cert_text = "genesis certified pre-owned (genesis.com CPO inventory)"
            L.cpo_program = "Genesis Certified Pre-Owned"
            L.fuel_type = "ev" if "electrified" in model else ""
            L.dealer, L.dealer_brand, L.dealer_url = d["dealer_name"], "Genesis", d["homepage"]
            out.append(L)
    return out, stats


# --------------------------------------------------------------------------
# Subaru: subaru.com/vehicle-info/certified-pre-owned/certified-pre-owned.html
# --------------------------------------------------------------------------

def subaru() -> tuple[list[Listing], dict]:
    dealers = _dealers("Subaru")
    raw = json.loads((ROOT / "data" / "locator_raw" / "subaru.json").read_text(encoding="utf-8"))
    edge = CONFIG["home"]["edge_radius_miles"]
    by_code = {r["dealer"]["id"]: r["dealer"] for r in raw}
    codes = [r["dealer"]["id"] for r in raw if _match_dealer(dealers, r["dealer"]["name"], r["dealer"].get("siteUrl", ""))]
    out, stats, page = [], {"seen": 0, "in_area": 0}, 0
    while True:
        url = ("https://www.subaru.com/services/graphql/cpoinventory?page=%d&dealerCode=%s&sortBy=asc&itemsPerPage=100"
               % (page, ",".join(codes)))
        data = fetcher().get_json(url)
        w = data["pagedListWrapper"]
        for v in w["items"]:
            stats["seen"] += 1
            if v.get("modelName") not in ("Forester", "Outback") or (v.get("year") or 0) < 2023:
                continue
            dd = by_code.get(v.get("dealerCode"), {})
            d = _match_dealer(dealers, v.get("dealership") or dd.get("name", ""), v.get("detailsUrl") or dd.get("siteUrl", ""))
            if not d:
                continue
            stats["in_area"] += 1
            L = Listing(vin=v["vinNumber"].upper(), source="subaru.com CPO search")
            L.listing_url = v.get("detailsUrl") or ""
            L.year = v.get("year")
            L.make, L.model = "Subaru", v["modelName"]
            L.trim = (v.get("trimName") or "").strip()
            pkg = (v.get("optionPackage") or {}).get("name") or ""
            L.packages = "" if pkg.lower().startswith("standard") else pkg
            L.price = money(v.get("internetPrice") or v.get("cpoPrice"))
            L.mileage = integer(v.get("mileage"))
            L.ext_color = (v.get("exteriorColor") or {}).get("name", "")
            L.int_color = (v.get("interiorColor") or {}).get("name", "")
            L.drivetrain = "AWD"  # every Forester/Outback has Symmetrical AWD; confirmed again by VIN decode
            L.mpg_city, L.mpg_hwy = money(v.get("cityMpg")), money(v.get("highwayMpg"))
            L.stock = v.get("stockNumber") or ""
            L.condition = "used"
            L.cert_text = "subaru certified pre-owned (subaru.com CPO inventory)"
            L.cpo_program = "Subaru Certified Pre-Owned"
            names = [f.get("name", "") for f in (v.get("keyFeatures") or [])]
            opts = v.get("options")
            if isinstance(opts, list):
                names += [o.get("name", "") if isinstance(o, dict) else str(o) for o in opts]
            L.features = [re.sub(r"<[^>]+>|&reg;", "", n) for n in names if n]
            L.dealer, L.dealer_brand, L.dealer_url = d["dealer_name"], "Subaru", d["homepage"]
            out.append(L)
        page += 1
        if page >= (w["pager"].get("totalPages") or 0) or page > 30:
            break
    return out, stats


FEEDS = {"Genesis": genesis, "Subaru": subaru}
