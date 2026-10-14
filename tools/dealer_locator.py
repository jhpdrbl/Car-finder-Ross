"""Build data/dealers.csv from each brand's official dealer locator.

Usage:  python -m tools.dealer_locator [--refresh-raw] [--detect]

Brands whose official locator answers from this machine (Subaru, Lexus, Toyota,
Genesis, Volkswagen) are pulled automatically; raw responses are kept in
data/locator_raw/. Brands whose locator blocks automated access (Audi, BMW,
Mercedes-Benz, Ford, Volvo) come from data/dealers_manual.csv, and are marked
`source=manual` so they can be confirmed against the locator by hand.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from scrapers.base import CONFIG, FetchError, fetcher

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "locator_raw"
DEALERS_CSV = ROOT / "data" / "dealers.csv"
MANUAL_CSV = ROOT / "data" / "dealers_manual.csv"

HOME = CONFIG["home"]
FIELDS = ["brand", "dealer_name", "city", "address", "zip", "lat", "lon", "distance_mi",
          "homepage", "platform", "inventory_url", "status", "source", "last_scraped", "notes"]


def miles(lat: float, lon: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(HOME["lat"]), math.radians(lat)
    dp, dl = p2 - p1, math.radians(lon - HOME["lon"])
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def norm_url(u: str | None) -> str:
    if not u:
        return ""
    u = u.strip()
    if not u.startswith("http"):
        u = "https://" + u
    p = urlparse(u)
    return f"https://{p.netloc.lower()}"


def _raw(name: str, fetch, refresh: bool):
    path = RAW / f"{name}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    data = fetch()
    RAW.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1))
    return data


# --- per-brand locators ------------------------------------------------------

def subaru(refresh):
    url = f"https://www.subaru.com/services/dealers/distances/by/zipcode?zipcode={HOME['zip']}&count=60&type=Active"
    for row in _raw("subaru", lambda: fetcher().get_json(url), refresh):
        d = row["dealer"]
        a = d["address"]
        yield dict(dealer_name=d["name"], city=a["city"], address=a["street"], zip=a["zipcode"],
                   lat=d["location"]["latitude"], lon=d["location"]["longitude"],
                   homepage=d.get("siteUrl"), notes="" if "Cpo" in d.get("types", []) else "locator: no CPO flag")


def lexus(refresh):
    url = "https://www.lexus.com/rest/lexus/dealers"
    for d in _raw("lexus", lambda: fetcher().get_json(url), refresh)["dealers"]:
        a = d["dealerAddress"]
        yield dict(dealer_name=d["dealerName"], city=a["city"], address=a["address1"], zip=a["zipCodeFive"],
                   lat=d["dealerLatitude"], lon=d["dealerLongitude"], homepage=d.get("dealerSiteUrl", ""),
                   platform=VENDOR_MAP.get((d.get("websiteVendor") or "").lower(), ""),
                   inventory_url=(d.get("dealerPreOwnedInventoryUrl") or "").split("#")[0])


def toyota(refresh):
    url = f"https://dealers.prod.webservices.toyota.com/v1/dealers?zipcode={HOME['zip']}"
    hdrs = {"Origin": "https://www.toyota.com", "Referer": "https://www.toyota.com/"}
    for d in _raw("toyota", lambda: fetcher().get_json(url, headers=hdrs), refresh)["dealers"]:
        yield dict(dealer_name=d["name"], city=d["city"], address=d["address1"], zip=d["zip"],
                   lat=d["latitude"], lon=d["longitude"], homepage=d.get("url"))


def genesis(refresh):
    url = f"https://www.genesis.com/bin/api/v2/dealers?zip={HOME['zip']}"
    for d in _raw("genesis", lambda: fetcher().get_json(url), refresh)["result"]["dealers"]:
        yield dict(dealer_name=d["dealerNm"].title(), city=d["city"].title(), address=d["address1"].title(),
                   zip=d["zipCd"], lat=float(d["latitude"]), lon=float(d["longitude"]), homepage=d.get("dealerUrl"))


def volkswagen(refresh):
    # vw.com's locator is a JS app; its full dealer list is captured once with
    # Playwright (see _vw_capture) and cached in data/locator_raw/volkswagen.json.
    for d in _raw("volkswagen", _vw_capture, refresh):
        if "TESTDRIVE" not in (d.get("features") or []):
            continue  # vw.com also lists certified collision centers; keep sales dealers only
        a = d["address"]
        lat, lon = d["coordinates"]
        yield dict(dealer_name=d["name"], city=a["city"].title(), address=a["street"], zip=a["postalCode"],
                   lat=lat, lon=lon, homepage=d.get("contact", {}).get("website"))


def _vw_capture():
    from playwright.sync_api import sync_playwright
    found = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(user_agent=CONFIG["scrape"]["user_agent"]).new_page()
        pg.on("response", lambda r: found.append(r) if "bff-search/dealers" in r.url else None)
        pg.goto("https://www.vw.com/en/dealer-search.html", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(10000)
        best = max((r.json()["dealers"] for r in found), key=len, default=[])
        b.close()
    if not best:
        raise FetchError("vw.com dealer search returned no dealer list")
    return best


VENDOR_MAP = {"dealer inspire": "dealer_inspire", "dealer.com": "dealer_com", "dealeron": "dealeron",
              "dealer eprocess": "dealer_eprocess", "team velocity": "team_velocity", "sincro": "sincro_cdk",
              "cdk": "sincro_cdk", "fox dealer": "fox_dealer", "dealer venom": "dealer_venom"}

LOCATORS = {"Subaru": subaru, "Lexus": lexus, "Toyota": toyota, "Genesis": genesis, "Volkswagen": volkswagen}


# --- geocoding for manual rows ------------------------------------------------

GEOCACHE = RAW / "geocode_cache.json"


def geocode(address: str, city: str, zip_: str) -> tuple[float, float] | None:
    """Street address via the US Census geocoder; city-level fallback via OpenStreetMap Nominatim."""
    cache = json.loads(GEOCACHE.read_text()) if GEOCACHE.exists() else {}
    key = f"{address}|{city}|{zip_}"
    if key in cache:
        return tuple(cache[key]) if cache[key] else None
    f = fetcher()
    result = None
    if address:
        q = f"{address}, {city}, CA {zip_}".replace(" ", "+")
        try:
            j = f.get_json("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
                           f"?address={q}&benchmark=Public_AR_Current&format=json")
            m = j["result"]["addressMatches"]
            if m:
                result = (m[0]["coordinates"]["y"], m[0]["coordinates"]["x"])
        except (FetchError, KeyError):
            pass
    if result is None and city:
        # City-center fallback from a static table (Nominatim's robots.txt disallows /search).
        with (ROOT / "data" / "city_centroids.csv").open() as fh:
            for row in csv.DictReader(fh):
                if row["city"].lower() == city.lower():
                    result = (float(row["lat"]), float(row["lon"]))
                    break
    cache[key] = result
    GEOCACHE.write_text(json.dumps(cache, indent=1))
    return result


# --- platform detection ------------------------------------------------------

PLATFORM_SIGNS = [
    ("dealer_inspire", [r"dealerinspire", r"/wp-content/themes/DealerInspire", r"di-vrp"]),
    ("dealer_com", [r"dealer\.com", r"ddc-site", r"/static/js/ddc", r"DDC\.dataLayer", r"pictures\.dealer\.com"]),
    ("dealeron", [r"dealeron", r"/api/vhcliaa/"]),
    ("dealer_eprocess", [r"dealereprocess", r"dealer eprocess", r"/VehicleSearchResults"]),
    ("team_velocity", [r"teamvelocity", r"apolloplatform", r"tvmarketing"]),
    ("sincro_cdk", [r"cdkglobal", r"cobalt", r"sincro"]),
    ("fox_dealer", [r"foxdealer"]),
    ("dealer_venom", [r"dealervenom"]),
    ("dealerfire", [r"dealerfire"]),
    ("jazel", [r"jazel"]),
    ("audi_network", [r"vehicleId=", r"audiusa-dealer"]),
]


def detect_platform(homepage: str) -> tuple[str, str]:
    """Return (platform, note)."""
    if not homepage:
        return "", "no homepage"
    f = fetcher()
    try:
        llm = f.get(homepage + "/llms.txt")
        has_llm = llm.status_code == 200 and "llm/inventory" in llm.text
    except FetchError:
        has_llm = False
    try:
        r = f.get(homepage + "/")
    except FetchError as e:
        return ("dealer_inspire" if has_llm else "unknown"), f"homepage error: {e}"
    if r.status_code in (403, 429, 503):
        why = "cloudflare" if "cloudflare" in r.text.lower() else f"HTTP {r.status_code}"
        return ("dealer_inspire" if has_llm else "unknown"), f"homepage blocked ({why})" + ("; has /llm/inventory" if has_llm else "")
    html = r.text
    for name, pats in PLATFORM_SIGNS:
        if any(re.search(p, html, re.I) for p in pats):
            return name, "has /llm/inventory" if has_llm else ""
    return ("dealer_inspire" if has_llm else "unknown"), "has /llm/inventory" if has_llm else "platform not recognized"


# --- main ---------------------------------------------------------------------

def load_existing() -> dict[tuple[str, str], dict]:
    if not DEALERS_CSV.exists():
        return {}
    with DEALERS_CSV.open() as fh:
        return {(r["brand"], norm_url(r["homepage"]) or r["dealer_name"]): r for r in csv.DictReader(fh)}


def build(refresh_raw: bool, detect: bool) -> list[dict]:
    existing = load_existing()
    rows: list[dict] = []
    edge = HOME["edge_radius_miles"]
    for brand, fn in LOCATORS.items():
        try:
            items = list(fn(refresh_raw))
        except Exception as e:  # report and move on; one brand failing shouldn't stop the rest
            print(f"[{brand}] locator failed: {e}", file=sys.stderr)
            continue
        for it in items:
            dist = miles(float(it["lat"]), float(it["lon"]))
            if dist > edge:
                continue
            rows.append({**it, "brand": brand, "distance_mi": round(dist, 1), "homepage": norm_url(it.get("homepage")),
                         "status": "confirmed", "source": "brand locator"})
    if MANUAL_CSV.exists():
        with MANUAL_CSV.open() as fh:
            for it in csv.DictReader(fh):
                it = {k: (v or "").strip() for k, v in it.items()}
                if not (it.get("lat") and it.get("lon")):
                    ll = geocode(it.get("address", ""), it.get("city", ""), it.get("zip", ""))
                    if ll:
                        it["lat"], it["lon"] = round(ll[0], 5), round(ll[1], 5)
                        it["notes"] = "; ".join(filter(None, [it.get("notes"), "" if it.get("address") else "distance from city center"]))
                if it.get("lat") and it.get("lon"):
                    it["distance_mi"] = round(miles(float(it["lat"]), float(it["lon"])), 1)
                    if it["distance_mi"] > edge:
                        continue
                it["homepage"] = norm_url(it.get("homepage"))
                it.setdefault("status", "unverified")
                it["source"] = it.get("source") or "manual"
                rows.append(it)
    out = []
    for r in rows:
        key = (r["brand"], r["homepage"] or r["dealer_name"])
        prev = existing.get(key, {})
        row = {f: r.get(f, "") for f in FIELDS}
        for keep in ("platform", "inventory_url", "last_scraped", "notes"):
            if prev.get(keep) and not row.get(keep):
                row[keep] = prev[keep]
        if r.get("distance_mi", 0) and float(r["distance_mi"]) > HOME["radius_miles"]:
            row["notes"] = "; ".join(filter(None, [row["notes"], "edge (50-60 mi)"]))
        if detect and not prev.get("platform"):
            plat, note = detect_platform(row["homepage"])
            row["platform"] = plat
            row["notes"] = "; ".join(filter(None, [row["notes"], note]))
        out.append(row)
    out.sort(key=lambda r: (r["brand"], float(r["distance_mi"] or 999)))
    with DEALERS_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-raw", action="store_true", help="re-query the brand locators")
    ap.add_argument("--detect", action="store_true", help="fetch homepages to detect platform")
    a = ap.parse_args()
    rows = build(a.refresh_raw, a.detect)
    print(f"wrote {len(rows)} dealers to {DEALERS_CSV}")
