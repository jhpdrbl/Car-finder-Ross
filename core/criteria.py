"""Hard filters (spec section 3), model rules (section 5), scoring and monthly cost (section 4).

evaluate() returns three lists for a listing:
  fails   - a hard rule is broken; the car is excluded
  unknown - the page didn't show something we need (goes to "Needs a call")
  notes   - informational flags (Sportback, edge distance, inferred sunroof, ...)
"""
from __future__ import annotations

import re
import statistics

from scrapers.base import CONFIG
from scrapers.listing import Listing

F = CONFIG["filters"]
S = CONFIG["scoring"]
FIN = CONFIG["finance"]
HOME = CONFIG["home"]


# --------------------------------------------------------------------------
# Model rules
# --------------------------------------------------------------------------

def model_check(L: Listing, d: dict) -> tuple[list[str], list[str], list[str]]:
    """Return (fails, unknown, notes) for brand/model/trim rules."""
    fails, unknown, notes = [], [], []
    make = (d.get("Make") or L.make or "").title()
    model = f'{d.get("Model") or ""} {L.model}'.lower()
    trim = f'{d.get("Trim") or ""} {d.get("Series") or ""} {L.trim} {L.title}'.lower()
    year = L.year or 0
    brand = L.dealer_brand
    if brand == "Audi":
        if re.search(r"\bsq[35]\b|\brs ?q", model + " " + trim):
            fails.append("SQ3/SQ5/RS model (performance versions not on the list)")
        elif not re.search(r"\bq[35]\b", model):
            fails.append(f"model {L.model or d.get('Model')} not on the Audi list (Q3, Q5)")
        if "sportback" in model + trim:
            notes.append("Sportback")
    elif brand == "Genesis":
        if not re.search(r"gv70|gv80", model):
            fails.append(f"model {L.model} not on the Genesis list (GV70, GV80)")
        elif "gv80" in model and "coupe" in model + trim:
            notes.append("GV80 Coupe")
    elif brand == "Subaru":
        if "forester" in model:
            hybrid = "hybrid" in model + trim or (d.get("ElectrificationLevel") or "").lower().startswith("strong")
            if not hybrid and not re.search(r"limited|touring|wilderness", trim):
                fails.append(f"Forester trim {L.trim or '?'} (Limited/Touring/Wilderness or Hybrid only)")
        elif "outback" in model:
            if not re.search(r"limited|touring|wilderness", trim):
                fails.append(f"Outback trim {L.trim or '?'} (Limited/Touring/Wilderness only)")
        else:
            fails.append(f"model {L.model} not on the Subaru list")
    elif brand == "BMW":
        if not re.search(r"\bx[35]\b", model):
            fails.append(f"model {L.model} not on the BMW list (X3, X5)")
        elif re.search(r"sdrive", trim):
            fails.append("sDrive (rear-wheel drive)")
        elif re.search(r"\bm40|\bm50|\bm60|x[35] m\b|competition", trim + " " + model):
            fails.append("M version (only X3 xDrive30i, X5 xDrive40i/50e)")
    elif brand == "Mercedes-Benz":
        if not re.search(r"glc|gle", model):
            fails.append(f"model {L.model} not on the Mercedes list (GLC 300, GLE 350/450/450e)")
        elif re.search(r"amg|gl[ce] ?43|gl[ce] ?53|gl[ce] ?63|coupe|gle ?580", model + " " + trim):
            fails.append("AMG / Coupe / GLE 580 (not on the list)")
        elif "glc" in model and re.search(r"350e", model + trim):
            fails.append("GLC 350e (only GLC 300)")
    elif brand == "Volkswagen":
        if "tiguan" not in model:
            fails.append(f"model {L.model} not on the VW list (Tiguan)")
        elif year and year < 2025:
            fails.append("Tiguan before 2025 (AWD versions have a third row)")
    elif brand == "Lexus":
        if not re.search(r"\b(nx|rx)\b", model):
            fails.append(f"model {L.model} not on the Lexus list (NX, RX)")
        elif re.search(r"rx ?\d{3}h?\+? ?l\b|\brx ?l\b", model + " " + trim):
            fails.append("RX L (3-row)")
        elif re.search(r"nx ?250|\b250\b", model + trim) and not re.search(r"350|450", model + trim):
            fails.append("NX 250 (only NX 350 / 350h / 450h+)")
    elif brand == "Volvo":
        if not re.search(r"xc60|xc40|ex40", model):
            fails.append(f"model {L.model} not on the Volvo list (XC60, XC40)")
    elif brand == "Toyota":
        if "4runner" in model:
            pass
        elif "land cruiser" in model:
            if year and year < 2024:
                fails.append("Land Cruiser before 2024")
        else:
            fails.append(f"model {L.model} not on the Toyota list (4Runner, Land Cruiser 2024+)")
    elif brand == "Ford":
        if "bronco" not in model or "sport" in model:
            fails.append("not a Bronco (Bronco Sport excluded)")
        elif re.search(r"2[- ]?door|2dr", trim):
            fails.append("2-door Bronco")
        elif not re.search(r"4[- ]?door|4dr", trim + " " + L.listing_url.lower()):
            unknown.append("confirm it's a 4-door Bronco")
    return fails, unknown, notes


