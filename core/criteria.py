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
CFG = CONFIG


def use(cfg: dict) -> None:
    """Switch every rule below to one buyer's settings (core/profiles.py). Evaluation runs one buyer at a time."""
    global F, S, FIN, HOME, MODELS, CFG
    CFG = cfg
    F, S, FIN, HOME, MODELS = cfg["filters"], cfg["scoring"], cfg["finance"], cfg["home"], cfg.get("models") or {}


# --------------------------------------------------------------------------
# Model rules
# --------------------------------------------------------------------------

MODELS = CONFIG["models"]


def model_check(L: Listing, d: dict) -> tuple[list[str], list[str], list[str]]:
    """Return (fails, unknown, notes) from the brand's rules in config.yaml `models:`."""
    fails, unknown, notes = [], [], []
    spec = MODELS.get(L.dealer_brand)
    if not spec:       # a brand only another buyer searches (e.g. Jenna's Kia for Ross before Kia was added for him)
        fails.append(f"{L.dealer_brand or L.make} isn't one of this buyer's brands")
        return fails, unknown, notes
    model = f'{d.get("Model") or ""} {L.model}'.lower()
    text = " ".join([model, d.get("Trim") or "", d.get("Series") or "", L.trim, L.title, L.listing_url,
                     d.get("ElectrificationLevel") or ""]).lower()
    if not re.search(spec["allow"], model):
        fails.append(f"model {L.model or d.get('Model') or '?'} not on the {L.dealer_brand} list ({spec['list']})")
        return fails, unknown, notes
    out = {"fail": fails, "call": unknown, "note": notes}
    for rule in spec.get("rules") or []:
        if "if" in rule and not re.search(rule["if"], text):
            continue
        if "unless" in rule and re.search(rule["unless"], text):
            continue
        if L.year and (L.year < rule.get("from_year", 0) or L.year > rule.get("to_year", 9999)):
            continue   # rule only for some model years
        if "min_year" in rule:
            if L.year and L.year < rule["min_year"]:
                fails.append(rule["why"])
            continue
        out[rule["then"]].append(rule["why"])
    return fails, unknown, notes


# --------------------------------------------------------------------------
# Colors
# --------------------------------------------------------------------------

DARK_GREENS = ["autumn green", "cypress green", "british racing", "racing green", "dark green", "forest green",
               "eruption green", "district green", "verde", "jungle green", "hunter green"]
OTHER_COLOR_WORDS = ["blue", "red", "white", "beige", "brown", "orange", "yellow", "gold", "bronze", "copper",
                     "tan", "ivory", "cream", "champagne", "purple", "pink", "mahogany", "burgundy", "maroon",
                     "wine", "garnet", "ruby", "copper", "sand", "khaki"]


# Paint names some brands' feeds shorten (Kia's certified search says just "Shadow" for Shadow Matte Gray)
FULL_COLOR_NAMES = {("kia", r"^\s*shadow\s*$"): "Shadow Matte Gray"}


def full_color_name(make: str, color: str) -> str:
    for (mk, rx), full in FULL_COLOR_NAMES.items():
        if mk in (make or "").lower() and re.search(rx, color or "", re.I):
            return full
    return color


