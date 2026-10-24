"""Platform-independent pieces: find listing pages via sitemaps, and parse any
vehicle detail page (VDP) using schema.org JSON-LD plus the page's own text.
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

try:   # lxml is faster; Python's built-in parser is the fallback where lxml can't be installed (e.g. an iPad)
    import lxml  # noqa: F401
    PARSER = "lxml"
except ImportError:
    PARSER = "html.parser"

from .base import FetchError, fetcher
from .listing import (VIN_ANY, VIN_RE, Listing, integer, money, url_condition,
                      url_matches_brand_models, url_vin, url_years)

from core.profiles import min_year   # earliest model year any buyer wants, per brand

# --------------------------------------------------------------------------
# Discovery: sitemaps
# --------------------------------------------------------------------------

SITEMAP_HINT = re.compile(r"(invent|vehicle|used|cpo|certif|vdp|detail|pre-?owned|cars?[-_.]|srp)", re.I)


def sitemap_urls(homepage: str) -> list[str]:
    f = fetcher()
    found = []
    try:
        r = f.get(homepage + "/robots.txt", check_robots=False)
        if r.status_code == 200:
            found = [urljoin(homepage + "/", u.strip()) for u in re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text)]
    except FetchError:
        pass
    return found or [homepage + "/sitemap.xml", homepage + "/sitemap_index.xml"]


def _locs(url: str, depth: int, seen: set) -> list[str]:
    if url in seen or len(seen) > 40:
        return []
    seen.add(url)
    try:
        r = fetcher().get(url)
    except FetchError:
        return []
    if r.status_code != 200:
        return []
    locs = [html.unescape(l.strip()) for l in re.findall(r"<loc>\s*(?:<!\[CDATA\[)?([^<\]]+?)(?:\]\]>)?\s*</loc>", r.text)]
    if "<sitemapindex" in r.text[:2000] and depth < 2:
        out = []
        for u in locs:
            # child sitemaps: only follow ones that look like inventory, unless there are few
            if len(locs) <= 6 or SITEMAP_HINT.search(u):
                out += _locs(u, depth + 1, seen)
        return out
    return locs


UUID_RE = re.compile(r"[0-9a-f]{32}", re.I)


def looks_like_vdp(url: str) -> bool:
    """A single-car page: has a VIN, or a year plus a platform vehicle id (Dealer.com uuid, ...)."""
    if url_vin(url):
        return True
    path = url.split("?")[0]
    return bool(url_years(url)) and bool(UUID_RE.search(path) or re.search(r"vehicleid=|/vdp/|/detail", url, re.I))


def discover_from_sitemaps(homepage: str, brand: str) -> tuple[list[str], str]:
    """Return (candidate VDP URLs for this brand's target models, note)."""
    seen: set = set()
    locs: list[str] = []
    for sm in sitemap_urls(homepage):
        locs += _locs(sm, 0, seen)
    if not locs:
        return [], "no sitemap"
    host = urlparse(homepage).netloc.replace("www.", "")
    out = []
    for u in dict.fromkeys(locs):
        if host not in u:
            continue
        if url_condition(u) == "new":
            continue
        if not url_matches_brand_models(u, brand) and not url_vin(u):
            continue
        yrs = url_years(u)
        if yrs and max(yrs) < min_year(brand):
            continue
        if not looks_like_vdp(u):
            continue
        out.append(u)
    return out, f"sitemap: {len(locs)} urls, {len(out)} candidates"


# --------------------------------------------------------------------------
# Parsing a VDP
# --------------------------------------------------------------------------

CUT_MARKERS = re.compile(r"(similar vehicles|you may also like|recently viewed|related vehicles|"
                         r"other vehicles you|more vehicles like|shoppers also viewed)", re.I)


def _jsonld_vehicles(soup: BeautifulSoup) -> list[dict]:
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except ValueError:
            try:  # some sites put trailing commas / control chars in their JSON-LD
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw.replace("\n", " ")))
            except ValueError:
                continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
                continue
            if not isinstance(d, dict):
                continue
            if "@graph" in d:
                stack.extend(d["@graph"] if isinstance(d["@graph"], list) else [d["@graph"]])
            t = d.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(x in ("Vehicle", "Car", "Product", "MotorizedBicycle", "IndividualProduct") for x in types) and (
                    d.get("vehicleIdentificationNumber") or d.get("vin") or d.get("sku") or d.get("productID")):
                out.append(d)
            for v in d.values():
                if isinstance(v, (dict, list)):
                    stack.append(v)
    return out


