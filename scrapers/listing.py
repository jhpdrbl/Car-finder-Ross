"""The normalized record every adapter produces, plus small shared helpers."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote

VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
VIN_ANY = re.compile(r"(?<![A-Za-z0-9])([A-HJ-NPR-Za-hj-npr-z0-9]{17})(?![A-Za-z0-9])")

# Model words to look for in a dealer's URLs / listings, per brand (spec section 5): Ross's models here,
# plus every other buyer's `tokens:` from config.yaml (core/profiles.py), added below.
MODEL_TOKENS = {
    "Audi": ["q5", "q3"],
    "Genesis": ["gv70", "gv80"],
    "Subaru": ["forester", "outback"],
    "BMW": ["x3", "x5"],
    "Mercedes-Benz": ["glc", "gle"],
    "Volkswagen": ["tiguan"],
    "Lexus": ["nx", "rx"],
    "Volvo": ["xc60", "xc40", "ex40"],
    "Toyota": ["4runner", "land-cruiser", "landcruiser"],
    "Ford": ["bronco"],
}


ROSS_TOKENS = {b: list(t) for b, t in MODEL_TOKENS.items()}


def _add_profile_tokens() -> None:
    from core.profiles import BRANDS, model_tokens
    for b in BRANDS:
        for t in model_tokens(b):
            if t not in MODEL_TOKENS.setdefault(b, []):
                MODEL_TOKENS[b].append(t)


_add_profile_tokens()


@dataclass
class Listing:
    vin: str
    dealer: str = ""                 # dealer name from dealers.csv
    dealer_brand: str = ""           # franchise brand of the selling dealer
    dealer_url: str = ""             # dealer homepage
    listing_url: str = ""            # the dealer's own VDP for this car
    source: str = ""                 # how it was found: sitemap / dealer_com / brand feed / ...
    title: str = ""
    year: int | None = None
    make: str = ""
    model: str = ""
    trim: str = ""
    packages: str = ""
    body: str = ""
    stock: str = ""
    condition: str = ""              # new / used / certified (as the page says)
    price: float | None = None       # advertised price
    doc_fee: float | None = None
    other_fees: float | None = None  # filing, smog, etc.
    price_total: float | None = None
    fees_estimated: bool = False
    mileage: int | None = None
    ext_color: str = ""
    int_color: str = ""
    drivetrain: str = ""
    fuel_type: str = ""              # gas / hybrid / phev / ev (after verification)
    mpg_city: float | None = None
    mpg_hwy: float | None = None
    mpg_combined: float | None = None
    mpg_source: str = ""             # "listing" (dealer page / brand feed) or "EPA" (fueleconomy.gov)
    sunroof: bool | None = None
    sunroof_note: str = ""
    audio: str = ""
    leather: bool | None = None      # True = genuine leather, False = synthetic leather, None = not shown
    seats: str = ""                  # seat material: leather / synthetic / cloth ("" = not shown)
    ventilated_seats: bool | None = None
    spare_tire: bool | None = None
    spare_note: str = ""
    ground_clearance_in: float | None = None
    third_row: bool | None = None
    cert_text: str = ""              # certification wording found on the page
    cpo_program: str = ""
    cpo_warranty_terms: str = ""
    carfax_badges: str = ""
    carfax_status: str = "not_verified"
    location_note: str = ""          # e.g. car is at a sister store
    link_note: str = ""              # when the link isn't the car's own page (e.g. dealer inventory searched by VIN)
    features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["features"] = "; ".join(self.features[:80])
        return d


VIN_PARAM = re.compile(r"[?&](?:vehicleid|vin)=([A-HJ-NPR-Z0-9]{17})(?:&|$)", re.I)


def url_vin(url: str) -> str:
    """The VIN a listing URL carries: in the path (most platforms) or as ?vehicleId=/?vin= (Audi's dealer sites)."""
    m = VIN_PARAM.search(url)
    if m:
        return m.group(1).upper()
    m = VIN_ANY.search(url.split("?")[0])
    if m and re.search(r"\d", m.group(1)) and re.search(r"[a-zA-Z]", m.group(1)):
        return m.group(1).upper()
    return ""


# Listing URLs we can drop without reading the page (versions that are never on the list).
URL_SKIP = re.compile(r"sdrive|(?<![a-z])(2wd|fwd|4x2)(?![a-z])|(?<![a-z])amg(?![a-z])|(?<![a-z])m[56]0i?(?![a-z0-9])|x[35]-m(?![a-z])|"
                      r"rx-?350-?l(?![a-z])|gl[ce][a-z0-9-]*coupe|sq[35]|rs-?q[358]|bronco-sport|gle-?(43|53|63|580)|glc-?(43|63)")


def norm_url_text(url: str) -> str:
    """Lower-case URL with separators normalized, for model/year matching."""
    u = unquote(unquote(url)).replace("&#x2b;", "+").replace("&#x2B;", "+").lower()
    return re.sub(r"[+_%\s]", "-", u)


def url_condition(url: str) -> str:
    u = norm_url_text(url)
    if re.search(r"(certified|/cpo/|-cpo-|pre-owned|preowned|/used|used-|-used)", u):
        return "used"
    if re.search(r"(/new/|/new-|-new-|-new/|new-inventory|/inventory/new)", u):
        return "new"
    return ""


def url_years(url: str) -> list[int]:
    return [int(y) for y in re.findall(r"(?<!\d)(20[12]\d)(?!\d)", norm_url_text(url))]


def _ross_match(u: str, brand: str) -> bool:
    if brand == "Ford":
        return "bronco" in u and "bronco-sport" not in u
    if brand == "Lexus":
        return re.search(r"(?<![a-z0-9])(nx|rx)(?![a-z])", u) is not None
    if brand == "BMW":
        return re.search(r"(?<![a-z0-9])x[35](?![0-9])", u) is not None
    return any(t in u for t in ROSS_TOKENS.get(brand, []))


def url_matches_brand_models(url: str, brand: str) -> bool:
    """Could this URL be a car some buyer wants? Ross's model words, then other buyers' (whole words)."""
    u = norm_url_text(url)
    if _ross_match(u, brand):
        return True
    extra = [t for t in MODEL_TOKENS.get(brand, []) if t not in ROSS_TOKENS.get(brand, [])]
    return any(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z])", u) for t in extra)


def money(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s) if s > 0 else None
    m = re.search(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,7})(?:\.\d\d)?", str(s))
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v if v > 0 else None


def integer(s) -> int | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    m = re.search(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)", str(s))
    return int(m.group(1).replace(",", "")) if m else None