def exterior_ok(color: str) -> tuple[str, str]:
    """('pass'|'fail'|'unknown', reason)."""
    c = (color or "").lower()
    rules = F.get("exterior_colors") or {}
    if rules.get("include") is None:          # "any color except ..." (e.g. Jenna: no red/orange)
        bad = rules.get("exclude") or []
        if not c.strip():
            return ("unknown", f"exterior color not shown; confirm it isn't {rules.get('describe') or '/'.join(bad[:2])}") if bad else ("pass", "")
        hit = next((w for w in bad if re.search(rf"\b{re.escape(w)}", c)), None)
        return ("fail", f"exterior {color}") if hit else ("pass", "")
    if not c.strip():
        return "unknown", "exterior color not shown"
    if re.search(r"matte|frozen|magno|\bsatin\b|\bmatt\b", c):     # matte finishes (Ross: never; BMW Frozen, Mercedes magno)
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
    rules = F.get("interior_colors")
    if not rules:                              # this buyer takes any interior color
        return "pass", ""
    if rules.get("include") is None:          # "any interior except ..." (Jenna: no white)
        hit = next((w for w in rules.get("exclude") or [] if re.search(rf"\b{re.escape(w)}", c)), None)
        return ("fail", f"interior {color}") if hit else ("pass", "")
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
    for row in CFG.get("sunroof_standard", []):
        if row.get("not_model") and row["not_model"] in model:
            continue   # e.g. the Bronco's roof panels don't apply to the Bronco Sport
        if row["make"].lower() in make and row["model"].lower() in model and re.search(row["trim_regex"], trim):
            year = L.year or int(d.get("ModelYear") or 0)
            if row.get("min_year") and (not year or year < row["min_year"]):
                continue
            if row.get("max_year") and year and year > row["max_year"]:
                continue
            if row["model"] == "GV70" and not re.search(row["trim_regex"], f"{L.trim} {L.title} {L.listing_url}".lower()):
                continue  # vPIC's Series lists every GV70 trim; only trust the listing's own trim
            return row["note"]
    return ""


def seats_inferred(L: Listing, d: dict) -> tuple[str, str]:
    """(material, note) from config `seat_material` when the listing doesn't say: cloth / synthetic / leather,
    or cloth_std = cloth standard with leather(ette) optional (can't tell from the trim)."""
    make = (d.get("Make") or L.make or "").lower()
    model = f'{d.get("Model") or ""} {L.model}'.lower()
    trim = f'{L.model} {L.trim} {L.title} {L.listing_url}'.lower().replace("-", " ")
    year = L.year or int(d.get("ModelYear") or 0)
    for row in CFG.get("seat_material", []):
        if row.get("not_model") and row["not_model"] in model:
            continue   # e.g. the Bronco's roof panels don't apply to the Bronco Sport
        if row["make"].lower() in make and row["model"].lower() in model and re.search(row["trim_regex"], trim):
            if row.get("min_year") and (not year or year < row["min_year"]):
                continue
            if row.get("max_year") and year and year > row["max_year"]:
                continue
            return row["material"], row.get("note", "")
    return "", ""


def typical(table: str, L: Listing):
    t = CFG.get(table, {})
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


def _cap_label(fuel: str) -> str:
    cap, tol = F["price_caps"][fuel], F.get("price_tolerance") or 0
    if fuels_one_cap():
        return f"${cap:,} limit"
    return f"{fuel} cap (${cap:,}" + (f" + ${tol} cushion)" if tol else ")")


def fuels_one_cap() -> bool:
    caps = {v for v in F["price_caps"].values() if v}
    return len(caps) == 1


def _over(L: Listing, cap: float, label: str, fails: list, unknown: list) -> None:
    """Over the cap. If only our *estimated* fees push it over, ask instead of excluding."""
    if L.fees_estimated and L.price is not None and L.price <= cap:
        unknown.append(f"${L.price:,.0f} + estimated fees = ${L.price_total:,.0f}, just over the {label}; "
                       "confirm the real out-the-door fees")
    else:
        fails.append(f"${L.price_total:,.0f} over the {label}")


