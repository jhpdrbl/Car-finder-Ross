"""Automakers' own national certified pre-owned (CPO) inventory searches.

These are official brand sites (genesis.com, subaru.com), not aggregators: every
car they return carries the selling dealer and a link to that dealer's own
listing page, which is what results link to. They cover dealers whose websites
block automated access, so they are the primary source for these brands.
"""
from __future__ import annotations

import csv
from datetime import date
import json
import re
from pathlib import Path

from core.profiles import could_want
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

GENESIS_MODELS = {"gv60": "GV60", "gv70": "GV70", "electrified-gv70": "Electrified GV70", "gv80": "GV80", "gv80-coupe": "GV80 Coupe"}


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
            L.make, L.model = "Genesis", GENESIS_MODELS[model]
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
            if not could_want("Subaru", f'{v.get("modelName") or ""} {v.get("trimName") or ""}', v.get("year") or 0):
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
            L.ext_color = re.sub(r"<[^>]+>|&reg;", "", (v.get("exteriorColor") or {}).get("name", "")).strip()
            L.int_color = re.sub(r"<[^>]+>|&reg;", "", (v.get("interiorColor") or {}).get("name", "")).strip()
            L.drivetrain = "AWD"  # every Subaru SUV has Symmetrical AWD; confirmed again by VIN decode
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


# --------------------------------------------------------------------------
# Volvo: cpo.volvocars.us (Volvo's certified store, run for Volvo by Codeweavers)
# --------------------------------------------------------------------------
# The store's car search (services.codeweavers.net, robots.txt allows /api/) only answers inside the
# store's own session, so this opens the store page in a real browser (honest User-Agent, robots.txt
# checked) and asks the store's search for certified XC60/XC40 (and electric EX40, S60/S90 plug-in sedans) near home from inside that page.
# Without the browser add-on (e.g. on the iPad) this feed fails and Volvo dealer sites are read instead.

VOLVO_STORE = "https://cpo.volvocars.us/en-US/store/all/vehicles"
VOLVO_SEARCH = "https://services.codeweavers.net/api/vehicles/search-with-facets/groups"
_FETCH_JS = ("async ([u, h, b]) => { const r = await fetch(u, {method: 'POST', headers: h, body: b, credentials: 'omit'});"
             " return {status: r.status, text: await r.text()}; }")


def volvo() -> tuple[list[Listing], dict]:
    from urllib.parse import urlparse
    from . import playwright_fallback as pw
    if not pw.available():
        raise FetchError("needs the browser add-on (Playwright); reading Volvo dealer sites instead")
    f = fetcher()
    for u in (VOLVO_STORE, VOLVO_SEARCH):
        if not f.allowed(u):
            raise FetchError(f"robots.txt disallows {u}")
    dealers = _dealers("Volvo")
    home = CONFIG["home"]
    search_host = urlparse(VOLVO_SEARCH).netloc
    out, stats = [], {"seen": 0, "in_area": 0}
    from playwright.sync_api import sync_playwright
    with pw._lock, sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context(user_agent=pw.UA, locale="en-US").new_page()
            first: dict = {}
            page.on("request", lambda r: first.setdefault("req", r)
                    if "search-with-facets" in r.url and r.method == "POST" else None)
            f._throttle(urlparse(VOLVO_STORE).netloc)
            page.goto(VOLVO_STORE, wait_until="domcontentloaded", timeout=60000)
            for _ in range(60):
                if "req" in first:
                    break
                page.wait_for_timeout(500)
            if "req" not in first:
                raise FetchError("Volvo's store page didn't start its car search")
            req = first["req"]
            headers = {k: v for k, v in req.headers.items() if k.lower().startswith("x-cw-") or k.lower() == "content-type"}
            body = json.loads(req.post_data)
            body.update(SortBy="Distance", ResultsPerPage=50, Page=1)
            body["Filters"]["Vehicle"]["SelectedFacets"]["Models"] = ["XC60", "XC40", "EX40", "S60", "S90"]   # names as the store lists them (Oct 2026)
            body["Filters"]["Location"] = {"Latitude": home["lat"], "Longitude": home["lon"],
                                           "Distance": home["edge_radius_miles"]}
            while True:
                f._throttle(search_host)
                res = page.evaluate(_FETCH_JS, [VOLVO_SEARCH, headers, json.dumps(body)])
                if res["status"] != 200:
                    raise FetchError(f"Volvo store search answered HTTP {res['status']}")
                data = json.loads(res["text"])
                for grp in data.get("Groups") or []:
                    stats["seen"] += 1
                    L = _volvo_listing(grp, dealers)
                    if L:
                        stats["in_area"] += 1
                        out.append(L)
                if body["Page"] >= (data.get("TotalPages") or 0) or body["Page"] >= 20:
                    break
                body["Page"] += 1
        finally:
            browser.close()
    return out, stats