# --------------------------------------------------------------------------
# Colors
# --------------------------------------------------------------------------

DARK_GREENS = ["autumn green", "cypress green", "british racing", "racing green", "dark green", "forest green",
               "eruption green", "district green", "verde", "jungle green", "hunter green"]
OTHER_COLOR_WORDS = ["blue", "red", "white", "beige", "brown", "orange", "yellow", "gold", "bronze", "copper",
                     "tan", "ivory", "cream", "champagne", "purple", "pink", "mahogany", "burgundy", "maroon",
                     "wine", "garnet", "ruby", "copper", "sand", "khaki"]


def exterior_ok(color: str) -> tuple[str, str]:
    """('pass'|'fail'|'unknown', reason)."""
    c = (color or "").lower()
    if not c.strip():
        return "unknown", "exterior color not shown"
    if any(w in c for w in ("matte", "frozen")):
        return "fail", f"matte paint ({color})"
    if "green" in c:
        if any(g in c for g in DARK_GREENS):
            return "pass", ""
        return "unknown", f"green ({color}): confirm it's a dark green"
    grayish = re.search(r"\b(gr[ae]y|graphite)\b", c)
    for w in F["exterior_colors"]["exclude"]:
        if w == "silver" and grayish:
            continue  # "Silver Gray" / "Silver Graphite" count as gray
        if re.search(rf"\b{re.escape(w)}\b", c):
            return "fail", f"exterior {color}"
    if any(re.search(rf"\b{re.escape(w)}", c) for w in F["exterior_colors"]["include"]):
        return "pass", ""
    if any(w in c for w in OTHER_COLOR_WORDS):
        return "fail", f"exterior {color}"
    return "unknown", f"exterior color '{color}': confirm it's black/gray/dark green"


def interior_ok(color: str) -> tuple[str, str]:
    c = (color or "").lower()
    if not c.strip():
        return "unknown", "interior color not shown"
    for w in F["interior_colors"]["exclude"]:
        if re.search(rf"\b{re.escape(w)}\b", c):
            return "fail", f"interior {color}"
    if any(w in c for w in F["interior_colors"]["include"]):
        return "pass", ""
    if re.search(r"\b(gr[ae]y|silver|blue|green|titanium|stone|ash|light|sky|ultramarine|platinum|mocha|camel)\b", c):
        return "fail", f"interior {color} (black only)"
    return "unknown", f"interior color '{color}': confirm it's black"


# --------------------------------------------------------------------------
# Inference tables
# --------------------------------------------------------------------------

def sunroof_inferred(L: Listing, d: dict) -> str:
    make = (d.get("Make") or L.make or "").lower()
    model = f'{d.get("Model") or ""} {L.model}'.lower()
    trim = f'{d.get("Trim") or ""} {L.trim} {L.title} {L.listing_url}'.lower()
    for row in CONFIG.get("sunroof_standard", []):
        if row["make"].lower() in make and row["model"].lower() in model and re.search(row["trim_regex"], trim):
            if row["model"] == "GV70" and not re.search(row["trim_regex"], f"{L.trim} {L.title} {L.listing_url}".lower()):
                continue  # vPIC's Series lists every GV70 trim; only trust the listing's own trim
            return row["note"]
    return ""


def typical(table: str, L: Listing):
    t = CONFIG.get(table, {})
    model = (L.model or "").title()
    trim = L.trim or ""
    for key in (f"{model} {'Wilderness' if 'wilderness' in trim.lower() else ''}".strip(), model):
        for k, v in t.items():
            if k.lower() == key.lower() or (k.lower() in model.lower() and " " not in k):
                return v
    return None


# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------

def price_total(L: Listing) -> None:
    if L.price is None:
        L.price_total = None
        return
    est = F["estimated_fees"]
    doc = L.doc_fee if L.doc_fee is not None else est["doc_fee"]
    other = L.other_fees if L.other_fees is not None else est["other_fees"]
    L.fees_estimated = L.doc_fee is None or L.other_fees is None
    L.price_total = round(L.price + doc + other)