def _name(x) -> str:
    if isinstance(x, dict):
        return str(x.get("name") or x.get("@id") or "")
    if isinstance(x, list):
        return ", ".join(_name(i) for i in x)
    return str(x or "")


LABELS = {
    "ext_color": r"(?:exterior(?: colou?r)?|ext\.? colou?r|colou?r)",
    "int_color": r"(?:interior(?: colou?r)?|int\.? colou?r|upholstery)",
    "drivetrain": r"(?:drive ?train|drive ?type|drive ?line|drive)",
    "mileage": r"(?:mileage|miles|odometer)",
    "stock": r"(?:stock ?(?:#|no\.?|number)?)",
    "engine": r"(?:engine)",
    "fuel": r"(?:fuel(?: type)?)",
    "trim": r"(?:trim)",
    "location": r"(?:location|located at)",
}


NOT_A_COLOR = re.compile(r"camera|cargo|volume|sensor|assist|system|control|mirror|wiper|window|door|trunk|headrest|"
                         r"airbag|\btires?\b|wheels?\b|bumper|\bseats?\b|cup ?holder|outlet|usb|speaker|lamps?\b|dimensions?|"
                         r"length|width|height|capacity|\d+(\.\d+)? ?(in|cu|ft|mm)\b", re.I)


def _label_values(text: str) -> dict[str, str]:
    """Read 'Label: value' and 'Label' / 'value' on the next line (DealerOn, Dealer Inspire, ...)."""
    out: dict[str, str] = {}
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for i, line in enumerate(lines[:4000]):
        for key, lab in LABELS.items():
            if key in out:
                continue
            m = re.fullmatch(rf"{lab}\s*[:#]?\s*(.*)", line, re.I)
            if not m:
                continue
            val = m.group(1).strip(" :,;")
            if not val and i + 1 < len(lines):
                val = lines[i + 1].strip()
            if re.match(r"(and|&|or|features?|options?|packages?|specs?)\b", val, re.I):
                continue
            if key.endswith("_color") and NOT_A_COLOR.search(val):
                continue          # an "Exterior" / "Interior" features heading, e.g. "parking camera front"
            if val and len(val) <= 60 and not re.fullmatch(rf"{'|'.join(LABELS.values())}\s*:?", val, re.I):
                out[key] = val
    return out


DATA_ATTRS = {"odometer": "mileage", "mileage": "mileage", "extcolor": "ext_color", "exteriorcolor": "ext_color",
              "intcolor": "int_color", "interiorcolor": "int_color", "trim": "trim", "drivetrain": "drivetrain",
              "price": "price", "year": "year", "model": "model", "make": "make", "vin": "vin", "stocknum": "stock",
              "stock": "stock"}


BAD_TRIM = re.compile(r"backlight|lighting|\bwood\b|aluminum|carbon fiber|piano black|^\s*(?:n/?a|none|null|undefined)\s*$", re.I)


def _json_trim(html: str, vin: str) -> str:
    """The trim in the page's own data for this VIN, e.g. Dealer.com's {"vin":"WA1...","trim":"Premium Plus"}
    (the closest "trim" to the VIN; other cars' carousels on the same page are farther away)."""
    best, dist = "", 10 ** 9
    for m in re.finditer(rf'"vin"\s*:\s*"{vin}"', html, re.I):
        lo = max(0, m.start() - 1500)
        for t in re.finditer(r'"(?:trim|vehicleConfiguration)"\s*:\s*"([^"\[\]{}]{1,40})"', html[lo:m.end() + 1500], re.I):
            val, d = t.group(1).strip(), abs(lo + t.start() - m.start())
            if val and val.lower() != "trim" and d < dist:
                best, dist = val, d
    return best


