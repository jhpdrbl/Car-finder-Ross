"""The normalized record every adapter produces, plus small shared helpers."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote

VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
VIN_ANY = re.compile(r"(?<![A-Za-z0-9])([A-HJ-NPR-Za-hj-npr-z0-9]{17})(?![A-Za-z0-9])")

# Model words to look for in a dealer's URLs / listings, per brand (spec section 5).
MODEL_TOKENS = {
    "Audi": ["q5"],
    "Genesis": ["gv70"],
    "Subaru": ["forester", "outback"],
    "BMW": ["x3"],
    "Mercedes-Benz": ["glc"],
    "Volkswagen": ["tiguan"],
    "Lexus": ["nx"],
    "Volvo": ["xc60"],
    "Toyota": ["4runner", "land-cruiser", "landcruiser"],
    "Ford": ["bronco"],
}


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
    sunroof: bool | None = None
    sunroof_note: str = ""
    audio: str = ""
    leather: bool | None = None
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
    features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["features"] = "; ".join(self.features[:80])
        return d


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


def url_matches_brand_models(url: str, brand: str) -> bool:
    u = norm_url_text(url)
    toks = MODEL_TOKENS.get(brand, [])
    if brand == "Ford":
        return "bronco" in u and "bronco-sport" not in u
    if brand == "Lexus":
        return re.search(r"(?<![a-z0-9])nx(?![a-z])", u) is not None
    if brand == "BMW":
        return re.search(r"(?<![a-z0-9])x3(?![0-9])", u) is not None
    return any(t in u for t in toks)


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