def _volvo_listing(grp: dict, dealers: list[dict]) -> Listing | None:
    v = (grp.get("HeadlineVehicle") or {}).get("Vehicle") or {}
    ph, sp, rt = v.get("Physical") or {}, v.get("Specification") or {}, v.get("Retailer") or {}
    year = integer(sp.get("ModelYear"))
    if not ph.get("IsFranchiseApproved") or ph.get("NoLongerAvailable") or (year or 0) < 2023:
        return None
    d = _match_dealer(dealers, rt.get("Name", ""), rt.get("Website", ""))
    if not d or not ph.get("Vin") or not ph.get("ExternalVehicleLink"):
        return None
    L = Listing(vin=ph["Vin"].upper(), source="Volvo certified store (cpo.volvocars.us)")
    L.listing_url = ph["ExternalVehicleLink"]        # a link on the dealer's own website
    L.year, L.make, L.model = year, "Volvo", sp.get("Model") or ""
    variant = (sp.get("Variant") or "").strip()
    L.trim = re.sub(rf"^{re.escape(L.model)}\s*", "", variant)       # e.g. "Plus, B5 AWD, Mild Hybrid, Bright"
    L.price = money(ph.get("OnTheRoadPrice") or sp.get("OnTheRoadPrice"))
    L.mileage = integer(ph.get("Mileage"))
    L.ext_color = ((ph.get("ExteriorColour") or {}).get("Description") or "").strip()
    L.int_color = ((ph.get("InteriorColour") or {}).get("Description") or "").strip()
    L.drivetrain = classify_drivetrain(sp.get("Drive") or variant)
    L.condition = "used"
    L.cert_text = "certified by volvo (cpo.volvocars.us CPO inventory)"   # brand feed = strong evidence
    L.cpo_program = "Volvo Certified by Volvo"
    L.features = [x for x in (ph.get("EquipmentOptions") or []) if isinstance(x, str)]
    L.dealer, L.dealer_brand, L.dealer_url = d["dealer_name"], "Volvo", d["homepage"]
    return L


# --------------------------------------------------------------------------
# Lexus: lexus.com L/Certified search (/rest/lexus/inventorySearch/cpo; robots.txt allows /rest/)
# --------------------------------------------------------------------------
# It gives no link to the car's page on the dealer's site, only the dealer's certified inventory, so
# this feed SUPPLEMENTS the dealer sites (see SUPPLEMENT_FEEDS): dealer sites that load keep their real
# listing links (dedupe prefers them); cars at dealers whose sites refuse us still show up, linked to
# the dealer's own certified inventory searched for the VIN (and labelled that way).

LEXUS_SEARCH = ("https://www.lexus.com/rest/lexus/inventorySearch/cpo?zip={zip}&limit=50&offset={offset}"
                "&experience=offers&sortOrder=lotPrice:asc&radius={radius}&minPrice=0&maxPrice=100000")


def lexus() -> tuple[list[Listing], dict]:
    dealers = _dealers("Lexus")
    home = CONFIG["home"]
    out, stats, offset = [], {"seen": 0, "in_area": 0}, 0
    while True:
        data = fetcher().get_json(LEXUS_SEARCH.format(zip=home["zip"], offset=offset, radius=home["edge_radius_miles"]))
        docs = data.get("docs") or []
        for doc in docs:
            stats["seen"] += 1
            L = _lexus_listing(doc, dealers)
            if L:
                stats["in_area"] += 1
                out.append(L)
        offset += len(docs)
        if not docs or offset >= (data.get("numFound") or 0) or offset >= 2000:
            break
    return out, stats