def _data_attrs(html: str, vin: str) -> dict[str, str]:
    """Platform tagging attributes, e.g. DealerOn's data-odometer / data-extcolor on the VDP container."""
    out: dict[str, str] = {}
    i = html.lower().find(vin.lower()) if vin else -1
    window = html[max(0, i - 3000): i + 3000] if i >= 0 else html[:20000]
    for m in re.finditer(r'data-(?:dotagging-item-|vehicle-)?([a-z]+)="([^"]{1,80})"', window, re.I):
        k = DATA_ATTRS.get(m.group(1).lower())
        if k and m.group(2).strip() and k not in out:
            out[k] = m.group(2).strip()
    return out


SUNROOF = re.compile(r"(sun ?roof|moon ?roof|panoramic (?:glass )?roof|panorama roof|sky ?roof|removable roof panels?|"
                     r"removable hard ?top|panoramic sunroof|vista roof|power tilt/slide)", re.I)
NO_SUNROOF = re.compile(r"(no (?:sun|moon) ?roof|without (?:sun|moon) ?roof|sunroof delete)", re.I)
AUDIO = re.compile(r"(bang\s*&\s*olufsen|bang and olufsen|\bb&o\b|lexicon|harman[\s/-]*kardon|burmester|"
                   r"bowers\s*(?:&|and)\s*wilkins|mark levinson|\bsonos\b|\bbose\b|meridian (?:surround|premium|audio|sound)|"
                   r"\bjbl\b|\bakg\b|\bkrell\b|\brevel\b (?:premium|audio|sound)|els studio)", re.I)
_FAKE = (r"(?:leatherette|inteluxe|duoleather|duo leather|luxtec|mb-?tex|sensatec|startex|softex|synthetic leather|vegan leather|nuluxe|artificial leather|"
         r"leather-?like|simulated leather|faux leather|vernasca|leather-?appointed synthetic)")
_SEAT = r"(?:seat|seats|seating|upholster\w*)"
FAKE_LEATHER = re.compile(rf"({_FAKE}[^.;|\n]{{0,30}}{_SEAT}|{_SEAT}[^.;|\n]{{0,30}}{_FAKE})", re.I)
FAKE_WORD = re.compile(_FAKE, re.I)
LEATHER = re.compile(rf"((?:genuine |nappa |perforated |real )?leather[- ](?:trimmed |appointed )?{_SEAT}|"
                     rf"{_SEAT}[^.;|\n]{{0,20}}(?<!synthetic )leather(?!ette)|nappa leather)", re.I)
CLOTH = re.compile(rf"((?:cloth|fabric|tweed|woven|knit) (?:trimmed |covered )?{_SEAT}|{_SEAT}[^.;|\n]{{0,15}}(?:cloth|fabric)(?! headliner)|"
                   rf"(?:cloth|fabric) (?:interior|upholstery|seat trim))", re.I)
CLOTH_WORD = re.compile(r"\b(cloth|fabric|tweed)\b", re.I)


CLEARANCE = re.compile(r'ground[ -]?clearance\s*(?:\((max|min|in|inches)\))?\s*:?\s*'
                       r'(?:(\d{2,3})\s*mm\s*\(\s*([\d.]+)\s*(?:"|in\.?)?\s*\)|([\d.]+)\s*(?:in\b|inches|")?)', re.I)


def ground_clearance(text: str) -> float | None:
    """Ground clearance in inches from the page's spec list: Dealer.com 'Ground clearance (max): 208mm (8.2")',
    'Ground Clearance (in): 8.1', 'Ground Clearance 8.3 in'. With max and min (adjustable suspension), max wins."""
    vals: dict[str, float] = {}
    for m in CLEARANCE.finditer(text):
        kind = (m.group(1) or "").lower().replace("inches", "in")
        try:
            inch = float(m.group(3)) if m.group(3) else (float(m.group(2)) / 25.4 if m.group(2) else float(m.group(4)))
        except (TypeError, ValueError):
            continue
        if 4 <= inch <= 15:
            vals.setdefault(kind, round(inch, 1))
    return vals.get("max") or vals.get("") or vals.get("in") or vals.get("min")