def monthly_cost(total: float | None) -> float | None:
    if not total:
        return None
    financed = total * (1 + FIN["sales_tax"]) + FIN["gov_fees"] - FIN["down_payment"]
    r = FIN["apr"] / 12
    n = FIN["term_months"]
    return round(financed * r / (1 - (1 + r) ** -n), 0)


def ev_comparables(L: Listing, pool: list[Listing]) -> list[float]:
    return [x.price_total for x in pool if x.vin != L.vin and x.fuel_type == "ev" and x.price_total
            and (x.model or "").lower() == (L.model or "").lower()
            and x.year and L.year and abs(x.year - L.year) <= 1]


# --------------------------------------------------------------------------
# Main evaluation
# --------------------------------------------------------------------------

NAME_2WD = re.compile(r"\b(2wd|rwd|fwd|4x2|sdrive\w*)\b|rear[- ]wheel drive|front[- ]wheel drive|two[- ]wheel drive")
NAME_AWD = re.compile(r"\b(awd|4wd|4x4|4matic|xdrive\w*|quattro|htrac)\b|all[- ]wheel|four[- ]wheel|4motion")


def _over(L: Listing, cap: float, label: str, fails: list, unknown: list) -> None:
    """Over the cap. If only our *estimated* fees push it over, ask instead of excluding."""
    if L.fees_estimated and L.price is not None and L.price <= cap:
        unknown.append(f"${L.price:,.0f} + estimated fees = ${L.price_total:,.0f}, just over the {label}; "
                       "confirm the real out-the-door fees")
    else:
        fails.append(f"${L.price_total:,.0f} over the {label}")