def _lexus_listing(doc: dict, dealers: list[dict]) -> Listing | None:
    ov, di = doc.get("overview") or {}, doc.get("dealerInfo") or {}
    series, year = (ov.get("series") or "").upper(), integer(ov.get("year"))
    if not could_want("Lexus", series, year or 0) or not ov.get("vin"):
        return None
    d = _match_dealer(dealers, di.get("name", ""), di.get("webUrl", ""))
    inv = (di.get("dealerPreOwnedInventoryUrl") or di.get("webUrl") or "").rstrip("?&")
    if not d or not inv:
        return None
    vin = ov["vin"].upper()
    L = Listing(vin=vin, source="lexus.com L/Certified search")
    L.listing_url = f"{inv}{'&' if '?' in inv else '?'}search={vin}"
    L.link_note = "link opens the dealer's certified inventory searched for this VIN"
    L.year, L.make, L.model = year, "Lexus", series
    L.trim = re.sub(rf"^{series}\s*", "", (ov.get("modelname") or "").strip(), flags=re.I)   # e.g. "350h PREMIUM AWD"
    L.price = money(ov.get("lotPrice"))
    L.mileage = integer(ov.get("miles"))
    col = doc.get("color") or {}
    L.ext_color = (col.get("exteriorcolorname") or "").title()
    L.int_color = (col.get("interiorcolorname") or "").title()
    L.drivetrain = classify_drivetrain((doc.get("spec") or {}).get("drivetrain") or ov.get("modelname") or "")
    perf = doc.get("performance") or {}
    city, hwy = money(perf.get("mpgCity")), money(perf.get("mpgHwy"))
    if city and hwy and city < 80 and hwy < 80:          # plug-ins report MPGe-like numbers; leave those to EPA
        L.mpg_city, L.mpg_hwy = city, hwy
    L.stock = ov.get("stockId") or ""
    L.condition = "used"
    L.cert_text = "lexus l/certified (lexus.com CPO inventory)"
    L.cpo_program = "L/Certified"
    acc = (doc.get("inventoryData") or {}).get("accessory") or []
    L.features = [a.get("description", "") for a in acc if isinstance(a, dict) and a.get("description")]
    L.dealer, L.dealer_brand, L.dealer_url = d["dealer_name"], "Lexus", d["homepage"]
    return L


# --------------------------------------------------------------------------
# Volkswagen: vw.com certified inventory (VW's own inventory service, *.gsl.feature-app.io)
# --------------------------------------------------------------------------
# The search is a plain GET that vw.com's page makes with a public key and a signed "endpoint" from
# vw.com's own page settings (en.global-config.json). Those can change, so they're read fresh each run.
# Each car carries the dealer's own listing URL (onlineSalesUrl). Works without a browser (iPad too).

VW_CONFIG = "https://www.vw.com/en.global-config.json"


def _vw_settings() -> dict:
    t = fetcher().get(VW_CONFIG).text
    host = re.search(r"https://v[\w-]+\.gsl\.feature-app\.io", t)
    ep = re.search(r'\{"endpoint":\{[^{}]*"type":"publish"[^{}]*\},"signature":"[^"]+"\}', t)
    key = re.search(r'"trackingId":"GSL-[^"]*"[^{}]*?"featureAppApiKey":"(\w+)"', t) or re.search(r'"featureAppApiKey":"(\w+)"', t)
    ver = re.search(r'"serviceConfigsVersion":"(\w+)"', t)
    if not (host and ep and key):
        raise FetchError("vw.com page settings changed (couldn't find the inventory service settings)")
    return {"host": host.group(0), "endpoint": ep.group(0), "key": key.group(1), "version": ver.group(1) if ver else ""}


def vw() -> tuple[list[Listing], dict]:
    from urllib.parse import urlencode
    cfg = _vw_settings()
    dealers = _dealers("Volkswagen")
    home = CONFIG["home"]
    out, stats, page = [], {"seen": 0, "in_area": 0}, 1
    while True:
        q = {"t_cartype": "U", "t_manuf": "BQ", "t_geo": f'{home["lat"]},{home["lon"]},{home["edge_radius_miles"]}',
             "sort": "DISTANCE", "sortdirection": "ASC", "pageitems": 48, "page": page, "country": "US",
             "endpoint": cfg["endpoint"], "language": "en", "market": "passenger", "oneapiKey": cfg["key"],
             "dataVersion": cfg["version"]}
        data = fetcher().get_json(f'{cfg["host"]}/bff/car/search?{urlencode(q)}', headers={"Referer": "https://www.vw.com/"})
        for car in data.get("cars") or []:
            stats["seen"] += 1
            L = _vw_listing(car, dealers)
            if L:
                stats["in_area"] += 1
                out.append(L)
        meta = data.get("meta") or {}
        if page >= (meta.get("pageMax") or 0) or page >= 40 or not data.get("cars"):
            break
        page += 1
    return out, stats