def seat_material(hay: str, int_color: str) -> str:
    """leather / synthetic / cloth from the interior color name first (most specific), then the page text."""
    if FAKE_WORD.search(int_color):
        return "synthetic"
    if CLOTH_WORD.search(int_color):
        return "cloth"
    if "leather" in int_color.lower():
        return "leather"
    if FAKE_LEATHER.search(hay):
        return "synthetic"
    if LEATHER.search(hay):
        return "leather"
    if CLOTH.search(hay):
        return "cloth"
    return ""


ORIG_MSRP = re.compile(r"(?:original|orig\.|factory|window[- ]sticker|when new|new[- ]vehicle)\s+(?:sticker\s+)?(?:msrp|sticker price|price)"
                       r"\s*(?:when new)?\s*[:\-]?\s*\$\s?([\d,]{5,7})", re.I)
VENT = re.compile(r"(ventilated|cooled) (?:front )?seats?|seat ventilation|ventilated (?:driver|front)", re.I)
SPARE_YES = re.compile(r"(full[- ]size spare|compact spare|temporary spare|spare tire|space[- ]saver spare|spare wheel)", re.I)
SPARE_NO = re.compile(r"(tire (?:mobility|repair|inflat\w*) kit|inflator kit|tire sealant|run[- ]flat|no spare)", re.I)
THIRD_ROW = re.compile(r"((?:third|3rd)[- ]row (?:seat|seating|bench|split)|7[- ]passenger|seats? 7 |seating for 7|"
                       r"seating capacity:? ?7)", re.I)
CERT = re.compile(r"(audi certified(?: pre-?owned)?|audi approved(?: plus)?|genesis certified(?: pre-?owned)?|"
                  r"subaru certified(?: pre-?owned)?|bmw certified(?: pre-?owned)?|certified pre-?owned bmw|"
                  r"mercedes-benz certified(?: pre-?owned)?|mb certified|volkswagen certified(?: pre-?owned)?|vw certified|"
                  r"l/certified|lexus certified|volvo (?:cars )?certified(?: pre-?owned)?|certified by volvo|"
                  r"toyota certified(?: used vehicles?)?|tcuv|ford blue advantage(?: gold| blue)?|blue advantage (?:gold|blue)|"
                  r"certified pre-?owned)", re.I)
# "Galpin Certified", "Keyes Certified": a dealer's own program (case-sensitive, capitalized name)
DEALER_CERT = re.compile(r"\b([A-Z][a-zA-Z]{2,}) Certified\b")
NOT_DEALER = {"Audi", "Genesis", "Subaru", "BMW", "Benz", "Mercedes", "Volkswagen", "VW", "Lexus", "Volvo", "Toyota",
              "Ford", "Pre", "Our", "The", "All", "Shop", "View", "Browse", "Search", "Used", "New", "Why", "Factory",
              "Manufacturer", "Owned", "Are", "Is", "Be", "Being", "Of", "From", "And", "Get", "Fully", "Inspected",
              "Gold", "Silver", "Platinum", "Blue", "Elite", "Select", "Advantage", "Approved", "Vehicle", "Vehicles"}
WARRANTY = re.compile(r"(\d+[- ]year/?\s*(?:unlimited|[\d,]+)[- ]?(?:mile)?[^.]{0,80}warranty[^.]{0,60})", re.I)
DOC_FEE = re.compile(r"(?:doc(?:ument(?:ation)?)?\.? (?:fee|processing)[^$]{0,30})\$\s?([\d,]{2,6}(?:\.\d\d)?)", re.I)
OTHER_FEE = re.compile(r"(?:(?:electronic )?filing|smog|emissions?|e-?filing|dealer service|reconditioning|"
                       r"certification) (?:fee|charge)[^$]{0,30}\$\s?([\d,]{2,6}(?:\.\d\d)?)", re.I)
CARFAX_BADGE = re.compile(r"carfax[^\"'<>]{0,80}?(1[-_ ]?own(?:er)?(?:[-_ ]?great|[-_ ]?good)?|one[-_ ]?owner|"
                          r"accident[-_ ]?free|no[-_ ]?accidents?|clean|great[-_ ]?value|good[-_ ]?value|service[-_ ]?records?)", re.I)