def evaluate(L: Listing, d: dict, dealer: dict, pool: list[Listing], excluded: dict[str, str]):
    fails, unknown, notes = [], [], []
    if L.vin in excluded:
        fails.append(f"manually excluded: {excluded[L.vin]}")

    # VIN decode vs listing
    if d:
        if d.get("ModelYear") and L.year and str(L.year) != d["ModelYear"]:
            notes.append(f"listing says {L.year}, VIN says {d['ModelYear']}")
        L.year = int(d["ModelYear"]) if (d.get("ModelYear") or "").isdigit() else L.year
        if not L.make and d.get("Make"):
            L.make = d["Make"].title()
    else:
        notes.append("VIN not decoded")

    f, u, n = model_check(L, d)
    fails += f
    unknown += u
    notes += n

    if L.year is None:
        unknown.append("model year not shown")
    elif L.year < F["min_year"]:
        fails.append(f"{L.year} (need {F['min_year']}+)")

    if L.mileage is None:
        unknown.append("mileage not shown")
    elif L.mileage > F["max_mileage"]:
        fails.append(f"{L.mileage:,} miles (need under 40,000)")

    # body / rows
    # vPIC SeatRows is model-level ("up to 3"); the seat count tells the configuration
    rows = (d.get("SeatRows") or "").strip()
    seats = (d.get("Seats") or "").strip()
    if seats.isdigit() and int(seats) >= 6:
        fails.append(f"third-row seating ({seats} seats)")
    elif seats.isdigit() and int(seats) <= 5:
        pass
    elif rows.isdigit() and int(rows) >= 3:
        unknown.append("model offers a third row; confirm this one is 2-row")
    elif L.third_row:
        unknown.append("page mentions third-row seating; confirm this one is 2-row")
    if d and "sport utility" not in (d.get("BodyClass") or "").lower() and d.get("BodyClass"):
        fails.append(f"body: {d.get('BodyClass')}")

    # drivetrain
    from verify.vin_decode import drive_class
    dt = drive_class(d) or L.drivetrain
    name = f"{L.model} {L.trim} {L.title} {d.get('Trim') or ''} {L.listing_url}".lower().replace("_", " ")
    if dt not in ("AWD", "4WD") and not drive_class(d):
        # VIN decode silent (common for Mercedes/VW): trust what the listing's name says
        if NAME_2WD.search(name) and not NAME_AWD.search(name):
            dt = "2WD" if not re.search(r"\bfwd\b|front[- ]wheel", name) else "FWD"
        elif NAME_AWD.search(name) and not dt:
            dt = "AWD"
    if L.dealer_brand == "Subaru" and not dt:
        dt = "AWD"
    if dt in ("FWD", "RWD", "2WD"):
        fails.append(f"{dt} (AWD/4WD only)" + (" per the listing" if not drive_class(d) else ""))
    elif not dt:
        unknown.append("drivetrain not shown")
    L.drivetrain = dt or L.drivetrain

    # certification
    from verify.certification import check
    prog, why_not, unsure = check(L, L.dealer_brand)
    L.cpo_program = prog
    if why_not:
        fails.append(why_not)
    if unsure:
        unknown.append(unsure)

    # price
    price_total(L)
    if L.price_total is None:
        unknown.append("price not shown")
    else:
        if L.fees_estimated:
            notes.append("fees estimated")
        fuel = L.fuel_type
        if fuel in ("hybrid", "phev"):
            cap = F["price_caps"][fuel] + F["price_tolerance"]
            if L.price_total > cap:
                _over(L, cap, f"{fuel} cap (${F['price_caps'][fuel]:,} + ${F['price_tolerance']} cushion)", fails, unknown)
        elif fuel == "ev":
            comps = ev_comparables(L, pool)
            if len(comps) < F["ev_min_comparables"]:
                fails.append(f"EV: only {len(comps)} comparable listings, can't call it an exceptional deal")
            else:
                med = statistics.median(comps)
                if L.price_total > med * (1 - F["exceptional_ev_discount"]):
                    fails.append(f"EV not an exceptional deal (${L.price_total:,.0f} vs median ${med:,.0f})")
                else:
                    notes.append(f"exceptional EV deal: {1 - L.price_total / med:.0%} below {len(comps)} comparables")
        else:
            cap = F["price_caps"]["gas"] + F["price_tolerance"]
            if L.price_total > cap:
                _over(L, cap, f"gas cap (${F['price_caps']['gas']:,} + ${F['price_tolerance']} cushion)", fails, unknown)

    # sunroof
    if L.sunroof is False:
        fails.append(f"no sunroof ({L.sunroof_note})")
    elif L.sunroof is None:
        why = sunroof_inferred(L, d)
        if why:
            L.sunroof, L.sunroof_note = True, f"standard on this trim ({why})"
            notes.append("sunroof inferred from trim")
        elif L.dealer_brand == "Genesis" and re.fullmatch(r"2\.5t", (L.trim or "").strip().lower()):
            unknown.append("GV70 2.5T: base has no sunroof, Select+ does; confirm trim/roof")
        else:
            unknown.append("sunroof not shown")

    # colors
    for st, why in (exterior_ok(L.ext_color), interior_ok(L.int_color)):
        if st == "fail":
            fails.append(why)
        elif st == "unknown":
            unknown.append(why)

    # distance
    dist = float(dealer.get("distance_mi") or 0)
    if dist > HOME["edge_radius_miles"]:
        fails.append(f"dealer {dist:.0f} mi away")
    elif dist > HOME["radius_miles"]:
        notes.append(f"edge: dealer {dist:.0f} mi away")

    # CARFAX
    from verify.carfax_badge import status
    L.carfax_status = status(L)
    if L.carfax_status == "accident" and F["carfax_exclude_accident"]:
        fails.append("CARFAX: accident reported")

    # nice-to-have defaults
    if L.ground_clearance_in is None:
        L.ground_clearance_in = typical("ground_clearance_in", L)
    if L.spare_tire is None:
        t = typical("spare_tire_typical", L)
        if t is not None:
            L.spare_tire, L.spare_note = t, "typical for model"
    return [x for x in fails if x], [x for x in unknown if x], notes


def score(L: Listing) -> float:
    w = S["weights"]
    pts = 0.0
    if L.price_total:
        pts += w["price"] * max(0.0, min(1.0, 1 - (L.price_total - S["price_target"]) / 10000))
    pts += w["phev"] * (1.0 if L.fuel_type == "phev" else 0.0)
    mpg = L.mpg_combined
    pts += w["mpg"] * (max(0.0, min(1.0, (mpg - 20) / 20)) if mpg else (0.6 if L.fuel_type in ("hybrid", "phev") else 0.3))
    pts += w["audio"] * (1.0 if L.audio else 0.0)

    def tri(v):
        return 1.0 if v is True else (0.0 if v is False else 0.4)
    pts += w["leather"] * tri(L.leather)
    pts += w["ventilated_seats"] * tri(L.ventilated_seats)
    pts += w["ground_clearance"] * (1.0 if (L.ground_clearance_in or 0) >= 8 else 0.0)
    pts += w["spare_tire"] * tri(L.spare_tire)
    return round(100 * pts / sum(w.values()), 1)