def _val(d, *keys):
    for k in keys:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _vw_listing(car: dict, dealers: list[dict]) -> Listing | None:
    model = (car.get("modelKtText") or car.get("basemodelKtText") or "").strip()
    year = integer(_val(car, "modelyear", "value"))
    url = _val(car, "buildMyDealLinks", "onlineSalesUrl") or ""
    if _val(car, "cartype", "code") != "U" or "certified" not in (car.get("carTypeLabel") or "").lower():
        return None
    if not could_want("Volkswagen", model, year or 0) or not car.get("vin") or not url:
        return None
    if "tiguan" in model.lower() and (year or 0) < 2025:
        return None
    d = _match_dealer(dealers, _val(car, "dealer", "name", "value") or "", url)
    if not d:
        return None
    L = Listing(vin=car["vin"].upper(), source="vw.com certified inventory")
    L.listing_url = url                                   # the dealer's own listing page
    L.year, L.make, L.model = year, "Volkswagen", model
    L.trim = " ".join(x for x in (car.get("trimName") or "", _val(car, "subtitle", "value") or "") if x).strip()
    L.price = money(_val(car, "parsedPrice", "value"))
    L.mileage = integer(_val(car, "mileage", "raw_value"))
    L.ext_color = _val(car, "color", "out", "value") or ""
    inside = _val(car, "color", "in")
    L.int_color = (inside.get("value") if isinstance(inside, dict) else "") or ""
    L.drivetrain = classify_drivetrain(_val(car, "drive", "value") or L.trim)
    L.condition = "used"
    L.cert_text = "volkswagen certified pre-owned (vw.com CPO inventory)"
    L.cpo_program = "Volkswagen Certified Pre-Owned"
    L.dealer, L.dealer_brand, L.dealer_url = d["dealer_name"], "Volkswagen", d["homepage"]
    return L


# --------------------------------------------------------------------------
# Kia: kia.com certified pre-owned search (POST /us/services/en/cpo/inventory/exactmatch; kia.com's robots.txt
# only disallows /*dealer-master*, */search/ and other countries). 10 cars per page; its radius is unreliable,
# so it asks for 100 miles and keeps cars at the dealers in dealers.csv (60 miles). Each car links to the
# dealer's own page (vdpUrl). Not every Kia dealer is in it, so Kia dealer sites are still read too.
# --------------------------------------------------------------------------

KIA_SEARCH = "https://www.kia.com/us/services/en/cpo/inventory/exactmatch"