def evaluate(L: Listing, d: dict, dealer: dict, pool: list[Listing], excluded: dict[str, str]):
    fails, unknown, notes = [], [], []
    L.ext_color = full_color_name(L.make or L.dealer_brand, L.ext_color)
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
    if not F.get("max_rows"):
        pass                                   # this buyer is fine with a third row
    elif seats.isdigit() and int(seats) >= 6:
        fails.append(f"third-row seating ({seats} seats)")
    elif seats.isdigit() and int(seats) <= 5:
        pass
    elif rows.isdigit() and int(rows) >= 3:
        unknown.append("model offers a third row; confirm this one is 2-row")
    elif L.third_row:
        unknown.append("page mentions third-row seating; confirm this one is 2-row")
    also_suv = F.get("also_suv")      # models a buyer counts as SUVs though the VIN record says otherwise (Lexus UX = "Wagon")
    if (d and "sport utility" not in (d.get("BodyClass") or "").lower() and d.get("BodyClass")
            and not (also_suv and re.search(also_suv, f"{L.model} {d.get('Model') or ''}".lower()))):
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

    # fuel: some buyers take only certain kinds (Jenna: regular hybrids; mild hybrids count as gas)
    fuels = F.get("fuels")
    if fuels and L.fuel_type and L.fuel_type not in fuels:
        fails.append({"gas": "not a hybrid (gas only)", "phev": "plug-in hybrid (regular hybrids only)",
                      "ev": "electric (regular hybrids only)"}.get(L.fuel_type, f"{L.fuel_type} (hybrids only)"))
    elif fuels and not L.fuel_type:
        unknown.append("fuel type not shown; confirm it's a hybrid")

    # price
    price_total(L)
    if L.price_total is None:
        unknown.append("price not shown")
    else:
        if L.fees_estimated:
            notes.append("fees estimated")
        fuel = L.fuel_type
        if fuel in ("hybrid", "phev") or (fuel == "ev" and F["price_caps"].get("ev")):
            cap = F["price_caps"][fuel] + F["price_tolerance"]
            if L.price_total > cap:
                _over(L, cap, _cap_label(fuel), fails, unknown)
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
                _over(L, cap, _cap_label("gas"), fails, unknown)

    # sunroof
    if not F.get("sunroof_required", True):    # nice to have: shown and scored, never excludes
        if L.sunroof is None:
            why = sunroof_inferred(L, d)
            if why:
                L.sunroof, L.sunroof_note = True, f"standard on this trim ({why})"
                notes.append("sunroof inferred from trim")
    elif L.sunroof is False:
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

    # seats: no cloth (Jenna)
    if F.get("no_cloth_seats"):
        mat, how = (L.seats, "per the listing") if L.seats else (seats_inferred(L, d)[0], "standard on this trim")
        if mat == "cloth":
            fails.append("cloth seats" + (f" ({how})" if how else ""))
        elif mat in ("leather", "synthetic"):
            if not L.seats:
                L.seats = mat
                notes.append(f"{'synthetic leather' if mat == 'synthetic' else 'leather'} seats inferred from trim")
        elif mat == "cloth_std":
            unknown.append("cloth seats are standard on this trim (leather/synthetic optional); confirm the seats")
        else:
            unknown.append("seat material not shown; confirm leather or synthetic leather (no cloth)")

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
    if L.carfax_status == "accident" and F.get("carfax_exclude_accident", True):
        fails.append("CARFAX: accident reported")

    # nice-to-have defaults
    if L.ground_clearance_in is None:
        L.ground_clearance_in = typical("ground_clearance_in", L)
    if L.spare_tire is None:
        t = typical("spare_tire_typical", L)
        if t is not None:
            L.spare_tire, L.spare_note = t, "typical for model"
    return [x for x in fails if x], [x for x in unknown if x], notes


# Exterior color families, most specific first ("Silver Gray" is gray, "Black Sapphire" is black, "Titanium Glow" is gold)
COLOR_FAMILIES = [
    ("gold", r"titanium glow|champagne|\bgold"),
    ("brown", r"sand dune|\b(brown|bronze|mocha|espresso|chestnut|coffee|tan|beige|sand|khaki|desert|earth)\b"),
    ("black", r"\b(black|ebony|obsidian|onyx|jet|caviar|vik|panthera)\b|shadow black"),
    ("gray", r"\b(gr[ae]y|shadow|graphite|gunmetal|charcoal|slate|steel|magnetic|magnetite|cement|lunar|titanium|polymetal|machine|meteor|storm|asphalt|carbon|tungsten|anthracite)\b"),
    ("dark blue", r"\b(navy|sapphire|cobalt|indigo|nightfall|blueprint|abyss|deep ocean)\b|"
                  r"blue(?!.*\b(sky|light|ice|horizon|cerulean|aqua|baby|powder|pale)\b)"),
    ("silver", r"\b(silver|platinum|iridium|alloy|quicksilver)\b"),
    ("white", r"\b(white|snow|ivory|glacier|blizzard|frost|opal|wind chill)\b"),
    ("other", r"\b(yellow|citron|green|lime|purple|pink|orange|red|teal|turquoise|copper)\b"),
]