NO_ACCIDENT = re.compile(r"(no accidents? (?:or damage )?reported|no accidents?\b|accident[- ]free|0 accidents)", re.I)
HAS_ACCIDENT = re.compile(r"((?<!no )accident(?:s)? reported|damage reported|(?<!no )(?<!0 )accident/damage)", re.I)


def classify_drivetrain(s: str) -> str:
    s = (s or "").lower()
    if re.search(r"(awd|all[- ]wheel|quattro|xdrive|4matic|symmetrical|intelligent awd|htrac)", s):
        return "AWD"
    if re.search(r"(4wd|4x4|four[- ]wheel|4-wheel)", s):
        return "4WD"
    if re.search(r"(fwd|front[- ]wheel)", s):
        return "FWD"
    if re.search(r"(rwd|rear[- ]wheel|sdrive)", s):
        return "RWD"
    if re.search(r"\b2wd\b|4x2|two[- ]wheel", s):
        return "2WD"
    return ""


def parse_vdp(html: str, url: str) -> Listing | None:
    """Parse one dealer VDP. Returns None when the page holds no vehicle."""
    soup = BeautifulSoup(html, PARSER)
    vehicles = _jsonld_vehicles(soup)
    for t in soup(["script", "style", "noscript", "svg", "header", "nav", "footer"]):
        t.decompose()
    for t in soup.select('[role="navigation"], [class*="navbar"], [class*="mega-menu"], [class*="megamenu"], '
                         '[class*="site-header"], [class*="site-footer"], [id*="footer"], [class*="breadcrumb"]'):
        t.decompose()
    full_text = soup.get_text("\n", strip=True)
    cut = CUT_MARKERS.search(full_text)
    text = full_text[:cut.start()] if cut and cut.start() > 500 else full_text
    flat = re.sub(r"\s+", " ", text)

    # VIN: JSON-LD first, then the URL, then the page text
    vin = ""
    v = {}
    for cand in vehicles:
        cv = str(cand.get("vehicleIdentificationNumber") or cand.get("vin") or "").upper()
        if VIN_RE.fullmatch(cv):
            vin, v = cv, cand
            break
    if not vin:
        vin = url_vin(url)
    if not vin:
        m = re.search(r"\bVIN\b[:#\s]*([A-HJ-NPR-Z0-9]{17})", flat)
        vin = m.group(1) if m else ""
    if not vin:
        return None
    if not v and vehicles:
        v = vehicles[0]

    L = Listing(vin=vin, listing_url=url)
    L.title = _name(v.get("name")) or (soup.title.get_text(strip=True) if soup.title else "")
    L.year = integer(v.get("vehicleModelDate") or v.get("modelDate") or v.get("productionDate"))
    if not L.year:
        m = re.search(r"\b(20[12]\d)\b", L.title)
        L.year = int(m.group(1)) if m else None
    L.make = _name(v.get("brand") or v.get("manufacturer"))
    L.model = _name(v.get("model"))
    L.trim = str(v.get("vehicleConfiguration") or "")
    L.body = str(v.get("bodyType") or "")
    L.stock = str(v.get("sku") or "")
    L.ext_color = _name(v.get("color"))
    L.int_color = _name(v.get("vehicleInteriorColor"))
    L.drivetrain = classify_drivetrain(_name(v.get("driveWheelConfiguration")))
    L.fuel_type = _name(v.get("fuelType"))
    odo = v.get("mileageFromOdometer")
    L.mileage = integer(odo.get("value") if isinstance(odo, dict) else odo)
    for fe in (v.get("fuelEfficiency") or []) if isinstance(v.get("fuelEfficiency"), list) else []:
        if isinstance(fe, dict):
            n = str(fe.get("name", "")).lower()
            if "city" in n:
                L.mpg_city = money(fe.get("value"))
            elif "highway" in n or "hwy" in n:
                L.mpg_hwy = money(fe.get("value"))
    offers = v.get("offers")
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict):
        L.price = money(offers.get("price") or (offers.get("priceSpecification") or {}).get("price")
                        if isinstance(offers.get("priceSpecification"), dict) else offers.get("price"))
    cond = str(v.get("itemCondition") or "").lower()
    L.condition = "used" if "used" in cond else ("new" if "new" in cond else url_condition(url))

    # Label: value fallbacks from the page text
    lv = _label_values(text)
    L.ext_color = L.ext_color or lv.get("ext_color", "")
    L.int_color = L.int_color or lv.get("int_color", "")
    L.drivetrain = L.drivetrain or classify_drivetrain(lv.get("drivetrain", ""))
    L.mileage = L.mileage if L.mileage is not None else integer(lv.get("mileage"))
    L.stock = L.stock or lv.get("stock", "")
    L.trim = L.trim or lv.get("trim", "")
    da = _data_attrs(html, vin)
    L.ext_color = L.ext_color or da.get("ext_color", "")
    L.int_color = L.int_color or da.get("int_color", "")
    for attr in ("ext_color", "int_color"):     # a section heading or a word cut from a longer name, not a color
        if re.fullmatch(r"\s*(mechanical|exterior|interior|safety|entertainment|features?|options?|accents?|trim|n/?a|null)\s*", getattr(L, attr) or "", re.I):
            setattr(L, attr, "")
    L.mileage = L.mileage if L.mileage is not None else integer(da.get("mileage"))
    if BAD_TRIM.search(L.trim):
        L.trim = ""                  # a features line read as the trim ("Trim: backlighting")
    L.trim = L.trim or da.get("trim", "") or _json_trim(html, vin)
    if BAD_TRIM.search(L.trim):      # the page's data attributes / JSON can say "null" too (dealer.com, Oct 2026)
        L.trim = ""
    L.drivetrain = L.drivetrain or classify_drivetrain(da.get("drivetrain", ""))
    if L.price is None and da.get("price") and (money(da["price"]) or 0) >= 3000:
        L.price = money(da["price"])
    if lv.get("location"):
        L.location_note = lv["location"]
    if not L.drivetrain:
        L.drivetrain = classify_drivetrain(L.title + " " + url)

    # Price: ignore junk (ratings, monthly payments) from structured data
    if L.price is not None and L.price < 3000:
        L.price = None
    # prefer an explicit "total/final/sale price" if the page shows one
    if L.price is None:
        m = re.search(r"(?:internet|sale|selling|our|final|total|e-?price|special|dealer) price\s*:?\s*\$\s?([\d,]{4,7})", flat, re.I)
        L.price = money(m.group(1)) if m else None
    m = ORIG_MSRP.search(flat)          # only an explicitly ORIGINAL sticker price (a plain "MSRP" on a used car is often the dealer's)
    if m:
        sticker = money(m.group(1))
        L.msrp_new = sticker if sticker and 15000 <= sticker <= 250000 else None
    m = DOC_FEE.search(flat)
    L.doc_fee = money(m.group(1)) if m else None
    others = [money(x) for x in OTHER_FEE.findall(flat)]
    others = [o for o in others if o and o < 5000]
    L.other_fees = sum(others) if others else None
    # the price IS the dealer's all-in figure (Calabasas "Total Transparent Price", West Covina "Final Price"): no fees on top
    m = re.search(r"(?:total transparent|final|out[- ]the[- ]door|all[- ]in) price\s*:?\s*\$\s?([\d,]{4,7})", flat, re.I)
    if m and L.price and abs(money(m.group(1)) - L.price) < 1:
        L.doc_fee, L.other_fees = 0.0, 0.0

    # Features
    feats = []
    for li in soup.find_all("li"):
        t = li.get_text(" ", strip=True)
        if 3 <= len(t) <= 90 and not t.lower().startswith(("home", "new ", "used ", "contact", "service", "parts")):
            feats.append(t)
    L.features = list(dict.fromkeys(feats))
    hay = flat + " " + " ".join(L.features) + " " + str(v.get("description") or "")
    L.ground_clearance_in = ground_clearance(flat)
    if NO_SUNROOF.search(hay):
        L.sunroof, L.sunroof_note = False, NO_SUNROOF.search(hay).group(1)
    elif SUNROOF.search(hay):
        L.sunroof, L.sunroof_note = True, SUNROOF.search(hay).group(1)
    a = AUDIO.search(hay)
    L.audio = a.group(1) if a else ""
    if FAKE_LEATHER.search(hay) or FAKE_WORD.search(L.int_color):
        L.leather = False
    elif LEATHER.search(hay) or "leather" in L.int_color.lower():
        L.leather = True
    L.seats = seat_material(hay, L.int_color)
    if VENT.search(hay):
        L.ventilated_seats = True
    if SPARE_NO.search(hay):
        L.spare_tire, L.spare_note = False, SPARE_NO.search(hay).group(1)
    elif SPARE_YES.search(hay):
        L.spare_tire, L.spare_note = True, SPARE_YES.search(hay).group(1)
    if THIRD_ROW.search(hay):
        L.third_row = True

    # Certification + warranty wording, as quoted on the page
    certs = [c.strip() for c in CERT.findall(flat + " " + L.title + " " + str(v.get("description") or ""))]
    dealer_progs = [f"{m} certified" for m in DEALER_CERT.findall(flat) if m not in NOT_DEALER]
    L.cert_text = " | ".join(dict.fromkeys([c.lower() for c in certs] + [f"dealer program: {d}" for d in dealer_progs]))[:300]
    w = WARRANTY.search(flat)
    L.cpo_warranty_terms = w.group(1).strip()[:200] if w else ""
    strong = []
    if re.search(r"(/cpo/|certified|[-/]cpo[-/])", url, re.I):
        strong.append("url:certified")
    ld_text = " ".join(str(v.get(k) or "") for k in ("name", "description", "itemCondition", "vehicleSpecialUsage"))
    if re.search(r"certified|\bcpo\b|l/certified|blue advantage", ld_text + " " + L.title, re.I):
        strong.append("title:certified")
    L.cert_text = " | ".join(strong + ([L.cert_text] if L.cert_text else []))

    # CARFAX: badge images/text on the dealer page only (never fetch carfax.com)
    badges = set()
    for img in BeautifulSoup(html, PARSER).find_all(["img", "a"]):
        blob = " ".join(str(img.get(k, "")) for k in ("src", "alt", "title", "href", "aria-label", "data-src"))
        if "carfax" in blob.lower():
            for b in CARFAX_BADGE.findall(blob):
                badges.add(b.lower().replace("_", "-").replace(" ", "-"))
    for b in CARFAX_BADGE.findall(flat):
        badges.add(b.lower().replace("_", "-").replace(" ", "-"))
    L.carfax_badges = ",".join(sorted(badges))
    accident_ctx = " ".join(re.findall(r"[^.]{0,80}accident[^.]{0,80}", flat, re.I))
    if HAS_ACCIDENT.search(accident_ctx) and not NO_ACCIDENT.search(accident_ctx):
        L.carfax_status = "accident"
    elif NO_ACCIDENT.search(accident_ctx) or any("accident-free" in b or "no-accident" in b for b in badges):
        L.carfax_status = "clean"
    return L


CHALLENGE_PAGE = re.compile(r"<title>\s*(client challenge|just a moment|attention required|access denied|"
                            r"security check|verify you are human|pardon our interruption)", re.I)


def fetch_vdp(url: str) -> tuple[Listing | None, str]:
    """Fetch + parse one VDP. Second value: '' or a reason (sold/redirected/http error)."""
    try:
        r = fetcher().get(url)
    except FetchError as e:
        return None, str(e)[:120]
    if r.status_code == 404 or r.status_code == 410:
        return None, "gone (HTTP %d)" % r.status_code
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    if CHALLENGE_PAGE.search(r.text[:5000]):
        return None, "blocked: bot challenge page"
    L = parse_vdp(r.text, r.url)
    if L is not None and L.price is None and L.mileage is None and not L.model and not L.ext_color:
        return None, "no vehicle data on page"   # a VIN in the URL alone isn't a listing
    want = url_vin(url)
    if L is None:
        if r.url.rstrip("/") != url.rstrip("/"):
            return None, "redirected to inventory page (sold/removed)"
        return None, "no vehicle data on page"
    if want and want != L.vin and r.url != url:
        return None, "redirected to a different vehicle (sold/removed)"
    return L, ""