def kia() -> tuple[list[Listing], dict]:
    from core.profiles import all_profiles
    from .generic_jsonld import FAKE_WORD, SUNROOF, seat_material
    dealers = _dealers("Kia")
    # Kia's search names hybrids as their own model ("Sportage Hybrid"): config `feed_models:` per buyer
    models = list(dict.fromkeys(m for p in all_profiles() for m in ((p.models().get("Kia") or {}).get("feed_models") or [])))
    out, stats = [], {"seen": 0, "in_area": 0}
    for model in models:
        start = 0
        while True:
            body = {"radius": 100, "zipCode": CONFIG["home"]["zip"], "model": model, "transmissions": [], "trims": [],
                    "milesFilter": {}, "priceFilter": {}, "year": "", "dealers": [], "sortBy": "", "start": start, "end": start + 10}
            data = fetcher().post_json(KIA_SEARCH, json.dumps(body), headers={"content-type": "application/json"})
            rows = data.get("dealerVehicles") or []
            for x in rows:
                stats["seen"] += 1
                v, dl = x.get("vehicle") or {}, x.get("dealer") or {}
                year = integer(v.get("year"))
                if not v.get("vin") or not could_want("Kia", f'{v.get("model") or ""} {v.get("trim") or ""}', year or 0):
                    continue
                d = _match_dealer(dealers, dl.get("name", ""), dl.get("url", ""))
                if not d:
                    continue
                stats["in_area"] += 1
                L = Listing(vin=v["vin"].upper(), source="kia.com CPO search")
                L.listing_url = v.get("vdpUrl") or ""
                if not L.listing_url:       # no link to the car's page: the dealer's certified inventory, searched by VIN
                    inv = (d.get("inventory_url") or d["homepage"]).rstrip("?&")
                    L.listing_url = f"{inv}{'&' if '?' in inv else '?'}search={v['vin'].upper()}"
                    L.link_note = "link opens the dealer's certified inventory searched for this VIN"
                L.year, L.make, L.model = year, "Kia", v.get("model") or model
                L.trim = (v.get("trim") or v.get("cdmTrim") or "").strip()
                L.price = money(v.get("internetPrice"))
                L.mileage = integer(v.get("mileage"))
                L.ext_color, L.int_color = (v.get("exteriorColor") or "").strip(), (v.get("interiorColor") or "").strip()
                L.drivetrain = classify_drivetrain(v.get("drivetrain") or "")
                L.mpg_city, L.mpg_hwy = money(v.get("cityEpa")), money(v.get("highwayEpa"))
                L.stock = v.get("stockNumber") or ""
                L.condition = "used"
                L.cert_text = "kia certified pre-owned (kia.com CPO inventory)"
                L.cpo_program = "Kia Certified Pre-Owned"
                L.features = [str(e) for e in (v.get("equipment") or []) if e]
                hay = " ".join(L.features) + " " + (v.get("dealerComments") or "")
                if SUNROOF.search(hay):
                    L.sunroof, L.sunroof_note = True, SUNROOF.search(hay).group(1)
                L.seats = seat_material(hay, L.int_color)
                L.leather = False if L.seats == "synthetic" or FAKE_WORD.search(hay) else (True if L.seats == "leather" else None)
                L.dealer, L.dealer_brand, L.dealer_url = d["dealer_name"], "Kia", d["homepage"]
                out.append(L)
            start += 10
            if not rows or start >= (data.get("totalMatches") or 0) or start >= 1000:
                break
    return out, stats


# --------------------------------------------------------------------------
# Mazda: mazdausa.com certified search (GET /api/inv/search, cond=c; robots.txt's * group only blocks /EPiServer/CMS/,
# /Util/, /component-library/). Needs Mazda's dealer ids (from its dealer locator) and a carline code per model
# (CX5, C50 = CX-50, 50H = CX-50 Hybrid, C70 = CX-70, C7P = CX-70 PHEV; config `feed_models:`). Trims come as codes
# ("PP" = Premium Plus). The link to the car's page on the dealer's own site comes from /api/inv/detail, asked only
# for cars some buyer could want (year, miles, price), since each one is another request.
# --------------------------------------------------------------------------

MAZDA = "https://www.mazdausa.com"
MAZDA_ZIPS = ("90039", "92701", "91761", "93030", "91355")     # LA, Santa Ana, Ontario, Oxnard, Valencia: Mazda's radius is by driving
MAZDA_TRIMS = {"PP": "Premium Plus", "PR": "Premium", "PF": "Preferred", "SE": "Select", "CE": "Carbon Edition",
               "MR": "Meridian", "SG": "Signature", "TS": "Turbo Signature", "SPR": "S Premium", "SPP": "S Premium Plus",
               "BS": "Base", "PS": "Preferred", "CT": "Carbon Turbo", "TP": "Turbo Premium", "TPP": "Turbo Premium Plus",
               "PPT": "Turbo Premium Plus", "PRT": "Turbo Premium", "SGT": "Turbo Signature", "CET": "Carbon Turbo"}