def color_family(color: str) -> str:
    """The family of the first color word named (two-tone "Cavalry Blue/Midnight Black" = blue body)."""
    c = (color or "").lower()
    if "silver" in c and re.search(r"gr[ae]y|graphite", c):
        return "gray"                          # "Silver Gray" counts as gray (same as Ross's color rule)
    hits = [(m.start(), i, fam) for i, (fam, rx) in enumerate(COLOR_FAMILIES) if (m := re.search(rx, c))]
    if not hits:
        return "white" if "pearl" in c else ("other" if c.strip() else "")
    return min(hits)[2]


def score_parts(L: Listing) -> dict[str, float]:
    """Each scored item as 0..1 (how good this car is on it). score() weights them; the dashboard explains them."""
    tri = lambda v: 1.0 if v is True else (0.0 if v is False else 0.4)
    parts = {}
    if L.price_total:
        parts["price"] = max(0.0, min(1.0, 1 - (L.price_total - S.get("price_target", 30000)) / 10000))
    parts["phev"] = 1.0 if L.fuel_type in ("phev", "ev") else 0.0      # electric cars plug in too
    mpg = L.mpg_combined
    parts["mpg"] = max(0.0, min(1.0, (mpg - 20) / 20)) if mpg else (0.6 if L.fuel_type in ("hybrid", "phev") else 0.3)
    parts["audio"] = 1.0 if L.audio else 0.0
    parts["leather"] = tri(L.leather)
    parts["real_leather"] = 1.0 if (L.leather is True or L.seats == "leather") else (0.4 if L.seats == "synthetic" or L.leather is False else 0.2)
    parts["ventilated_seats"] = tri(L.ventilated_seats)
    parts["ground_clearance"] = 1.0 if (L.ground_clearance_in or 0) >= 8 else 0.0
    parts["spare_tire"] = tri(L.spare_tire)
    parts["sunroof"] = 1.0 if L.sunroof is True else (0.0 if L.sunroof is False else 0.3)
    rank = S.get("color_rank") or []
    fam = color_family(L.ext_color)
    parts["exterior_color"] = (len(rank) - rank.index(fam)) / len(rank) if fam in rank else (0.0 if fam else 0.3)
    cap = F.get("max_mileage") or 40000
    parts["mileage"] = max(0.0, 1 - L.mileage / cap) if L.mileage is not None else 0.3
    return parts


def score(L: Listing) -> float:
    """0-100: each item in this buyer's config `scoring.weights` counts its weight times how good the car is on it."""
    w = S["weights"]
    parts = score_parts(L)
    pts = sum(wt * parts.get(k, 0.0) for k, wt in w.items())
    return round(100 * pts / sum(w.values()), 1)


def _old_score(L: Listing) -> float:     # kept for reference: the formula before Oct 2026 (same result as score() for Ross)
    w = S["weights"]
    pts = 0.0
    if L.price_total:
        pts += w["price"] * max(0.0, min(1.0, 1 - (L.price_total - S["price_target"]) / 10000))
    pts += w.get("phev", 0) * (1.0 if L.fuel_type == "phev" else 0.0)
    mpg = L.mpg_combined
    pts += w["mpg"] * (max(0.0, min(1.0, (mpg - 20) / 20)) if mpg else (0.6 if L.fuel_type in ("hybrid", "phev") else 0.3))
    pts += w["audio"] * (1.0 if L.audio else 0.0)

    def tri(v):
        return 1.0 if v is True else (0.0 if v is False else 0.4)
    pts += w.get("leather", 0) * tri(L.leather)
    pts += w.get("sunroof", 0) * tri(L.sunroof)
    pts += w["ventilated_seats"] * tri(L.ventilated_seats)
    pts += w["ground_clearance"] * (1.0 if (L.ground_clearance_in or 0) >= 8 else 0.0)
    pts += w["spare_tire"] * tri(L.spare_tire)
    return round(100 * pts / sum(w.values()), 1)