def mazda() -> tuple[list[Listing], dict]:
    from core.profiles import MAX_PRICE, all_profiles, min_year
    from .generic_jsonld import FAKE_WORD, SUNROOF, seat_material
    dealers = _dealers("Mazda")
    ids: dict[str, dict] = {}
    for z in MAZDA_ZIPS:
        loc = fetcher().get_json(f"{MAZDA}/handlers/dealer.ajax?zip={z}&radius=60")
        for r in (loc.get("body") or {}).get("results") or []:
            d = _match_dealer(dealers, r.get("name", ""), r.get("webUrl", ""))
            if d:
                ids[str(r["id"])] = d
    if not ids:
        raise FetchError("no Mazda dealers matched the locator")
    codes = list(dict.fromkeys(c for p in all_profiles() for c in ((p.models().get("Mazda") or {}).get("feed_models") or [])))
    years = ",".join(str(y) for y in range(min_year("Mazda"), date.today().year + 2))
    out, stats = [], {"seen": 0, "in_area": 0}
    for vc in codes:
        page = 1
        while True:
            data = fetcher().get_json(f"{MAZDA}/api/inv/search?cond=c&dlrId={','.join(ids)}&zip={CONFIG['home']['zip']}"
                                      f"&yr={years}&vc={vc}&p={page}&ps=20&s=d")
            if (data.get("header") or {}).get("status") == "error":
                raise FetchError(f"Mazda search error for {vc}")
            body = data.get("body") or {}
            rows = body.get("results") or []
            for v in rows:
                stats["seen"] += 1
                d = ids.get(str(v.get("dealerId")))
                year, miles, price = integer(v.get("year")), integer(v.get("mileage")), money(v.get("cpoPrice"))
                if not d or not v.get("vin") or (miles or 0) >= 40000 or (price and price > MAX_PRICE + 1500):
                    continue
                words = " ".join(MAZDA_TRIMS.get(t, t) for t in (v.get("carlineName") or "").split())
                if not could_want("Mazda", words, year or 0):
                    continue
                stats["in_area"] += 1
                L = Listing(vin=v["vin"].upper(), source="mazdausa.com CPO search")
                m = re.match(r"(CX-\d+)", v.get("carlineName") or "")
                L.year, L.make = year, "Mazda"
                L.model = (m.group(1) if m else "") + (" Hybrid" if "HYBRID" in (v.get("carlineName") or "") else "") \
                    + (" PHEV" if "PHEV" in (v.get("carlineName") or "") else "")
                L.trim = MAZDA_TRIMS.get(v.get("trimName") or "", v.get("trimName") or "")
                L.title = words.title()
                L.price, L.mileage = price, miles
                L.ext_color = ((v.get("extColor") or {}).get("description") or "").title()
                L.int_color = ((v.get("intColor") or {}).get("description") or "").title()
                it = (v.get("intType") or "").lower()
                L.seats = "leather" if "leather" in it and "leatherette" not in it else ("synthetic" if "leatherette" in it else
                          ("cloth" if "cloth" in it else ""))
                L.leather = True if L.seats == "leather" else (False if L.seats == "synthetic" else None)
                L.drivetrain = "AWD" if "AWD" in (v.get("carlineName") or "") or "HYBRID" in (v.get("carlineName") or "") or "CX-70" in (v.get("carlineName") or "") else ""
                L.condition = "used"
                L.cert_text = "mazda certified pre-owned (mazdausa.com CPO inventory)"
                L.cpo_program = "Mazda Certified Pre-Owned"
                L.dealer, L.dealer_brand, L.dealer_url = d["dealer_name"], "Mazda", d["homepage"]
                try:      # the car's page on the dealer's own site, plus its feature list
                    det = (fetcher().get_json(f"{MAZDA}/api/inv/detail?vin={L.vin}").get("body") or {}).get("vehicle") or {}
                except (FetchError, AttributeError):
                    det = {}
                L.listing_url = det.get("dealerSiteUrl") or ""
                feats = [x for k in ("standardFeatures", "hiddenStandardFeatureList", "engineFeaturesList") for x in (det.get(k) or [])]
                L.features = [t for x in feats if (t := re.sub(r"<[^>]+>", "", str(x)).strip())][:150]
                hay = " ".join(L.features)
                if SUNROOF.search(hay):
                    L.sunroof, L.sunroof_note = True, SUNROOF.search(hay).group(1)
                if not L.seats:
                    L.seats = seat_material(hay, L.int_color)
                if not L.listing_url:
                    inv = (d.get("inventory_url") or d["homepage"]).rstrip("?&")
                    L.listing_url = f"{inv}{'&' if '?' in inv else '?'}search={L.vin}"
                    L.link_note = "link opens the dealer's certified inventory searched for this VIN"
                out.append(L)
            page += 1
            if not rows or (page - 1) * 20 >= (body.get("total") or 0) or page > 30:
                break
    return out, stats


FEEDS = {"Genesis": genesis, "Subaru": subaru, "Volvo": volvo, "Lexus": lexus, "Volkswagen": vw, "Kia": kia, "Mazda": mazda}
# Feeds that don't cover every dealer of the brand, or have no link to the car's own page on the dealer's site:
# their brand's dealer sites are still read (dedupe keeps the best record of each car).
SUPPLEMENT_FEEDS = {"Lexus", "Kia"}       # Mazda's covers every Mazda dealer on our list (its dealer locator), so their sites are skipped
