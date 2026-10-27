"""Digest (markdown for Apple Notes), coverage report, and the static HTML dashboard."""
from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

from scrapers.base import CONFIG

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
TRIM_GUIDE = ROOT / "data" / "trim_guide.json"   # hand-researched reference for the Trim guide tab
WARRANTY = ROOT / "data" / "warranty.json"        # factory + certified pre-owned warranty terms by brand


FUEL_LABEL = {"gas": "Gas", "hybrid": "Hybrid", "phev": "Plug-in hybrid", "ev": "Electric"}


def _money(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "?"


def _miles(v) -> str:
    try:
        return f"{int(float(v)):,} mi"
    except (TypeError, ValueError):
        return "? mi"


def _features(r: dict) -> str:
    bits = []
    if r.get("sunroof") == "True":
        bits.append("sunroof")
    if r.get("audio"):
        bits.append(r["audio"])
    if r.get("leather") == "True":
        bits.append("leather")
    if r.get("ventilated_seats") == "True":
        bits.append("ventilated seats")
    if r.get("cpo_program"):
        bits.append(r["cpo_program"])
    return ", ".join(bits)


def _carfax(r: dict) -> str:
    s = r.get("carfax_status", "not_verified")
    return {"clean": "CARFAX: no accidents", "accident": "CARFAX: accident"}.get(s, "CARFAX: not verified")


def _title(r: dict) -> str:
    return " ".join(x for x in (str(r.get("year") or ""), r.get("make", ""), r.get("model", ""), r.get("trim", "")) if x).strip()


def _line(r: dict) -> str:
    t = _title(r)
    link = f"[{t}]({r['listing_url']})" if r.get("listing_url") else t
    colors = " / ".join(x for x in (r.get("ext_color"), r.get("int_color")) if x) or "colors ?"
    parts = [f"**{link}** at {r.get('dealer', '?')}", f"VIN {r['vin']}", _money(r.get("price_total")) +
             (" (fees est.)" if r.get("fees_estimated") == "True" else ""), _miles(r.get("mileage")), colors]
    parts.append(FUEL_LABEL.get(r.get("fuel_type", ""), "fuel ?"))
    if r.get("mpg_combined"):
        parts.append(f"{float(r['mpg_combined']):.0f} mpg" + (" gas-only" if r.get("fuel_type") == "phev" else "")
                     + (" (EPA)" if r.get("mpg_source") == "EPA" else ""))
    feats = _features(r)
    if feats:
        parts.append(feats)
    parts.append(_carfax(r))
    if r.get("est_monthly_cost"):
        parts.append(f"~{_money(r['est_monthly_cost'])}/mo")
    if r.get("score"):
        parts.append(f"score {r['score']}")
    line = "- " + " · ".join(parts)
    extra = [n for n in (r.get("notes") or "").split("; ") if n]
    if r.get("recall_flags"):
        extra.append(f"recalls to confirm completed: {r['recall_flags'][:160]}")
    if extra:
        line += "\n  - " + "; ".join(extra)
    return line


def coverage_rows(results, feed_stats: dict) -> list[dict]:
    rows = []
    for brand, st in feed_stats.items():
        rows.append({"brand": brand, "dealer": f"{brand} brand CPO feed", "status": st["status"],
                     "reason": st.get("reason") or f"{st.get('in_area', 0)} certified listings at our dealers",
                     "listings": st.get("in_area", ""), "distance_mi": "", "homepage": ""})
    for r in sorted(results, key=lambda r: (r.dealer["brand"], r.status != "success", float(r.dealer["distance_mi"] or 0))):
        rows.append({"brand": r.dealer["brand"], "dealer": r.dealer["dealer_name"], "status": r.status,
                     "reason": r.reason, "listings": r.parsed + len(r.carried), "distance_mi": r.dealer["distance_mi"],
                     "homepage": r.dealer["homepage"], "method": r.method})
    return rows


def _profile(profile=None):
    from core import profiles
    return profile or profiles.get()


def write_digest(rows: list[dict], changes: dict, cov: list[dict], today: str | None = None, profile=None) -> Path:
    P = _profile(profile)
    today = today or date.today().isoformat()
    active = [r for r in rows if r.get("status") == "active"]
    matches = sorted([r for r in active if not r.get("needs_call")], key=lambda r: -float(r.get("score") or 0))
    calls = sorted([r for r in active if r.get("needs_call")], key=lambda r: -float(r.get("score") or 0))
    ok = [c for c in cov if c["status"] == "success"]
    failed = [c for c in cov if c["status"] == "failed"]
    skipped = [c for c in cov if c["status"] == "skipped"]
    L = [f"# CPO SUV digest — {today}" + ("" if P.is_default else f" — {P.label}"), ""]
    L += [f"- {b}" for b in P.cfg.get("buying_context") or []]
    L += ["", "## Coverage report", "",
          f"{len(ok)} sources read · {len(failed)} failed · {len(skipped)} skipped (covered by a brand feed)", ""]
    if failed:
        L.append("**Failed:**")
        for c in failed:
            L.append(f"- {c['brand']} · {c['dealer']} ({c['distance_mi']} mi): {c['reason']}")
        L.append("")
    L.append("**Read:**")
    for c in ok:
        L.append(f"- {c['brand']} · {c['dealer']}: {c['reason']}")
    L += ["", f"## ✅ Meets all criteria ({len(matches)})", ""]
    L += [_line(r) for r in matches] or ["- none this run"]
    new_vins = {r["vin"] for r in changes["new"]}
    L += ["", f"## 🆕 New since last run ({len([r for r in active if r['vin'] in new_vins])})", ""]
    L += [_line(r) + ("\n  - ⚠️ needs a call: " + r["needs_call"] if r.get("needs_call") else "")
          for r in active if r["vin"] in new_vins] or ["- none"]
    L += ["", f"## 💲 Price changes ({len(changes['price'])})", ""]
    for r, old, new in changes["price"]:
        if r.get("status") == "active":
            arrow = "⬇️" if new < old else "⬆️"
            L.append(f"- {arrow} [{_title(r)}]({r.get('listing_url', '')}) at {r.get('dealer')}: {_money(old)} → {_money(new)} · VIN {r['vin']}")
    if not changes["price"]:
        L.append("- none")
    L += ["", f"## ⚠️ Needs a call ({len(calls)})", "", "_Passes everything the page showed; the items listed weren't on the page._", ""]
    for r in calls:
        L.append(_line(r) + f"\n  - **ask about:** {r['needs_call']}")
    if not calls:
        L.append("- none")
    gone = changes["removed"] + changes["newly_excluded"]
    L += ["", f"## ❌ Removed / sold / newly excluded ({len(gone)})", ""]
    for r in gone:
        L.append(f"- {_title(r)} at {r.get('dealer')} · VIN {r['vin']}: {r.get('fail_reasons') or r.get('status')}")
    if not gone:
        L.append("- none")
    L += ["", "_Every result links to the dealer's own listing page. CARFAX status comes from the dealer page's badge only. "
          "Recalls are model-level campaigns; check the VIN at https://www.nhtsa.gov/recalls._", ""]
    P.out.mkdir(parents=True, exist_ok=True)
    path = P.out / f"digest_{today}.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path


# ---- "Check yourself": dealers no method could read, with links to look at them by hand ----
TOP_BRANDS = ("Audi", "Subaru", "Genesis")      # Ross's; another buyer sets `top_brands:` in config.yaml
_CFG = CONFIG                                     # the buyer whose page is being written (set by write_dashboard)


def _plain_reason(reason: str) -> str:
    r = reason.lower()
    if "wrong website address" in r:
        return "The website address on file is wrong (tell Claude the dealer's real site)"
    if "robots.txt" in r:
        return "Its website asks automated tools not to read it"
    if "browser" in r or "couldn't see" in r:
        return "Its cars only show up in a full web browser"
    if "unreachable" in r or "timeout" in r or "sslerror" in r or "connection" in r:
        return "Its website didn't respond (the address may be wrong)"
    if "blocked" in r or "403" in r or "503" in r or "challenge" in r or "bot" in r:
        return "Its website blocks automated searches"
    return "Couldn't read its website"


def _model_words(brand: str) -> list[str]:
    """Search words for a brand's models from config.yaml (e.g. 'GLE 350/450/450e' -> 'GLE')."""
    return list(_model_years(brand))


def _model_years(brand: str) -> dict[str, int]:
    """{model word: earliest model year} from config.yaml's list (e.g. 'Tiguan 2025+' -> {'Tiguan': 2025},
    'ZDX (electric, AWD), RDX (SH-AWD)' -> ZDX, RDX; 'plug-in sedans S60 / S90 T8' -> S60, S90)."""
    spec = _CFG.get("models", {}).get(brand) or {}
    lst = spec.get("list", "")
    base = int(_CFG.get("filters", {}).get("min_year") or _CFG.get("min_year") or 2023)
    while re.search(r"\([^()]*\)", lst):
        lst = re.sub(r"\s*\([^()]*\)", "", lst)                # notes in brackets: "(electric, AWD)"
    lst = re.sub(r"(\d{3}\w*)(?:/\d{3}\w*)+", r"\1", lst)   # "GLE 350/450/450e": versions of one model, not models
    out: dict[str, int] = {}
    for part in re.split(r"[,;/]", lst):
        y = re.search(r"(\d{4})\+", part)
        w = re.sub(r"^\s*(?:(?:plug-in|electric|hybrid|gas|sedans?|and|incl\.?)\s+)+", "", part, flags=re.I)
        w = re.sub(r"\s*(\d{3}\b.*|\d{4}\+.*|4-door.*|\b(?:xdrive|awd|4matic|t8|hybrid|sedan)\b.*)$", "", w, flags=re.I).strip()
        if not w or re.fullmatch(r"(?i)plug-in|electric|hybrid|gas|sedans?|\d+", w) or w.lower() in map(str.lower, out):
            continue
        yr = int(y.group(1)) if y else base
        for rule in spec.get("rules") or []:          # e.g. {if: zdx, min_year: 2024}
            if rule.get("min_year") and not rule.get("unless") and re.search(rule.get("if") or "$^", w.lower()):
                yr = max(yr, int(rule["min_year"]))
        out[w] = yr
    return out


# Dealer Inspire filters, checked by the user on a real DI site (Oct 2026): year and ext_color_generic work;
# drivetrain values are spelled out, so several spellings are listed (any one matching is enough).
DI_DRIVES = ("All-Wheel Drive", "All Wheel Drive", "AWD", "Four-Wheel Drive", "Four Wheel Drive", "4WD", "4x4")
DI_COLORS = ("Black", "Gray", "Silver", "Green")   # Ross's exterior rule: black / gray / silver / dark green (light greens filtered by eye)


def _di_colors() -> tuple:
    """Color filter for the links: Ross's black/gray/green; none for a buyer who takes most colors."""
    return DI_COLORS if (_CFG.get("filters", {}).get("exterior_colors") or {}).get("include") else ()


def _di_filters(model: str, min_year: int) -> str:
    from urllib.parse import quote
    from datetime import date as _d
    parts = [f"_dFR%5Bmodel%5D%5B0%5D={quote(model)}"]
    parts += [f"_dFR%5Byear%5D%5B{i}%5D={y}" for i, y in enumerate(range(min_year, _d.today().year + 2))]
    if _CFG.get("filters", {}).get("awd_required", True):     # since Oct 25 2026 AWD is only a nice-to-have
        parts += [f"_dFR%5Bdrivetrain%5D%5B{i}%5D={quote(v)}" for i, v in enumerate(DI_DRIVES)]
    parts += [f"_dFR%5Bext_color_generic%5D%5B{i}%5D={quote(v)}" for i, v in enumerate(_di_colors())]
    return "&".join(parts)


def _cpo_base(d: dict) -> str:
    """The dealer's own CERTIFIED inventory page: the one on file, else the platform's standard path."""
    inv = d.get("inventory_url") or ""
    if re.search(r"certified|/cpo|cpo-|type=cpo", inv, re.I):
        return inv
    home, plat = (d.get("homepage") or "").rstrip("/"), d.get("platform") or ""
    if plat == "dealer_inspire":       # Dealer Inspire's standard certified page (Lexus's own data uses it for 6 of 7 DI dealers)
        return f"{home}/used-vehicles/certified-pre-owned-vehicles/"
    if plat == "dealer_com":
        return f"{home}/certified-inventory/index.htm"
    return ""


def _model_link(d: dict, brand: str, model: str) -> str:
    """The dealer's certified inventory filtered to one model (and, on Dealer Inspire, to your year and
    color rules, plus AWD when it's required), where the platform's filter format is known."""
    from urllib.parse import quote
    base, plat = _cpo_base(d), d.get("platform") or ""
    if not base:
        return ""
    sep = "&" if "?" in base else "?"
    if plat == "dealer_inspire" and "/certified" in base:
        return f"{base}{sep}{_di_filters(model, _model_years(brand).get(model, 2023))}"
    if plat == "dealer_com":
        return f"{base}{sep}search={quote(model)}"
    return ""


def check_list(cov: list[dict], profile=None) -> list[dict]:
    import csv
    global _CFG
    P = _profile(profile)
    _CFG = P.cfg
    dealers = {r["dealer_name"]: r for r in csv.DictReader((ROOT / "data" / "dealers.csv").open(encoding="utf-8"))}
    fed = {c["brand"] for c in cov if c["dealer"].endswith("brand CPO feed") and c["status"] == "success"}
    out = []
    for c in cov:
        if c["status"] != "failed" or c["dealer"].endswith("brand CPO feed") or c["brand"] in fed:
            continue   # a brand feed that worked already brings in that brand's certified cars
        if c["brand"] not in P.models():
            continue   # a brand this buyer has no models from
        if c["dealer"] not in dealers:
            continue   # dealer since removed from the list (e.g. one that turned out not to exist)
        d = dealers[c["dealer"]]
        models = _model_words(c["brand"])
        links = [{"label": f"{m} (certified)", "url": u} for m in models if (u := _model_link(d, c["brand"], m))]
        out.append({"dealer": c["dealer"], "brand": c["brand"], "distance_mi": c.get("distance_mi", ""),
                    "why": _plain_reason(c.get("reason", "")), "detail": c.get("reason", "")[:140],
                    "models": models, "links": links,
                    "cpo": _cpo_base(d),
                    "guess": "(inferred" in (d.get("notes") or ""),
                    "homepage": d.get("homepage") or c.get("homepage", "")})
    rank = {b: i for i, b in enumerate(P.cfg.get("top_brands", TOP_BRANDS) or [])}
    out.sort(key=lambda x: (rank.get(x["brand"], 9), x["brand"], float(x["distance_mi"] or 999)))   # by brand, then distance
    return out


def _mix(a: str, b: str, t: float) -> str:
    """Hex color a mixed into b by fraction t."""
    pa, pb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * t + y * (1 - t)):02x}" for x, y in zip(pa, pb))


def score_help(P) -> str:
    """Plain-words explanation of this buyer's score (from config scoring.weights)."""
    sc = P.cfg.get("scoring") or {}
    w = sc.get("weights") or {}
    tgt = sc.get("price_target", 30000)
    rank = sc.get("color_rank") or []
    label = {
        "price": f"Price: full points at ${tgt:,} or less, none at ${tgt + 10000:,}",
        "phev": "Plug-in hybrid or electric: all or nothing",
        "mpg": "Gas mileage: none at 20 mpg, full at 40 mpg",
        "audio": "Premium sound system (Harman Kardon, B&O, Burmester…)",
        "leather": "Real leather seats (not shown on the listing: 40%)",
        "ventilated_seats": "Cooled seats (not shown: 40%)",
        "ground_clearance": "Ground clearance of 8 inches or more",
        "spare_tire": "Spare tire (not shown: 40%)",
        "awd": "All-wheel drive (not shown: 30%)",
        "sunroof": "Sunroof (not shown: 30%)",
        "exterior_color": "Exterior color, in this order: " + " › ".join(rank) + " › anything else" if rank else "Exterior color",
        "mileage": "Mileage: full points at 0 miles, none at 40,000",
        "real_leather": "Real leather seats: full points; synthetic leather 40%",
    }
    total = sum(w.values()) or 1
    items = "".join(f"<li><b>{round(100 * v / total)} pts</b> · {html.escape(label.get(k, k))}</li>"
                    for k, v in sorted(w.items(), key=lambda kv: -kv[1]))
    return (f'<details id="scorehelp"><summary><b>How the score works</b> <span class="small">(0–100; it only ranks cars '
            f'that already pass every rule)</span></summary><ul>{items}</ul><p class="small">Each item gives its points '
            f'in full, in part or not at all, and the score adds them up. A car only reaches 100 if it is best on '
            f'everything at once, so even very good matches usually land between 50 and 75.</p></details>')


def theme_vars(P) -> dict:
    """Each buyer's color (config `theme:`): Ross British Racing Green, Jenna Cobalt Blue."""
    th = P.cfg.get("theme") or {"light": "#2c6e57", "dark": "#7cc7a8"}
    return {"__ACC_L__": th["light"], "__ACC_D__": th["dark"],
            "__BG_L__": _mix(th["light"], "#f6f6f5", .06), "__LINE_L__": _mix(th["light"], "#dde0de", .12),
            "__BG_D__": _mix(th["dark"], "#111312", .06), "__SURF_D__": _mix(th["dark"], "#191b1a", .08),
            "__LINE_D__": _mix(th["dark"], "#2a2e2c", .12)}


# VIN beginnings that name the version when the dealer doesn't (seen on listings that do name it, and on a window sticker)
VIN_VERSION = {"4JGGM1CB": "EQE 350 4MATIC", "W1N9M0KB": "EQB 300 4MATIC"}


def _spec_fields(r: dict, page_cl: dict | None = None) -> dict:
    """Ground clearance (one figure per model / year / trim, see specs.best_clearance) and EPA electric range."""
    from verify import specs
    extra = f'{VIN_VERSION.get((r.get("vin") or "")[:8].upper(), "")} {r.get("body") or ""}'   # SUV vs sedan, version
    page = r.get("ground_clearance_in") or (page_cl or {}).get((r.get("year"), r.get("make"), r.get("model")))
    cl, src = specs.best_clearance(r.get("make", ""), r.get("model", ""), f'{r.get("trim", "")} {extra}', r.get("year"), page)
    # the body type (from the VIN) tells an "EQE 350" SUV from the sedan when the dealer doesn't say
    er = specs.ev_range(r.get("make", ""), r.get("model", ""), f'{r.get("trim", "")} {extra}', r.get("year"), r.get("fuel_type", ""))
    pf = specs.perf(r.get("make", ""), r.get("model", ""), f'{r.get("trim", "")} {extra}', r.get("year"), r.get("drivetrain", ""),
                    r.get("fuel_type", ""))
    return {"clearance": cl if cl else "", "clearance_src": src, "ev_range": er[0] if er else "", "ev_range_src": "EPA" if er and "fueleconomy" in er[1].lower() else "",
            "perf": pf}


def _places(cars: list[dict], P) -> dict:
    """Map tab: where each dealer with a car on the page is (data/dealers.csv), plus home. Dealers without a street
    address on file were placed at their city's center when the list was built: their pins are marked approximate."""
    import csv
    path = ROOT / "data" / "dealers.csv"
    by = {}
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            by = {r["dealer_name"]: r for r in csv.DictReader(f)}
    out = {}
    for name in {c["dealer"] for c in cars}:
        d = by.get(name) or {}
        try:
            lat, lon = float(d.get("lat") or ""), float(d.get("lon") or "")
        except ValueError:
            continue
        out[name] = {"lat": lat, "lon": lon, "city": d.get("city", ""), "address": d.get("address", ""),
                     "zip": d.get("zip", ""), "approx": not d.get("address")}
    home = P.cfg.get("home") or CONFIG.get("home") or {}
    return {"dealers": out, "home": {"lat": home.get("lat"), "lon": home.get("lon"), "zip": home.get("zip", "")}}


def write_dashboard(rows: list[dict], history: list[dict], cov: list[dict], today: str | None = None, profile=None) -> Path:
    from core import criteria, profiles
    P = _profile(profile)
    today = today or date.today().isoformat()
    active = [r for r in rows if r.get("status") == "active"]
    hist: dict[str, list] = {}
    for h in history:
        hist.setdefault(h["vin"], []).append([h["date"], float(h["price"])])
    latest_run = max((r.get("seen_run") or "" for r in rows), default="")
    from core import history as history_mod      # (the `history` argument is the price history)
    conf = history_mod.load_confirmed(P.data)
    no_audio = {v for v, c in conf.items() if (c.get("audio") or "").strip().lower() == "none"}
    stickers = {v for v, c in conf.items() if (c.get("sticker") or "").strip().lower() == "yes"}   # original window sticker seen
    cars = []
    # the dealers' spec-data clearance for each year / make / model, so every car of it shows the same figure
    from collections import Counter
    seen: dict = {}
    for r in rows:
        if r.get("ground_clearance_in"):
            seen.setdefault((str(r.get("year")), r.get("make"), r.get("model")), Counter())[str(r["ground_clearance_in"])] += 1
    page_cl = {k: c.most_common(1)[0][0] for k, c in seen.items()}
    txt = lambda v: str(v) if isinstance(v, bool) else ("" if v is None else v)   # a fresh run's rows hold real True/False
    active = [{k: txt(v) for k, v in r.items()} for r in active]
    rows = [{k: txt(v) for k, v in r.items()} for r in rows]
    for r in active:
        cars.append({k: r.get(k, "") for k in ("vin", "dealer", "listing_url", "year", "make", "model", "trim", "price_total",
                                               "mileage", "ext_color", "int_color", "fuel_type", "sunroof", "audio",
                                               "carfax_status", "est_monthly_cost", "score", "needs_call", "notes",
                                               "mpg_combined", "mpg_city", "mpg_hwy", "mpg_source",
                                               "cpo_program", "first_seen", "distance_mi", "fees_estimated", "seats",
                                               "msrp_new", "msrp_source", "body", "page_features", "drivetrain",
                                               "ventilated_seats", "spare_tire", "leather", "recall_flags", "carfax_badges",
                                               "cpo_warranty_terms", "packages", "price", "last_seen")}
                    | {"hist": hist.get(r["vin"], []), "audio_none": r["vin"].upper() in no_audio, "sticker": r["vin"].upper() in stickers,
                       "is_new": bool(latest_run) and r.get("new_run") == latest_run,
                       "score_parts": criteria.score_breakdown(r) if r.get("score") not in ("", None) else []}
                    | _spec_fields(r, page_cl))
    ok = sum(c["status"] == "success" for c in cov)
    failed = [c for c in cov if c["status"] == "failed"]
    skipped = sum(c["status"] == "skipped" for c in cov)
    # cars that were on the dashboard (active) and have since sold / been removed by the dealer
    gone = []
    for r in rows:
        if r.get("status") == "sold":
            gone.append({k: r.get(k, "") for k in ("vin", "dealer", "listing_url", "year", "make", "model", "trim",
                                                   "price_total", "mileage", "ext_color", "int_color", "fuel_type",
                                                   "mpg_combined", "needs_call", "first_seen", "last_seen",
                                                   "removed_on", "fail_reasons", "distance_mi", "body", "drivetrain")}
                        | {"hist": hist.get(r["vin"], [])})
    gfile = ROOT / P.cfg["trim_guide"] if P.cfg.get("trim_guide") else TRIM_GUIDE
    guide = json.loads(gfile.read_text(encoding="utf-8")) if gfile.exists() else {"models": []}
    warranty = json.loads(WARRANTY.read_text(encoding="utf-8")) if WARRANTY.exists() else {"brands": []}
    makes = {m.lower() for m in P.models()}          # warranty table: only the brands this buyer looks at
    warranty = {"brands": [b for b in warranty.get("brands", []) if b.get("make", "").lower() in makes]}
    people = [{"id": q.id, "label": q.label, "href": q.href,
               "local": ("" if P.is_default else "../") + ("dashboard.html" if q.is_default else f"{q.id}/dashboard.html")}
              for q in profiles.all_profiles()]
    data = json.dumps({"cars": cars, "gone": gone, "places": _places(cars, P), "failed": failed, "guide": guide, "warranty": warranty, "check": check_list(cov, P),
                       "profile": {"id": P.id, "label": P.label, "default": P.is_default}, "people": people,
                       "miles_per_year": P.cfg.get("warranty", {}).get("miles_per_year", 12000)}, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", data).replace("__DATE__", html.escape(today)) \
        .replace("__OK__", str(ok)).replace("__FAILED__", str(len(failed))).replace("__SKIPPED__", str(skipped)) \
        .replace("__MATCHES__", str(sum(1 for c in cars if not c["needs_call"]))) \
        .replace("__CALLS__", str(sum(1 for c in cars if c["needs_call"]))) \
        .replace("__NAVAIL__", str(len(cars))) \
        .replace("__MPY__", f'{P.cfg.get("warranty", {}).get("miles_per_year", 12000):,}').replace("__NGONE__", str(len(gone))) \
        .replace("__TITLE__", f"{html.escape(P.label)}'s CPO SUV Finder").replace("__SCOREHELP__", score_help(P))
    for k, v in theme_vars(P).items():
        page = page.replace(k, v)
    if len(profiles.all_profiles()) < 2:        # nobody to switch to
        page = page.replace('<a class="switch" id="switch" href="/">&#8592; Ross or Jenna</a>', "")
    P.out.mkdir(parents=True, exist_ok=True)
    path = P.out / "dashboard.html"
    path.write_text(page, encoding="utf-8")
    if len(profiles.all_profiles()) > 1:
        write_chooser(today)
    else:                                       # one buyer: no "whose search?" start page
        (profiles.OUT / "index.html").unlink(missing_ok=True)
    return path


def write_chooser(today: str = "") -> Path:
    """The start page: pick whose search to see. Each buyer's tracker is separate, in its own color."""
    from core import history, profiles
    cards = []
    for q in profiles.all_profiles():
        rows = [r for r in history.read_csv(q.data / "listings.csv") if r.get("status") == "active"]
        n_ok, n_call = sum(1 for r in rows if not r.get("needs_call")), sum(1 for r in rows if r.get("needs_call"))
        th = theme_vars(q)
        local = "dashboard.html" if q.is_default else f"{q.id}/dashboard.html"
        cards.append(f'<a class="who" data-local="{local}" href="{q.href}" style="--a:{th["__ACC_L__"]};--ad:{th["__ACC_D__"]}">'
                     f'<b>{html.escape(q.label)}</b><span>{n_ok} meet all criteria · {n_call} need a call</span></a>')
    page = CHOOSER.replace("__CARDS__", "\n".join(cards)).replace("__DATE__", html.escape(today))
    path = profiles.OUT / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


CHOOSER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CPO SUV Finder</title>
<style>
:root { --bg:#f6f6f5; --fg:#1d211f; --muted:#5f6862; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root { --bg:#111312; --fg:#e5e9e6; --muted:#9aa49e; color-scheme: dark; } }
body { margin:0; min-height:100vh; background:var(--bg); color:var(--fg); font:16px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
  display:grid; place-items:center; padding:24px 16px; box-sizing:border-box; }
main { width:100%; max-width:520px; display:grid; gap:16px; }
h1 { margin:0; font-size:26px; } p { margin:0; color:var(--muted); }
.who { display:grid; gap:4px; text-decoration:none; color:#fff; background:var(--a); border-radius:14px; padding:22px 20px; }
.who b { font-size:28px; } .who span { font-size:15px; opacity:.92; } .who small { font-size:12px; opacity:.75; }
.who:focus-visible { outline:3px solid var(--fg); outline-offset:3px; }
</style></head><body><main>
<h1>CPO SUV Finder</h1><p>Whose search do you want to see?</p>
__CARDS__
<p style="font-size:13px">Last search __DATE__</p>
</main>
<script>
if (location.protocol === "file:") document.querySelectorAll("a.who").forEach(a => a.href = a.dataset.local);
</script>
</body></html>
"""


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { --bg:__BG_L__; --surface:#fff; --fg:#1d211f; --muted:#5f6862; --line:__LINE_L__; --accent:__ACC_L__; --on-accent:#fff;
  --ok:#1f7a4d; --ok-bg:#e2f2e9; --warn:#7a5a00; --warn-bg:#fbf1d6; --bad:#a3361f; --bad-bg:#f7e4df; --checked:#e6e8e6; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:__BG_D__; --surface:__SURF_D__; --fg:#e5e9e6; --muted:#9aa49e; --line:__LINE_D__;
  --accent:__ACC_D__; --on-accent:#0d1110; --ok:#7fd4a6; --ok-bg:#173226; --warn:#e8c766; --warn-bg:#33290f; --bad:#f0a08c; --bad-bg:#3a1f19; --checked:#2b302d; color-scheme: dark; } }
:root[data-theme="dark"] { --bg:__BG_D__; --surface:__SURF_D__; --fg:#e5e9e6; --muted:#9aa49e; --line:__LINE_D__;
  --accent:__ACC_D__; --on-accent:#0d1110; --ok:#7fd4a6; --ok-bg:#173226; --warn:#e8c766; --warn-bg:#33290f; --bad:#f0a08c; --bad-bg:#3a1f19; --checked:#2b302d; color-scheme: dark; }
[hidden] { display:none !important; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; padding-block:20px; padding-left:max(16px, env(safe-area-inset-left, 0px)); padding-right:max(16px, env(safe-area-inset-right, 0px)); }
main { max-width:1200px; margin:0 auto; display:grid; gap:18px; }
main > * { min-width:0; }  /* wide tables scroll inside .wrap instead of widening the page */
h1 { margin:0; font-size:26px; letter-spacing:-.01em; }
.hero { background:__ACC_L__; color:#fff; border-radius:12px; padding:14px 16px; }   /* the buyer's deep color, light or dark mode */
.hero h1 { color:#fff; } .hero .sub { opacity:.85; } .hero a { color:#fff; }
.hero .switch { display:inline-block; font-size:13px; font-weight:600; opacity:.9; margin-bottom:6px; text-decoration:none;
  border:1px solid currentColor; border-radius:999px; padding:2px 10px; } .muted { color:var(--muted); }
.tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(140px,1fr)); gap:10px; }
.tile { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
.tile b { display:block; font-size:24px; font-variant-numeric:tabular-nums; }
.tilebtn { font:inherit; color:inherit; text-align:left; cursor:pointer; }
.tilebtn b { color:var(--ok); }
.tilebtn[aria-pressed=true] { outline:2px solid var(--ok); }
.cutline { color:var(--ok); font-size:12px; font-weight:600; white-space:nowrap; }
details { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
details li { margin:3px 0; }
.controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
input, select { font:inherit; padding:6px 8px; border:1px solid var(--line); border-radius:6px; background:var(--surface); color:var(--fg); }
.filters { display:grid; gap:8px; }
.tabs { display:flex; gap:4px; border-bottom:1px solid var(--line); }
.tab { font:inherit; font-weight:600; background:none; border:0; border-bottom:3px solid transparent; color:var(--muted);
  padding:8px 12px; cursor:pointer; margin-bottom:-1px; }
.tab[aria-selected="true"] { color:var(--fg); border-bottom-color:var(--accent); }
.tab:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.tab .sh { display:none; }
.tab .n { font-weight:500; color:var(--muted); margin-left:4px; }
.gone td.car a { color:var(--muted); }
.group { display:flex; flex-wrap:wrap; gap:6px; align-items:center; border:0; margin:0; padding:0; }
.range { flex:1 1 240px; min-width:0; max-width:460px; box-sizing:border-box; padding:0; }
.rvs { margin-left:6px; text-transform:none; letter-spacing:0; color:var(--fg); white-space:nowrap; }
.rvs .rv { font-variant-numeric:tabular-nums; }
/* one track, two handles: two range inputs stacked; only their handles take touches */
.track { position:relative; height:32px; min-width:0; --a:0; --b:1; }
.track::before, .track::after { content:""; position:absolute; top:50%; height:4px; margin-top:-2px; border-radius:2px; }
.track::before { left:12px; right:12px; background:var(--line); }
.track::after { left:calc(12px + (100% - 24px) * var(--a)); right:calc(12px + (100% - 24px) * (1 - var(--b))); background:var(--accent); }   /* 12px = half a handle */
.track input[type=range] { position:absolute; inset:0; width:100%; height:100%; margin:0; padding:0; border:0; border-radius:0; box-sizing:border-box;
  background:none; box-shadow:none; outline:none; pointer-events:none;
  -webkit-appearance:none; appearance:none; z-index:1; }
.track input[type=range]::-webkit-slider-runnable-track { background:none; border:0; height:32px; }
.track input[type=range]::-moz-range-track { background:none; border:0; }
.track input[type=range]::-webkit-slider-thumb { -webkit-appearance:none; pointer-events:auto; width:24px; height:24px; margin-top:4px;
  border-radius:50%; background:var(--surface); border:3px solid var(--accent); cursor:pointer; box-sizing:border-box; }
.track input[type=range]::-moz-range-thumb { pointer-events:auto; width:24px; height:24px; border-radius:50%; background:var(--surface);
  border:3px solid var(--accent); cursor:pointer; box-sizing:border-box; }
.track input[type=range]:focus-visible::-webkit-slider-thumb { outline:2px solid var(--accent); outline-offset:2px; }
#f-price legend, #f-miles legend, #f-clear legend, #f-erange legend { width:100%; }   /* slider rows: label on its own line */
.layout { display:grid; grid-template-columns:minmax(0,1fr); gap:18px; min-width:0; } .layout > * { min-width:0; }
.content { display:grid; grid-template-columns:minmax(0,1fr); gap:18px; min-width:0; } .content > * { min-width:0; }
.fsec { padding:0; border:0; background:none; }
.fsec > summary { font-size:13px; font-weight:700; cursor:pointer; padding:6px 0; color:var(--fg); }
.fsec > .group { margin:2px 0 8px; }
.hint { display:block; text-transform:none; letter-spacing:0; font-size:12px; }
/* desktop: the filters live in a panel on the left that stays in view while the list scrolls */
@media (min-width: 1100px) {
  main { max-width:1560px; }
  .layout { grid-template-columns:290px minmax(0,1fr); align-items:start; }
  .layout:has(> .filters[hidden]) { grid-template-columns:minmax(0,1fr); }
  .filters { position:sticky; top:12px; max-height:calc(100vh - 24px); overflow:auto; background:var(--surface);
    border:1px solid var(--line); border-radius:10px; padding:12px 14px; gap:4px; align-content:start; }
  .filters .controls input { flex:1 1 100%; } .filters .controls .clear { margin-left:auto; }
  .fsec { border-top:1px solid var(--line); padding-top:4px; }
  .fsec .group legend { float:none; display:block; width:100%; margin:0 0 4px; }
  .range { max-width:none; flex-basis:100%; }
  .pill > span { font-size:13px; padding:3px 9px; }
  td.car { min-width:230px; }
}
.group legend { float:left; font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin-right:6px; padding:0; min-width:56px; }
.pill { position:relative; }
.pill input { position:absolute; opacity:0; width:1px; height:1px; }
.pill > span { display:inline-block; padding:4px 11px; border:1px solid var(--line); border-radius:999px; background:var(--surface);
  font-size:14px; cursor:pointer; user-select:none; }
.pill input:checked + span { background:var(--accent); border-color:var(--accent); color:var(--bg); }
.pill input:focus-visible + span { outline:2px solid var(--accent); outline-offset:2px; }
.clear { font:inherit; font-size:13px; background:none; border:0; color:var(--accent); cursor:pointer; text-decoration:underline; padding:4px; }
.wrap { overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:8px; }
table { border-collapse:collapse; width:100%; min-width:900px; }
th { text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); padding:9px 10px;
  border-bottom:1px solid var(--line); cursor:pointer; white-space:nowrap; user-select:none; }
/* header row stays on screen while scrolling the table (moved by stickHeads() in the script) */
thead th { position:relative; z-index:3; background:var(--surface); will-change:transform; }
thead.stuck th { box-shadow:0 1px 0 var(--line), 0 6px 10px -8px rgba(0,0,0,.35); }
#safe-top { position:fixed; top:0; height:env(safe-area-inset-top, 0px); width:0; visibility:hidden; }
th:hover { color:var(--fg); } td { padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
td.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
a { color:var(--accent); } .car a { font-weight:600; color:var(--fg); text-decoration:none; } .car a:hover { color:var(--accent); text-decoration:underline; }
.vin { font:12px ui-monospace, Menlo, Consolas, monospace; color:var(--muted); }
.chip { display:inline-block; font-size:12px; font-weight:600; padding:1px 7px; border-radius:999px; white-space:nowrap; }
.match { background:var(--ok-bg); color:var(--ok); } .call { background:var(--warn-bg); color:var(--warn); }
.clean { color:var(--ok); } .accident { color:var(--bad); } .small { font-size:12px; color:var(--muted); }
#drive { position:fixed; left:0; top:0; width:100%; height:150px; pointer-events:none; z-index:50; }
#drive canvas { position:absolute; inset:0; width:100%; height:100%; }
#drive .car { position:absolute; left:0; top:44px; width:150px; height:64px; will-change:transform; color:var(--accent); }
#drive .wheel { transform-box:fill-box; transform-origin:center; animation:spin .35s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { #drive { display:none; } }
.newchip { display:inline-block; font-size:11px; font-weight:800; letter-spacing:.06em; padding:1px 7px;
  border-radius:999px; background:var(--accent); color:var(--bg); vertical-align:2px; margin-left:6px; }
.drop { color:var(--ok); font-weight:900; margin-right:3px; }
.orig { white-space:nowrap; font-variant-numeric:tabular-nums; }
.save { color:var(--ok); font-size:12px; font-weight:600; }
.sortbar { display:flex; gap:8px; align-items:center; margin-bottom:10px; }
.shown { margin:4px 0 8px; font-weight:600; }
.mapbar { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:0 0 10px; }
#map { height:min(65vh, 560px, 125vw); border-radius:10px; border:1px solid var(--line); margin-bottom:8px; z-index:0; }
.maplegend { display:flex; gap:6px 14px; align-items:center; flex-wrap:wrap; margin-bottom:4px; }
.maplegend > span { display:inline-flex; gap:5px; align-items:center; }
.pin { display:inline-flex; align-items:center; justify-content:center; min-width:26px; height:26px; padding:0 5px; box-sizing:border-box;
  border-radius:13px; color:#fff; font:700 13px/1 system-ui, sans-serif; border:2px solid #fff; box-shadow:0 1px 4px rgba(0,0,0,.45); }
.pin.m { background:#1f8a3b; } .pin.c { background:#b7791f; } .pin.home { background:#2b4c7e; }
.pin.approx { border-style:dashed; } .pin.fav::after { content:"\2665"; margin-left:2px; font-size:11px; }
.pin.trip { outline:3px solid #2b6cb0; }
.leaflet-div-icon.pinwrap { background:none; border:0; }
.mpop { font:13px/1.35 system-ui, sans-serif; max-width:270px; }
.mpop h4 { margin:0 0 2px; font-size:14px; } .mpop ul { margin:6px 0; padding-left:16px; } .mpop li { margin:2px 0; }
.mpop .acts { display:flex; gap:6px; flex-wrap:wrap; margin-top:6px; }
.mpop button, #trip button { font:inherit; cursor:pointer; }
#trip ol { margin:6px 0; padding-left:22px; } #trip li { margin:3px 0; }
#trip .x { border:0; background:none; color:var(--muted); font-size:16px; padding:0 6px; }
.shown .clear { margin-left:8px; font-weight:400; }
#shown-f { margin-left:8px; }
.sortbar label { font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
.sortbar select { flex:1; min-width:0; max-width:380px; }
.phone-only { display:none; }
/* "Back to top" button: appears after scrolling down */
#totop { position:fixed; z-index:40; right:max(16px, env(safe-area-inset-right, 0px));
  bottom:max(16px, calc(env(safe-area-inset-bottom, 0px) + 8px)); width:48px; height:48px; border-radius:50%;
  border:1px solid var(--line); background:var(--accent); color:var(--bg); font-size:22px; line-height:1; cursor:pointer;
  box-shadow:0 4px 14px rgba(0,0,0,.25); opacity:0; transform:translateY(12px); pointer-events:none;
  transition:opacity .2s, transform .2s; }
#totop.show { opacity:1; transform:none; pointer-events:auto; }
#totop:focus-visible { outline:3px solid var(--fg); outline-offset:2px; }
@media (prefers-reduced-motion: reduce) { #totop { transition:none; } }
/* Trim guide tab */
.gmodel { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:14px; margin-bottom:14px; scroll-margin-top:12px; }
.gmodel h2 { margin:0; font-size:20px; } .gmodel .rule { margin:2px 0 10px; }
.years { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:8px; }
.years button { font:inherit; font-size:14px; padding:4px 12px; border:1px solid var(--line); border-radius:999px; background:var(--surface); color:var(--fg); cursor:pointer; }
.years button[aria-pressed="true"] { background:var(--accent); border-color:var(--accent); color:var(--bg); }
.changed { margin:0 0 10px; }
.trims { display:grid; grid-template-columns:repeat(auto-fill, minmax(270px, 1fr)); gap:10px; }
.trim { border:1px solid var(--line); border-radius:8px; padding:10px 12px; background:var(--bg); }
.trim.off { opacity:.7; }
.trim h3 { margin:0 0 4px; font-size:16px; }
.trim dl { display:grid; grid-template-columns:auto 1fr; gap:2px 10px; margin:8px 0; font-size:13px; }
.trim dt { color:var(--muted); } .trim dd { margin:0; }
.trim ul { margin:4px 0 0; padding-left:18px; font-size:14px; } .trim li { margin:2px 0; }
.off-chip { background:var(--bad-bg); color:var(--bad); }
.gtools { display:grid; gap:8px; margin-bottom:12px; }
.src { font-size:12px; color:var(--muted); margin-top:8px; overflow-wrap:anywhere; }
.glink { font:600 12px system-ui, -apple-system, sans-serif; margin-left:6px; }
/* Check yourself tab */
.ck { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:12px; margin-bottom:10px; }
.ck h3 { margin:0; font-size:16px; } .ck .why { margin:2px 0 8px; }
.ck .btns { display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
.ck a.cbtn { text-decoration:none; display:inline-block; }
.ck.done { border-color:var(--ok); background:var(--checked); } .ck.stale { border-color:var(--warn); }  /* checked in the last 7 days = gray fill */
.ckstate { font-size:12px; font-weight:600; margin-left:4px; } .ck.done .ckstate { color:var(--ok); } .ck.stale .ckstate { color:var(--warn); }
.ckgroup { margin:14px 0; background:none; border:0; padding:0; } .ckgroup[open] > summary { margin-bottom:8px; }
.ckbrand { font-size:14px; color:var(--muted); cursor:pointer; padding:8px 10px; background:var(--surface); border:1px solid var(--line); border-radius:8px; }
.ckbrand b { color:var(--fg); font-size:16px; }
/* Compare tab */
.cmpbtn { font:600 12px system-ui, -apple-system, sans-serif; margin-top:6px; padding:3px 10px; border-radius:999px; cursor:pointer;
  border:1px solid var(--accent); background:var(--surface); color:var(--accent); }
.cmpbtn[aria-pressed="true"] { background:var(--accent); color:var(--bg); }
.favbtn { font:600 12px system-ui, -apple-system, sans-serif; margin:6px 6px 0 0; padding:3px 10px; border-radius:999px; cursor:pointer;
  border:1px solid var(--bad); background:var(--surface); color:var(--bad); }
.favbtn[aria-pressed="true"] { background:var(--bad); color:var(--bg); border-color:var(--bad); }
.disbtn { font:600 12px system-ui, -apple-system, sans-serif; margin:6px 6px 0 0; padding:3px 10px; border-radius:999px; cursor:pointer;
  background:transparent; color:var(--muted); border:1px solid var(--line); }
.disbtn[aria-pressed="true"] { background:var(--muted); color:var(--bg); border-color:var(--muted); }
tr.disliked > td { opacity:.5; }
tr.disliked > td.car { opacity:.8; }
td.car { position:relative; }
td.car.has-sticker { padding-right:34px; }
.stickerok { position:absolute; top:8px; right:6px; width:22px; height:22px; border-radius:50%; background:#1f8a3b; color:#fff;
  display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:900; line-height:1; box-shadow:0 0 0 2px var(--surface);
  border:0; padding:0; cursor:pointer; font-family:inherit; }
/* its label: on hover (laptop) or after a tap (iPad / phone); a tap anywhere else closes it */
.stickerok::after { content:attr(data-tip); position:absolute; top:calc(100% + 6px); right:0; white-space:nowrap; z-index:5;
  background:var(--fg); color:var(--bg); font-size:12px; font-weight:600; padding:5px 8px; border-radius:6px;
  opacity:0; pointer-events:none; transition:opacity .12s; }
.stickerok:hover::after, .stickerok.open::after, .stickerok:focus-visible::after { opacity:1; }
#fav-gone ul { margin:4px 0 12px; padding-left:18px; }
.cmpbar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; background:var(--surface); border:1px solid var(--accent);
  border-radius:8px; padding:8px 10px; font-size:14px; }
.cmpbar[hidden] { display:none; }
.cbtn { font:600 13px system-ui, -apple-system, sans-serif; padding:6px 12px; border-radius:999px; cursor:pointer;
  border:1px solid var(--accent); background:var(--accent); color:var(--bg); }
.cbtn.ghost { background:var(--surface); color:var(--accent); }
.cmptop { display:flex; flex-wrap:wrap; gap:8px; align-items:center; justify-content:space-between; margin-bottom:10px; }
.cmp { background:var(--surface); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
.crow { display:grid; grid-template-columns:150px repeat(var(--n), minmax(0,1fr)); border-bottom:1px solid var(--line); }
.crow:last-child { border-bottom:0; } .crow > div { padding:8px 10px; min-width:0; overflow-wrap:anywhere; font-size:14px; }
.crow .clabel { font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
.crow.chead > div { font-weight:600; } .crow.chead .rm { font:inherit; font-size:12px; background:none; border:0; color:var(--accent); cursor:pointer; padding:0; text-decoration:underline; }
.cval.best { color:var(--ok); font-weight:700; } .cval.best > div::after { content:" ★"; font-size:12px; }
.crow.csec { display:block; background:var(--bg); } .crow.csec > div { font-weight:700; font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--accent); padding:10px 10px 6px; }
.sbar { display:grid; grid-template-columns:minmax(0,1fr) 60px 44px; gap:6px; align-items:center; font-size:12px; line-height:1.6; }
.sbar .sb { height:6px; background:var(--line); border-radius:3px; overflow:hidden; } .sbar .sb i { display:block; height:100%; background:var(--accent); }
.sbar b { text-align:right; font-weight:600; } .cval ul.hl { margin:2px 0 0; padding-left:16px; font-size:13px; }
.cl { display:inline-block; min-width:20px; text-align:center; font-size:12px; font-weight:800; line-height:20px; border-radius:999px; background:var(--kc, var(--accent)); color:#fff; padding:0 5px; margin-right:6px; }
/* one colour per compared car (A-F), the same in the header and on every value line */
.k0 { --kc:#1f6feb; } .k1 { --kc:#d9480f; } .k2 { --kc:#2f9e44; } .k3 { --kc:#9c36b5; } .k4 { --kc:#c2255c; } .k5 { --kc:#0c8599; }
.crow.chead > div.ch { border-top:4px solid var(--kc); }
.cval .ctag { display:none; }
@media (max-width: 760px) {
  .crow { grid-template-columns:1fr; } .crow > div { padding:3px 12px; } .crow .clabel { padding-top:10px; }
  .crow:not(.chead) .cval { display:grid; grid-template-columns:104px minmax(0,1fr); gap:8px; align-items:start; padding:6px 12px 6px 9px;
    border-left:4px solid var(--kc); margin:3px 0; }
  .crow:not(.chead) .cval:nth-child(odd) { background:color-mix(in srgb, var(--kc) 6%, transparent); }
  .cval .ctag { display:flex; align-items:flex-start; gap:0; min-width:0; }
  .cval .ctag .cl { flex:none; } .cval .cn { font-size:12px; font-weight:600; color:var(--kc); line-height:1.3; padding-top:2px; overflow-wrap:anywhere; }
  .cval.best .ctag { font-weight:600; }
  .crow.chead > div.ch { border-top:0; border-left:4px solid var(--kc); margin:3px 0; }
  .tabs { flex-wrap:wrap; } .tab { padding:8px 8px; } .tab .lg { display:none; } .tab .sh { display:inline; }
  .crow.chead > div.clabel { display:none; } .crow.chead > div { padding:8px 12px; border-top:1px solid var(--line); }
  .crow > div:last-child { padding-bottom:10px; }
}
.yby { margin:0 0 10px; font-size:14px; } .yby summary { cursor:pointer; color:var(--accent); font-weight:600; }
.yby ul { margin:6px 0 0; padding-left:18px; } .yby li { margin:4px 0; }
.wcards { display:grid; grid-template-columns:repeat(auto-fill, minmax(270px, 1fr)); gap:10px; margin-top:8px; }
.wcard { border:1px solid var(--line); border-radius:8px; padding:10px 12px; background:var(--bg); font-size:14px; }
.wcard h3 { margin:0 0 4px; font-size:16px; } .wcard ul { margin:4px 0; padding-left:18px; } .wcard li { margin:2px 0; }
.wline { white-space:normal; } .wline + .wline { margin-top:3px; } .wexp { color:var(--muted); text-decoration:line-through; }
td.warr { min-width:190px; font-size:13px; }
/* Phones: each car becomes a card, so nothing needs sideways scrolling */
@media (max-width: 760px) {
  .phone-only { display:flex; } .sortbar select { max-width:none; }
  .wrap { overflow:visible; background:none; border:0; border-radius:0; }
  table, tbody { display:block; min-width:0; width:auto; }
  thead { display:none; }
  tbody tr { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:10px 12px; background:var(--surface);
    border:1px solid var(--line); border-radius:10px; padding:12px; margin-bottom:12px; }
  td { display:block; padding:0; border:0; min-width:0; overflow-wrap:anywhere; }
  td.num { text-align:left; white-space:normal; }
  td[data-l]::before { content:attr(data-l); display:block; font-size:11px; text-transform:uppercase; letter-spacing:.05em;
    color:var(--muted); margin-bottom:1px; }
  td.car { grid-column:1 / -1; order:-3; font-size:16px; } td.car::before { display:none !important; }
  td.wide { grid-column:1 / -1; } td.span2 { grid-column:span 2; }
  td.p-score { order:-2; } td.p-year { order:-1; } td.p-price { order:-2; font-size:17px; font-weight:700; } td.p-mo { order:-2; }
  td[colspan] { grid-column:1 / -1; }
  tbody tr:has(td[colspan]) { display:block; }
}
</style></head><body><main>
<div id="safe-top" aria-hidden="true"></div>
<button type="button" id="totop" aria-label="Back to top" title="Back to top">&#8593;</button>
<header class="hero"><a class="switch" id="switch" href="/">&#8592; Ross or Jenna</a><h1>__TITLE__</h1><div class="sub">Refreshed __DATE__ · every car links to the dealer's own listing</div></header>
<div class="tiles">
  <div class="tile"><b>__MATCHES__</b><span class="muted">meet all criteria</span></div>
  <div class="tile"><b>__CALLS__</b><span class="muted">need a call</span></div>
  <div class="tile"><b>__OK__</b><span class="muted">sources read</span></div>
  <div class="tile"><b>__FAILED__</b><span class="muted">sources failed</span></div>
  <div class="tile"><b>__SKIPPED__</b><span class="muted">covered by brand feeds</span></div>
  <button type="button" class="tile tilebtn" id="cut-tile"><b id="ncut-tile">0</b><span class="muted">price cuts &#9660; (tap to see)</span></button>
</div>
__SCOREHELP__
<details id="cov"><summary><b>Coverage:</b> <span id="covsum"></span></summary><ul id="covlist"></ul></details>
<div class="tabs" role="tablist">
  <button class="tab" role="tab" id="tab-avail" aria-selected="true" aria-controls="panel-avail"><span class="lg">Available</span><span class="sh">Cars</span><span class="n">__NAVAIL__</span></button>
  <button class="tab" role="tab" id="tab-fav" aria-selected="false" aria-controls="panel-avail">&#9829; <span class="lg">Favorites</span><span class="n" id="nfav">0</span></button>
  <button class="tab" role="tab" id="tab-cmp" aria-selected="false" aria-controls="panel-cmp">Compare<span class="n" id="ncmp">0</span></button>
  <button class="tab" role="tab" id="tab-guide" aria-selected="false" aria-controls="panel-guide"><span class="lg">Trim guide</span><span class="sh">Trims</span></button>
  <button class="tab" role="tab" id="tab-check" aria-selected="false" aria-controls="panel-check"><span class="lg">Check yourself</span><span class="sh">Check</span><span class="n" id="ncheck">0</span></button>
  <button class="tab" role="tab" id="tab-gone" aria-selected="false" aria-controls="panel-gone"><span class="lg">No longer available</span><span class="sh">Sold</span><span class="n">__NGONE__</span></button>
</div>
<div class="layout">
<aside class="filters" aria-label="Filters">
  <div class="cmpbar" id="cmpbar" hidden><span>Comparing <b id="cmpbar-n">0</b> cars</span>
    <button type="button" class="cbtn" id="cmpbar-view">View comparison</button>
    <button type="button" class="cbtn ghost" id="cmpbar-clear">Clear compare</button></div>
  <div class="controls"><input id="q" placeholder="Search: dealer, model, color…" aria-label="Search">
    <button class="clear" id="clear" type="button">Clear filters</button><span class="small" id="shown-f"></span></div>
  <details class="fsec" open><summary>Status &amp; your marks</summary>
    <fieldset class="group" id="f-show"><legend>Status</legend></fieldset>
    <fieldset class="group" id="f-mine"><legend>Your marks</legend></fieldset>
    <fieldset class="group" id="f-new"><legend>Show</legend><label class="pill"><input type="checkbox" id="only-new" value="new"><span>Only NEW (<span id="nnew">0</span>)</span></label><label class="pill"><input type="checkbox" id="only-cut" value="cut"><span>&#9660; Price cut (<span id="ncut">0</span>)</span></label></fieldset>
  </details>
  <details class="fsec" open><summary>The car</summary>
    <fieldset class="group" id="f-make"><legend>Make</legend></fieldset>
    <fieldset class="group" id="f-year"><legend>Model year</legend></fieldset>
    <fieldset class="group" id="f-body"><legend>Body</legend></fieldset>
    <fieldset class="group" id="f-fuel"><legend>Fuel</legend></fieldset>
    <fieldset class="group" id="f-drive"><legend>Drive</legend></fieldset>
  </details>
  <details class="fsec" open><summary>Price &amp; miles</summary>
    <fieldset class="group" id="f-price"><legend>Price (with fees) <span class="rvs"><b class="rv" id="pmin-v"></b> – <b class="rv" id="pmax-v"></b></span></legend>
    <div class="range"><div class="track"><input type="range" id="pmin" aria-label="Lowest price"><input type="range" id="pmax" aria-label="Highest price"></div></div></fieldset>
    <fieldset class="group" id="f-miles"><legend>Miles <span class="rvs"><b class="rv" id="mmin-v"></b> – <b class="rv" id="mmax-v"></b></span></legend>
    <div class="range"><div class="track"><input type="range" id="mmin" aria-label="Fewest miles"><input type="range" id="mmax" aria-label="Most miles"></div></div></fieldset>
  </details>
  <details class="fsec" open><summary>Features</summary>
    <fieldset class="group" id="f-roof"><legend>Sunroof</legend></fieldset>
    <fieldset class="group" id="f-sound"><legend>Upgraded sound</legend></fieldset>
    <fieldset class="group" id="f-seat"><legend>Seats</legend></fieldset>
  </details>
  <details class="fsec" open><summary>Size &amp; range</summary>
    <fieldset class="group" id="f-clear"><legend>Ground clearance <span class="rvs"><b class="rv" id="clmin-v"></b> – <b class="rv" id="clmax-v"></b></span></legend>
    <div class="range"><div class="track"><input type="range" id="clmin" aria-label="Lowest ground clearance"><input type="range" id="clmax" aria-label="Highest ground clearance"></div></div></fieldset>
    <fieldset class="group" id="f-erange"><legend>Electric range <span class="rvs"><b class="rv" id="ermin-v"></b> – <b class="rv" id="ermax-v"></b></span> <span class="hint">plug-ins and electric only; moving it hides gas cars</span></legend>
    <div class="range"><div class="track"><input type="range" id="ermin" aria-label="Shortest electric range"><input type="range" id="ermax" aria-label="Longest electric range"></div></div></fieldset>
  </details>
  <div class="small">Tap to select several; nothing selected in a row means all.</div>
</aside>
<div class="content">
<div id="panel-avail" role="tabpanel" aria-labelledby="tab-avail">
<div id="fav-extra" hidden>
  <p class="muted" style="margin-top:0">Your favorites. Tap <b>&#9825; Save</b> on any car to add it here, tap again to remove it.
  <span id="fav-sync-on" hidden>They sync automatically between your iPhone, iPad and laptop.</span>
  <span id="fav-sync-off">Favorites are kept on this device; to see them on another device, <button type="button" class="clear" id="fav-share">copy a link with your favorites</button> and open it there.</span>
  <button type="button" class="clear" id="fav-cmp">Compare these</button></p>
  <div id="fav-gone"></div>
</div>
<div class="shown" id="shown-a" aria-live="polite"></div>
<div class="mapbar"><button type="button" class="cbtn" id="map-toggle" aria-pressed="false" aria-controls="map-box">&#128506; Show on a map</button>
  <span class="small">the cars these filters show, by dealer</span></div>
<div id="map-box" hidden>
  <div id="map" role="region" aria-label="Map of dealers"></div>
  <div class="small maplegend"><span><span class="pin m">2</span> meet everything</span> <span><span class="pin c">1</span> some need a call</span>
    <span><span class="pin m approx">1</span> dashed: spot approximate</span> <span><span class="pin home">&#8962;</span> home</span></div>
  <div class="small" style="margin-bottom:8px">The number is how many cars there. Tap a pin for its cars, dealers close by, and <b>+ Add to trip</b>.</div>
  <div id="trip"></div>
</div>
<div class="sortbar phone-only"><label for="sort-a">Sort</label><select id="sort-a">
  <option value="score:-1">Best score</option><option value="price_total:1">Lowest price</option>
  <option value="est_monthly_cost:1">Lowest monthly</option><option value="mileage:1">Fewest miles</option>
  <option value="distance_mi:1">Closest dealer</option><option value="first_seen:-1">Newest listing</option>
  <option value="cut:-1">Biggest price cut</option><option value="year:-1">Newest model year</option><option value="mpg_combined:-1">Best MPG</option><option value="clearance:-1">Most ground clearance</option><option value="ev_range:-1">Longest electric range</option><option value="warr_end:-1">Longest warranty (any)</option><option value="warr_full_end:-1">Longest bumper-to-bumper</option></select></div>
<div class="wrap"><table><thead><tr>
  <th data-k="score">Score</th><th data-k="title">Car</th><th data-k="year">Year</th><th data-k="dealer">Dealer</th><th data-k="price_total">Price</th>
  <th data-k="orig">Original price</th><th data-k="msrp">Sticker when new</th><th data-k="mileage">Miles</th><th data-k="fuel">Fuel</th><th data-k="drive">Drive</th><th data-k="mpg_combined">MPG</th><th data-k="colors">Colors</th><th data-k="roof">Sunroof</th><th data-k="snd">Upgraded sound</th><th data-k="seat">Seats</th><th data-k="clearance">Ground clearance</th><th data-k="ev_range">Electric range</th>
  <th data-k="carfax_status">CARFAX</th><th data-k="est_monthly_cost">Est./mo</th><th data-k="warr_end">Warranty</th><th data-k="first_seen">First seen</th>
</tr></thead><tbody id="rows"></tbody></table></div>
</div>
<div id="panel-gone" role="tabpanel" aria-labelledby="tab-gone" hidden>
<div class="shown" id="shown-g" aria-live="polite"></div>
<div class="sortbar phone-only"><label for="sort-g">Sort</label><select id="sort-g">
  <option value="removed_on:-1">Gone most recently</option><option value="price_total:1">Lowest price</option>
  <option value="days:1">Fewest days listed</option><option value="mileage:1">Fewest miles</option></select></div>
<div class="wrap"><table class="gone"><thead><tr>
  <th data-g="title">Car</th><th data-g="year">Year</th><th data-g="dealer">Dealer</th><th data-g="price_total">Last price</th><th data-g="orig">Original price</th>
  <th data-g="mileage">Miles</th><th data-g="fuel">Fuel</th><th data-g="colors">Colors</th><th data-g="first_seen">First seen</th>
  <th data-g="removed_on">Gone since</th><th data-g="days">Days listed</th><th data-g="fail_reasons">Why</th>
</tr></thead><tbody id="gone-rows"></tbody></table></div>
<p class="small">Cars that were on this dashboard and later disappeared from the dealer's site (sold or taken down). The link may no longer work.</p>
</div>
<div id="panel-cmp" role="tabpanel" aria-labelledby="tab-cmp" hidden><div id="cmp"></div></div>
<div id="panel-check" role="tabpanel" aria-labelledby="tab-check" hidden>
<p class="muted" style="margin-top:0">Dealers the search couldn't read by any method, so their cars may be missing from this page.
Tap a model to open that dealer's own <b>certified</b> inventory for it (or <b>All certified inventory</b>).
Have a look, then tap <b>Mark checked</b>. Checks older than a week turn yellow as a reminder. Dealers covered by a brand-wide certified search aren't listed.</p>
<div class="controls" style="margin-bottom:10px"><label class="pill"><input type="checkbox" id="chk-hide"><span>Hide ones I checked this week</span></label>
<button type="button" class="cbtn ghost" id="chk-clear">Clear all checks</button>
<span class="small" id="chk-sync"></span></div>
<div id="checklist"></div>
</div>
<div id="panel-guide" role="tabpanel" aria-labelledby="tab-guide" hidden>
<p class="muted" style="margin-top:0">What each trim includes, by model year, for every model your search looks for.
Trims marked <span class="chip off-chip">not on your list</span> are shown so you can compare. Researched from the
manufacturers' own press sites and brochures; dealers can add options, so check the window sticker.</p>
<div class="gtools">
  <div class="sortbar"><label for="g-jump">Jump to</label><select id="g-jump"><option value="">Choose a model…</option></select></div>
  <fieldset class="group" id="g-make"><legend>Make</legend></fieldset>
  <label class="pill"><input type="checkbox" id="g-only"><span>Only trims on my list</span></label>
</div>
<details class="gmodel" id="g-warranty" open><summary><b>Warranties by brand</b> <span class="small">(new-car and certified pre-owned)</span></summary>
<p class="small">Each car on the Available tab also shows the coverage it has left and when each part is expected to end.
How the end date is estimated: most warranties count from the day the car was first sold new (its "in-service date"). Listings don't
show that, so it's assumed to be about April of the model year (a car can be up to ~9 months either side; ask the dealer for the exact
date). A warranty also ends when the car reaches its mileage limit; that date assumes you drive about __MPY__ miles a year.
The earlier of the two is shown.</p>
<div class="wcards" id="wcards"></div></details>
<div id="guide"></div>
</div>
</div></div>
<p class="small" id="footnote">Price = advertised price + dealer fees (estimated when the page didn't list them), before tax. Monthly = $8,000 down, 60 months at 5.34%, 9.75% tax, $400 gov't fees. MPG = combined (city/hwy below); "EPA" means the listing didn't show it, so it's the official rating from fueleconomy.gov; plug-in hybrids show gas-only MPG.</p>
</main>
<script>
const D = __DATA__;
// Each buyer has their own favorites, compare list and "checked" marks: saved under their own keys here and online.
const PK = D.profile.default ? "" : D.profile.id + ":";
const API = name => "/api/" + name + (D.profile.default ? "" : "?p=" + encodeURIComponent(D.profile.id));
const SEATS = {leather: "leather", synthetic: "synthetic leather", cloth: "cloth"};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
(function chooser() {           // back to the start page, where you pick whose search to see
  const a = document.getElementById("switch"); if (!a) return;
  a.href = location.protocol === "file:" ? (D.profile.default ? "index.html" : "../index.html") : "/";
})();
const num = v => { const n = parseFloat(v); return isNaN(n) ? null : n; };
const FUEL = {gas: "Gas", hybrid: "Hybrid", phev: "Plug-in hybrid", ev: "Electric"};
const fmt$ = v => num(v) == null ? "?" : "$" + Math.round(num(v)).toLocaleString();
const squash = s => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
D.cars.concat(D.gone).forEach(c => {   // "EQB 300" + trim "EQB 300 4MATIC" -> "EQB 300 4MATIC", not the model twice
  if (/^\s*(null|undefined|none|n\/a)\s*$/i.test(c.trim || "")) c.trim = "";      // junk trim from a dealer's data
  const dup = c.model && c.trim && squash(c.trim).startsWith(squash(c.model));
  c.title = [c.year, c.make, dup ? "" : c.model, c.trim].filter(Boolean).join(" ");
  c.colors = [c.ext_color, c.int_color].filter(Boolean).join(" / ");
  c.roof = c.sunroof === "True" ? "Yes" : c.sunroof === "False" ? "No" : "Not sure";
  c.fuel = FUEL[c.fuel_type] || "?";
  // drive: AWD (4WD counts) / RWD / FWD; a VIN that only says "2WD" stays "2WD" (front or rear isn't known)
  c.drive = {AWD: "AWD", "4WD": "AWD", RWD: "RWD", FWD: "FWD", "2WD": "2WD"}[String(c.drivetrain || "").toUpperCase()] || "Not sure"; });
const CUT_MIN = 200;
D.cars.concat(D.gone).forEach(c => {
  c.orig = c.hist && c.hist.length ? c.hist[0][1] : num(c.price_total);
  c.msrp = num(c.msrp_new);
  const now = num(c.price_total);
  // a real cut is $200+: smaller moves are estimated fees changing, or the dealer's real fees replacing the estimate
  c.dropped = c.orig != null && now != null && now <= c.orig - CUT_MIN;
  c.cut = c.dropped ? c.orig - now : null;                       // total cut since first seen (sorts "Biggest price cut")
  const h = c.hist || [];
  for (let i = h.length - 1; i > 0; i--) if (num(h[i][1]) <= num(h[i - 1][1]) - CUT_MIN) {
    c.lastCut = {amt: num(h[i - 1][1]) - num(h[i][1]), on: h[i][0]}; break; }
  c.histTip = (c.hist || []).map(x => x[0] + ": " + fmt$(x[1])).join("\n"); });
D.gone.forEach(c => { const a = Date.parse(c.first_seen), b = Date.parse(c.last_seen);
  c.days = isNaN(a) || isNaN(b) ? "" : Math.round((b - a) / 864e5) + 1; });
const makes = [...new Set(D.cars.concat(D.gone).map(c => c.make))].sort();
// shade the track between the two handles; the low handle goes on top once it's past the middle, so
// both can still be grabbed when they meet
function fillTrack(a, b) {
  const lo = +a.min, span = (+a.max - lo) || 1, t = a.parentElement;
  t.style.setProperty("--a", (+a.value - lo) / span);
  t.style.setProperty("--b", (+b.value - lo) / span);
  a.style.zIndex = +a.value - lo > span / 2 ? 3 : 1; }
const pills = (id, vals) => document.getElementById(id).insertAdjacentHTML("beforeend",
  vals.map(v => `<label class="pill"><input type="checkbox" value="${esc(v)}"><span>${esc(v)}</span></label>`).join(""));
pills("f-show", ["Meets all criteria", "Needs a call"]);
pills("f-make", makes);
pills("f-fuel", ["Gas", "Hybrid", "Plug-in hybrid", "Electric"].filter(f => D.cars.concat(D.gone).some(c => c.fuel === f)));
pills("f-body", ["SUV", "Sedan"]);
pills("f-drive", ["AWD", "RWD", "FWD", "2WD", "Not sure"].filter(v => ["AWD", "RWD", "FWD"].includes(v) || D.cars.some(c => c.drive === v)));
pills("f-roof", ["Yes", "No", "Not sure"]);
pills("f-sound", ["Yes", "No", "Not sure"]);
pills("f-seat", ["Leather", "Synthetic leather", "Cloth", "Not sure"]);
// price sliders: $500 steps between the cheapest and the dearest car on the page
const PRICES = D.cars.map(c => num(c.price_total)).filter(v => v != null);
const P_LO = PRICES.length ? Math.floor(Math.min(...PRICES) / 500) * 500 : 0, P_HI = PRICES.length ? Math.ceil(Math.max(...PRICES) / 500) * 500 : 50000;
const pmin = document.getElementById("pmin"), pmax = document.getElementById("pmax");
[pmin, pmax].forEach(el => { el.min = P_LO; el.max = P_HI; el.step = 500; });
const resetPrice = () => { pmin.value = P_LO; pmax.value = P_HI; showPrice(); };
function showPrice() {
  if (+pmin.value > +pmax.value) { if (document.activeElement === pmin) pmax.value = pmin.value; else pmin.value = pmax.value; }
  document.getElementById("pmin-v").textContent = fmt$(pmin.value);
  document.getElementById("pmax-v").textContent = fmt$(pmax.value); fillTrack(pmin, pmax); }
// mileage sliders: 1,000-mile steps
const MILES = D.cars.map(c => num(c.mileage)).filter(v => v != null);
const M_LO = MILES.length ? Math.floor(Math.min(...MILES) / 1000) * 1000 : 0, M_HI = MILES.length ? Math.ceil(Math.max(...MILES) / 1000) * 1000 : 40000;
const mmin = document.getElementById("mmin"), mmax = document.getElementById("mmax");
[mmin, mmax].forEach(el => { el.min = M_LO; el.max = M_HI; el.step = 1000; });
const fmtMi = v => Math.round(num(v)).toLocaleString() + " mi";
function showMiles() {
  if (+mmin.value > +mmax.value) { if (document.activeElement === mmin) mmax.value = mmin.value; else mmin.value = mmax.value; }
  document.getElementById("mmin-v").textContent = fmtMi(mmin.value);
  document.getElementById("mmax-v").textContent = fmtMi(mmax.value); fillTrack(mmin, mmax); }
const resetMiles = () => { mmin.value = M_LO; mmax.value = M_HI; showMiles(); };
resetPrice(); resetMiles();
// a From / Up to slider (two handles) over one number per car (ground clearance, electric range)
function makeSlider(id, vals, step, fmt) {
  const lo = vals.length ? Math.floor(Math.min(...vals) / step) * step : 0, hi = vals.length ? Math.ceil(Math.max(...vals) / step) * step : step;
  const a = document.getElementById(id + "min"), b = document.getElementById(id + "max");
  [a, b].forEach(el => { el.min = lo; el.max = hi; el.step = step; });
  const show = () => {
    if (+a.value > +b.value) { if (document.activeElement === a) b.value = a.value; else a.value = b.value; }
    document.getElementById(id + "min-v").textContent = fmt(+a.value);
    document.getElementById(id + "max-v").textContent = fmt(+b.value); fillTrack(a, b); };
  const s = {reset() { a.value = lo; b.value = hi; show(); },
             on: () => +a.value > lo + step / 2 || +b.value < hi - step / 2,
             ok: v => v != null && v >= +a.value - step / 2 && v <= +b.value + step / 2};
  [a, b].forEach(el => el.addEventListener("input", () => { show(); render(); }));
  s.reset(); return s;
}
const clearS = makeSlider("cl", D.cars.map(c => num(c.clearance)).filter(v => v != null), 0.1, v => v.toFixed(1) + " in");
const rangeS = makeSlider("er", D.cars.map(c => num(c.ev_range)).filter(v => v != null), 5, v => Math.round(v) + " mi");
pills("f-mine", ["Favorite", "Disliked", "No mark"]);
pills("f-year", [...new Set(D.cars.concat(D.gone).map(c => String(c.year || "")).filter(Boolean))].sort().reverse());
const picked = id => new Set([...document.querySelectorAll(`#${id} input:checked`)].map(i => i.value));
document.getElementById("covsum").textContent = D.failed.length ? `${D.failed.length} sources failed (tap to see why)` : "all sources read";
document.getElementById("covlist").innerHTML = D.failed.map(f => `<li><b>${esc(f.brand)} · ${esc(f.dealer)}</b>: ${esc(f.reason)}</li>`).join("") || "<li>Nothing failed.</li>";
const shortDate = d => { const t = Date.parse(d); return isNaN(t) ? d : new Date(t).toLocaleDateString("en-US", {month: "short", day: "numeric", timeZone: "UTC"}); };
function priceCell(c) {
  if (!c.dropped) return fmt$(c.price_total);
  const last = c.lastCut ? `<div class="cutline">&#9660; ${fmt$(c.lastCut.amt)} on ${esc(shortDate(c.lastCut.on))}</div>` : "";
  return `<span class="drop" title="Price dropped from ${fmt$(c.orig)}" aria-label="price dropped">&#9660;</span>${fmt$(c.price_total)}${last}`;
}
function msrpCell(c) {          // original new-car sticker: the dealer's figure, or "~" = the trim's base price when new (options add to it)
  if (c.msrp == null) return '<span class="muted">?</span>';
  const est = c.msrp_source !== "listing";
  const off = num(c.price_total) != null ? Math.round(100 * (1 - num(c.price_total) / c.msrp)) : null;
  return `<span title="${est ? "Base price of this trim when new (destination included, before options)" : "Original sticker price, from the dealer's page"}">${est ? "~" : ""}${fmt$(c.msrp)}</span>`
    + (off != null && off > 0 ? `<div class="small">${off}% below</div>` : "");
}
function origCell(c) {
  if (c.orig == null) return "?";
  const save = c.dropped ? `<div class="save">${fmt$(c.orig - num(c.price_total))} less now</div>` : "";
  return `<span class="orig" title="${esc(c.histTip)}">${fmt$(c.orig)}</span>${save}`;
}
// ---- Warranty: what coverage a car has left, and when it's expected to end (estimated) ----
const W = {}; ((D.warranty && D.warranty.brands) || []).forEach(b => W[b.make.toLowerCase()] = b);
const NOW = new Date(), MPY = D.miles_per_year || 12000;      // assumed future driving, miles per year
const kmi = n => n == null ? "unlimited miles" : (n >= 1000 ? Math.round(n / 1000) + "k" : n) + " mi";
const addYears = (d, y) => Number.isInteger(y) ? new Date(d.getFullYear() + y, d.getMonth(), d.getDate())
  : new Date(d.getTime() + y * 365.25 * 864e5);
const monthYr = d => d.toLocaleDateString("en-US", {month: "short", year: "numeric"});
// A model-year car is usually first sold between July of the year before and December of its model year;
// the expected in-service date is the middle of that window (about April of the model year).
const inService = my => ({lo: new Date(my - 1, 6, 1), mid: new Date(my, 3, 1), hi: new Date(my, 11, 31)});
// When does one coverage end? The earlier of its time limit and the date the miles run out at MPY a year.
// Coverage that starts later (when the new-car warranty ends, or at purchase) with a small mile allowance
// (e.g. Audi 1 yr/20k) counts those miles from its start; otherwise the miles are an odometer limit.
const additive = cov => /end of new|purchase/i.test(cov.starts || "") && cov.miles != null && cov.miles <= 30000;
function coverEnd(cov, c, start) {
  const mi = num(c.mileage);
  const timeEnd = cov.years != null && start ? addYears(start, cov.years) : null;
  let limit = cov.miles;
  if (limit != null && mi != null && additive(cov)) {
    const ahead = start && start > NOW ? (start - NOW) / (365.25 * 864e5) * MPY : 0;   // miles driven before it starts
    limit = mi + ahead + cov.miles;
  }
  const milesLeft = limit == null || mi == null ? null : Math.round(limit - mi);
  const milesEnd = milesLeft == null ? null : addYears(NOW, Math.max(0, milesLeft) / MPY);
  let end = timeEnd, by = "time";
  if (milesEnd && (!end || milesEnd < end)) { end = milesEnd; by = "miles"; }
  return {end, by, milesLeft, expired: (milesLeft != null && milesLeft <= 0) || (end && end <= NOW)};
}
function coverLine(cov, c, label, start) {
  if (cov.years == null && cov.miles == null) return null;
  const e = coverEnd(cov, c, start);
  const text = `<b>${esc(label)}:</b> ${cov.years ? cov.years + " yr / " : ""}${kmi(cov.miles)}`;
  if (e.expired) return {html: `<div class="wline wexp">${text}</div>`, end: 0, label};
  const when = e.end ? ` · ends ~${monthYr(e.end)}${e.by === "miles" ? ` (at ${kmi(MPY)}/yr)` : ""}` : "";
  const left = e.milesLeft == null ? "" : ` · ${kmi(e.milesLeft)} left`;
  return {html: `<div class="wline">${text}${when}${left}</div>`, end: e.end ? e.end.getTime() : 0, label};
}
function warrantyFor(c) {
  const b = W[String(c.make).toLowerCase()], my = parseInt(c.year);
  if (!b || !my) return {html: '<span class="muted">?</span>', end: 0, fullEnd: 0};
  const ins = inService(my).mid, lines = [];
  const pick = re => (b.factory || []).find(f => re.test(f.name));
  const basic = pick(/basic|bumper|limited warranty|new vehicle/i), pt = pick(/powertrain/i);
  const hy = /hybrid|phev|ev/.test(c.fuel_type || "") ? pick(/hybrid|battery|electric|high.?voltage/i) : null;
  // coverage that "starts when the new-car warranty ends" starts now if that has already happened
  let basicEnd = basic ? coverEnd(basic, c, ins) : null;
  const afterBasic = basicEnd && basicEnd.end && !basicEnd.expired ? basicEnd.end : NOW;
  const startFor = cv => /purchase/i.test(cv.starts || "") ? NOW : /end of new/i.test(cv.starts || "") ? afterBasic : ins;
  const isHy = /hybrid|phev|ev/.test(c.fuel_type || "");
  // repair coverage only (roadside / rust aren't what the buyer compares); battery coverage only on plug-ins/hybrids
  const cpo = ((b.cpo && b.cpo.coverage) || []).filter(cv => !/roadside|corrosion|rust/i.test(cv.name)
    && (isHy || !/battery|high.?voltage|electric/i.test(cv.name)));
  cpo.forEach(cv => lines.push(coverLine(cv, c, "CPO " + cv.name.replace(/\s*\(.*\)/, "").toLowerCase(), startFor(cv))));
  const outdone = f => cpo.some(cv => /powertrain/i.test(cv.name) === /powertrain/i.test(f.name) && /in-service/i.test(cv.starts || "")
    && (cv.years || 0) >= (f.years || 0) && (cv.miles == null || (f.miles != null && cv.miles >= f.miles)));   // CPO already covers it for longer
  [[basic, "Factory basic"], [pt, "Factory powertrain"], [hy, "Hybrid battery"]].forEach(([f, l]) => {
    if (f && !/^no/i.test(f.transfers || "") && !(f !== hy && outdone(f))) lines.push(coverLine(f, c, l, ins)); });
  const ok = lines.filter(Boolean);
  const end = Math.max(0, ...ok.map(l => l.end));
  const fullEnd = Math.max(0, ...ok.filter(l => !/powertrain|battery|hybrid/i.test(l.label)).map(l => l.end));   // bumper-to-bumper type
  const head = end ? `<div class="wline"><b>Longest: ~${monthYr(new Date(end))}</b>${fullEnd ? ` · bumper-to-bumper ~${monthYr(new Date(fullEnd))}` : " · bumper-to-bumper over"}</div>` : "";
  return {html: head + (ok.map(l => l.html).join("") || '<span class="muted">?</span>'), end, fullEnd};
}
D.cars.forEach(c => { const w = warrantyFor(c); c.warr_html = w.html; c.warr_end = w.end; c.warr_full_end = w.fullEnd; });
// one link per site (the first page used from it)
const host = u => String(u).replace(/^https?:\/\/(www\.)?/, "").split("/")[0];
const srcLinks = urls => [...new Map((urls || []).map(u => [host(u), u])).values()]
  .map(u => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(host(u))}</a>`).join(", ");
function renderWarranty() {
  const brands = (D.warranty && D.warranty.brands) || [];
  document.getElementById("g-warranty").hidden = !brands.length;
  const line = f => `<li><b>${esc(f.name)}:</b> ${f.years ? f.years + " yr / " : ""}${kmi(f.miles)}${f.starts ? ", from " + esc(f.starts) : ""}${f.transfers && !/^yes/i.test(f.transfers) ? " (" + esc(f.transfers === "no" ? "first owner only" : f.transfers) + ")" : ""}${f.note ? " · " + esc(f.note) : ""}</li>`;
  document.getElementById("wcards").innerHTML = brands.map(b => `<div class="wcard"><h3>${esc(b.make)}</h3>
    ${b.cpo ? `<div><b>${esc(b.cpo.program)}</b></div><div class="small">${esc(b.cpo.summary || "")}</div><ul>${(b.cpo.coverage || []).map(line).join("")}</ul>
      ${(b.cpo.perks || []).length ? `<div class="small">Also: ${b.cpo.perks.map(esc).join("; ")}</div>` : ""}` : ""}
    <div style="margin-top:6px"><b>New-car warranty</b></div><ul>${(b.factory || []).map(line).join("")}</ul>
    ${b.factory_note ? `<div class="small">${esc(b.factory_note)}</div>` : ""}
    ${b.maintenance ? `<div class="small">Maintenance: ${esc(b.maintenance)}</div>` : ""}
    ${(b.sources || []).length ? `<div class="src">Sources: ${srcLinks(b.sources)}</div>` : ""}
  </div>`).join("");
}
// ---- Trim guide tab ----
const G = (D.guide && D.guide.models) || [];
const slug = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-");
const gYear = {};   // chosen year per model
G.forEach(m => { m.id = "g-" + slug(m.make + " " + m.model);
  const ys = (m.years || []).map(y => y.year); gYear[m.id] = ys.includes(new Date().getFullYear() - 1) ? new Date().getFullYear() - 1 : ys[ys.length - 1]; });
pills("g-make", [...new Set(G.map(m => m.make))]);
document.getElementById("g-jump").insertAdjacentHTML("beforeend", G.map(m => `<option value="${m.id}">${esc(m.make)} ${esc(m.model)}</option>`).join(""));
document.getElementById("g-jump").addEventListener("change", e => {
  const id = e.target.value; if (!id) return;
  document.querySelectorAll("#g-make input").forEach(i => i.checked = false); renderGuide();
  const el = document.getElementById(id); if (el) el.scrollIntoView({block: "start"}); e.target.value = ""; });
function guideFor(c) {      // the guide entry for a listed car: same make, longest model name contained in the car's model
  const mk = String(c.make).toLowerCase(), md = " " + String(c.model + " " + c.trim).toLowerCase().replace(/-/g, " ") + " ";
  const has = w => md.includes(String(w).toLowerCase().replace(/-/g, " "));
  // an entry's optional "match" ({model, fuel}) also catches cars listed under the base name, e.g. a GLC that's a plug-in = GLC 350e
  const fits = m => has(m.model) || (m.match && has(m.match.model) && (!m.match.fuel || String(c.fuel_type).toLowerCase().includes(m.match.fuel)));
  return G.filter(m => m.make.toLowerCase() === mk && fits(m))
          .sort((a, b) => (b.match && b.match.fuel ? 1 : 0) - (a.match && a.match.fuel ? 1 : 0) || b.model.length - a.model.length)[0];
}
function guideLink(c) {
  const m = guideFor(c);
  return m ? ` <a class="glink" href="#${m.id}" data-gid="${m.id}" data-year="${esc(c.year)}">trim info</a>` : "";
}
const row = (k, v) => v && v !== "unknown" ? `<dt>${k}</dt><dd>${esc(v)}</dd>` : "";
function trimCard(t) {
  return `<div class="trim${t.on_list ? "" : " off"}"><h3>${esc(t.name)}</h3>
    ${t.on_list ? '<span class="chip match">on your list</span>' : `<span class="chip off-chip">not on your list</span> <span class="small">${esc(t.why_not)}</span>`}
    <dl>${row("Engine", t.powertrain)}${row("Sunroof", t.sunroof)}${row("Audio", t.premium_audio)}${row("Seats", t.seats)}
      ${row("Black interior", t.black_interior)}${row("Spare", t.spare)}${row("MPG", t.mpg ? t.mpg + " (city/hwy/comb.)" : "")}</dl>
    ${(t.highlights || []).length ? `<div class="small">${t.builds_on ? "Adds over " + esc(t.builds_on) + ":" : "Comes with:"}</div>
      <ul>${t.highlights.map(h => `<li>${esc(h)}</li>`).join("")}</ul>` : ""}</div>`;
}
function renderGuide() {
  const mk = picked("g-make"), only = document.getElementById("g-only").checked;
  const html = G.filter(m => !mk.size || mk.has(m.make)).map(m => {
    const y = (m.years || []).find(y => y.year === gYear[m.id]) || (m.years || [])[0] || {trims: []};
    const trims = (y.trims || []).filter(t => !only || t.on_list);
    return `<section class="gmodel" id="${m.id}"><h2>${esc(m.make)} ${esc(m.model)}</h2>
      <div class="small rule">${esc(m.on_list_rule)}</div>
      <div class="years" role="group" aria-label="Model year">${(m.years || []).map(v =>
        `<button type="button" data-m="${m.id}" data-y="${v.year}" aria-pressed="${v.year === y.year}">${v.year}</button>`).join("")}</div>
      ${y.what_changed ? `<p class="small changed"><b>${y.year}:</b> ${esc(y.what_changed)}</p>` : ""}
      ${(m.years || []).length > 1 ? `<details class="yby"><summary>How the years differ</summary><ul>${m.years.map(v =>
        `<li><b>${v.year}:</b> ${esc(v.what_changed || "")}</li>`).join("")}</ul></details>` : ""}
      <div class="trims">${trims.map(trimCard).join("") || '<div class="muted">No trims on your list this year.</div>'}</div>
      ${(m.sources || []).length ? `<div class="src">Sources: ${srcLinks(m.sources)}</div>` : ""}
    </section>`; }).join("");
  document.getElementById("guide").innerHTML = html || '<p class="muted">The trim guide is empty.</p>';
}
document.getElementById("guide").addEventListener("click", e => {
  const b = e.target.closest("button[data-y]"); if (!b) return;
  gYear[b.dataset.m] = +b.dataset.y; renderGuide();
  const btn = document.querySelector(`button[data-m="${b.dataset.m}"][data-y="${b.dataset.y}"]`); if (btn) btn.focus(); });
["g-make", "g-only"].forEach(id => document.getElementById(id).addEventListener("input", renderGuide));
document.addEventListener("click", e => {      // "trim info" link on a car: open its model + year in the guide
  const a = e.target.closest("a[data-gid]"); if (!a) return;
  e.preventDefault();
  const m = G.find(x => x.id === a.dataset.gid), yr = +a.dataset.year;
  if (m && m.years.some(y => y.year === yr)) gYear[m.id] = yr;
  document.querySelectorAll("#g-make input").forEach(i => i.checked = false);
  showTab("guide"); renderGuide();
  const el = document.getElementById(a.dataset.gid); if (el) el.scrollIntoView({block: "start"}); });
// ---- Favorites: tap "Save" on a car; the Favorites tab shows the Available list limited to them ----
let fav = [], favOnly = false, favImport = [];
try { fav = JSON.parse(localStorage.getItem(PK + "fav") || "[]"); } catch (e) {}
try { const m = location.hash.match(/fav=([A-Z0-9,]+)/i);      // a shared favorites link: #fav=VIN1,VIN2
  if (m) { favImport = m[1].toUpperCase().split(",").filter(Boolean);
           favImport.forEach(v => { if (!fav.includes(v)) fav.push(v); });
           history.replaceState(null, "", location.pathname + "#favorites"); } } catch (e) {}
function saveFav() { try { localStorage.setItem(PK + "fav", JSON.stringify(fav)); } catch (e) {}
  document.getElementById("nfav").textContent = fav.filter(v => D.cars.some(c => c.vin === v)).length; }
// Sync with the website's own storage (functions/api/favs.js) so favorites follow you between devices.
// Without it (opened as a local file, or not set up), favorites stay on this device only.
let favSync = false;
function setSyncNote() {
  document.getElementById("fav-sync-on").hidden = !favSync;
  document.getElementById("fav-sync-off").hidden = favSync; }
function pushFav() {
  if (!favSync) return;
  fetch(API("favs"), {method: "PUT", headers: {"content-type": "application/json"}, body: JSON.stringify({fav})})
    .catch(() => {});
}
function paintFavButtons() {
  document.querySelectorAll(".favbtn").forEach(b => { const on = fav.includes(b.dataset.vin);
    b.setAttribute("aria-pressed", String(on)); b.innerHTML = on ? "&#9829; Saved" : "&#9825; Save"; });
}
async function pullFav() {
  if (location.protocol === "file:") { setSyncNote(); return; }   // the laptop's local copy can't sync
  try {
    const r = await fetch(API("favs"), {cache: "no-store"});
    if (!r.ok) throw new Error(r.status);
    const server = (await r.json()).fav;
    if (!Array.isArray(server)) throw new Error("bad reply");
    let first = false; try { first = localStorage.getItem(PK + "fav_synced") !== "1"; } catch (e) {}
    if (first) {                         // first sync on this device: keep what was saved here, too
      fav = [...new Set(server.concat(fav))];
      favSync = true; pushFav();
      try { localStorage.setItem(PK + "fav_synced", "1"); } catch (e) {}
    } else {
      fav = [...new Set(server.concat(favImport))]; favSync = true;
      if (favImport.some(v => !server.includes(v))) pushFav();
    }
    favImport = [];
    saveFav(); paintFavButtons(); if (favOnly) render();
  } catch (e) { favSync = false; }
  setSyncNote();
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) pullFav(); });   // pick up changes from the other device
function toggleFav(vin) {
  fav = fav.includes(vin) ? fav.filter(v => v !== vin) : fav.concat(vin); saveFav(); pushFav();
  document.querySelectorAll(`.favbtn[data-vin="${vin}"]`).forEach(b => { const on = fav.includes(vin);
    b.setAttribute("aria-pressed", String(on)); b.innerHTML = on ? "&#9829; Saved" : "&#9825; Save"; });
  if (favOnly) render();
}
document.addEventListener("click", e => { const b = e.target.closest(".favbtn"); if (b) toggleFav(b.dataset.vin); });
pullFav();
document.getElementById("fav-share").addEventListener("click", () => {
  const url = location.href.split("#")[0] + "#fav=" + fav.join(",");
  const done = () => alert("Link copied. Open it on your other device (phone or iPad) and your favorites will be added there.");
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done, () => prompt("Copy this link:", url));
  else prompt("Copy this link:", url); });
document.getElementById("fav-cmp").addEventListener("click", () => {
  cmp = fav.filter(v => D.cars.some(c => c.vin === v)).slice(0, MAXCMP); saveCmp(); render(); showTab("cmp"); });
saveFav();
// ---- Dislikes: tap "Dislike" to mark a car you don't want; it stays on the page (greyed), the "Mine" filter can hide it ----
let dis = [], disSync = false;
try { dis = JSON.parse(localStorage.getItem(PK + "dis") || "[]"); } catch (e) {}
function saveDis() { try { localStorage.setItem(PK + "dis", JSON.stringify(dis)); } catch (e) {} }
function pushDis() {
  if (disSync) fetch(API("dislikes"), {method: "PUT", headers: {"content-type": "application/json"}, body: JSON.stringify({dis})}).catch(() => {});
}
async function pullDis() {
  if (location.protocol === "file:") return;
  try {
    const r = await fetch(API("dislikes"), {cache: "no-store"});
    if (!r.ok) throw new Error(r.status);
    const server = (await r.json()).dis;
    if (!Array.isArray(server)) throw new Error("bad reply");
    let first = false; try { first = localStorage.getItem(PK + "dis_synced") !== "1"; } catch (e) {}
    dis = first ? [...new Set(server.concat(dis))] : server; disSync = true;
    if (first) { pushDis(); try { localStorage.setItem(PK + "dis_synced", "1"); } catch (e) {} }
    saveDis(); render();
  } catch (e) { disSync = false; }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) pullDis(); });
function toggleDis(vin) {
  dis = dis.includes(vin) ? dis.filter(v => v !== vin) : dis.concat(vin); saveDis(); pushDis(); render();
}
document.addEventListener("click", e => { const b = e.target.closest(".disbtn"); if (b) toggleDis(b.dataset.vin); });
const mark = c => fav.includes(c.vin) ? "Favorite" : dis.includes(c.vin) ? "Disliked" : "No mark";
pullDis();
// ---- Check yourself tab: dealers we couldn't read; the user checks them by hand ----
const CK = D.check || [];
let checked = {}, ckSync = false;
try { checked = JSON.parse(localStorage.getItem(PK + "checked") || "{}") || {}; } catch (e) {}
const todayISO = () => { const d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); };
const daysAgo = iso => Math.round((Date.parse(todayISO()) - Date.parse(iso)) / 864e5);
function saveChecked() {
  try { localStorage.setItem(PK + "checked", JSON.stringify(checked)); } catch (e) {}
  if (ckSync) fetch(API("checked"), {method: "PUT", headers: {"content-type": "application/json"}, body: JSON.stringify({checked})}).catch(() => {});
}
async function pullChecked() {
  if (location.protocol === "file:") return;
  try {
    const r = await fetch(API("checked"), {cache: "no-store"}); if (!r.ok) throw 0;
    const server = (await r.json()).checked || {};
    for (const [k, v] of Object.entries(checked)) if (!server[k] || server[k] < v) server[k] = v;   // keep the newest of both
    checked = server; ckSync = true; saveChecked(); renderCheck();
  } catch (e) { ckSync = false; }
  document.getElementById("chk-sync").textContent = ckSync ? "Checks sync between your devices." : "Checks are saved on this device.";
}
const ckClosed = new Set();      // brand sections the user collapsed
function renderCheck() {
  const hide = document.getElementById("chk-hide").checked;
  const isDone = d => checked[d.dealer] && daysAgo(checked[d.dealer]) <= 7;
  document.getElementById("ncheck").textContent = CK.filter(d => !isDone(d)).length;
  const brands = [...new Set(CK.map(d => d.brand))];
  let html = "";
  for (const b of brands) {
    const all = CK.filter(d => d.brand === b), left = all.filter(d => !isDone(d)).length;
    html += `<details class="ckgroup" data-brand="${esc(b)}" ${ckClosed.has(b) ? "" : "open"}><summary class="ckbrand">
      <b>${esc(b)}</b> · ${left ? `${left} of ${all.length} to check` : `all ${all.length} checked ✓`} · looking for ${esc(all[0].models.join(", "))}</summary>`;
    html += ckCards(all, hide) + "</details>";
  }
  document.getElementById("checklist").innerHTML = html || '<p class="muted">Nothing to check: every dealer was read by the search.</p>';
}
function ckCards(list, hide) {
  let html = "";
  for (const d of list) {
    const when = checked[d.dealer], age = when ? daysAgo(when) : null;
    if (hide && when && age <= 7) continue;
    const state = when ? (age <= 7 ? "done" : "stale") : "";
    const label = when ? (age === 0 ? "checked today" : age <= 7 ? `checked ${age} day${age > 1 ? "s" : ""} ago` : `checked ${age} days ago, check again`) : "";
    html += `<div class="ck ${state}"><h3>${esc(d.dealer)} <span class="small">${esc(d.distance_mi)} mi</span>${label ? `<span class="ckstate">✓ ${label}</span>` : ""}</h3>
      <div class="small why" title="${esc(d.detail)}">${esc(d.why)}${d.guess ? ". Its certified-inventory address is a best guess; if it doesn't load, tell Claude which dealer" : ""}</div>
      <div class="btns">${d.links.map(l => `<a class="cbtn" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)}</a>`).join("")}
        ${d.cpo ? `<a class="cbtn ghost" href="${esc(d.cpo)}" target="_blank" rel="noopener">All certified inventory</a>`
                : `<a class="cbtn ghost" href="${esc(d.homepage)}" target="_blank" rel="noopener">Open their website</a>`}
        <button type="button" class="cbtn ghost ckbtn" data-dealer="${esc(d.dealer)}">${when && age <= 7 ? "Undo" : "Mark checked"}</button></div></div>`;
  }
  return html || '<p class="small muted">All checked this week.</p>';
}
document.getElementById("checklist").addEventListener("toggle", e => {
  const g = e.target.closest && e.target.closest(".ckgroup"); if (!g) return;
  if (g.open) ckClosed.delete(g.dataset.brand); else ckClosed.add(g.dataset.brand); }, true);
document.getElementById("checklist").addEventListener("click", e => {
  const b = e.target.closest(".ckbtn"); if (!b) return;
  const k = b.dataset.dealer, when = checked[k];
  if (when && daysAgo(when) <= 7) delete checked[k]; else checked[k] = todayISO();
  saveChecked(); renderCheck(); });
document.getElementById("chk-hide").addEventListener("input", renderCheck);
document.getElementById("chk-clear").addEventListener("click", () => {
  if (!Object.keys(checked).length || !confirm("Clear every \"checked\" mark (on all your devices)?")) return;
  checked = {}; saveChecked(); renderCheck(); });
// ---- Compare tab: pick cars with "+ Compare", see them field by field ----
let cmp = []; try { cmp = JSON.parse(localStorage.getItem(PK + "cmp") || "[]").filter(v => D.cars.some(c => c.vin === v)); } catch (e) {}
const MAXCMP = 6;
function saveCmp() { try { localStorage.setItem(PK + "cmp", JSON.stringify(cmp)); } catch (e) {}
  document.getElementById("ncmp").textContent = cmp.length;
  document.getElementById("cmpbar-n").textContent = cmp.length;
  document.getElementById("cmpbar").hidden = !cmp.length; }
function clearCmp() {
  cmp = []; saveCmp();
  document.querySelectorAll(".cmpbtn").forEach(b => { b.setAttribute("aria-pressed", "false"); b.textContent = "+ Compare"; });
  if (!document.getElementById("panel-cmp").hidden) renderCompare();
}
function toggleCmp(vin) {
  if (cmp.includes(vin)) cmp = cmp.filter(v => v !== vin);
  else if (cmp.length >= MAXCMP) { alert(`You can compare up to ${MAXCMP} cars. Remove one first.`); return; }
  else cmp.push(vin);
  saveCmp();
  document.querySelectorAll(`.cmpbtn[data-vin="${vin}"]`).forEach(b => { const on = cmp.includes(vin);
    b.setAttribute("aria-pressed", String(on)); b.textContent = on ? "✓ Comparing" : "+ Compare"; });
  if (!document.getElementById("panel-cmp").hidden) renderCompare();
}
document.addEventListener("click", e => { const b = e.target.closest(".cmpbtn"); if (b) toggleCmp(b.dataset.vin);
  const r = e.target.closest(".rm[data-vin]"); if (r) toggleCmp(r.dataset.vin); });
// the grade part of a trim name: "40 TFSI Premium quattro" and "2.5 S Premium Plus Package" -> premium / premium plus
const gradeWords = name => trimWords(name).filter(w => !/^(\d[\d.]*[a-z]*|tfsi|tdi|tsi|s|line|turbo|t|quattro|package|pkg|sport|utility|4d|awd)$/.test(w));
const sameWords = (a, b) => a.length === b.length && a.every(w => b.includes(w));
const trimWords = name => String(name || "").toLowerCase().split(/[^a-z0-9.+]+/).filter(w => w && !/^(awd|4wd|4matic|xdrive|quattro|4motion|suv)$/.test(w));
const SOUND_BRANDS = /harman|kardon|bang|olufsen|b&o|lexicon|burmester|bowers|mark levinson|bose|sonos|meridian|jbl|els studio|revel|krell|premium sound|premium audio/i;
function soundCall(pa) {   // a Trim guide premium_audio line -> {v, t}
  pa = String(pa || "");
  if (/^not (available|offered)/i.test(pa)) return {v: "No", t: "not on this trim"};
  if (/^none/i.test(pa)) return /optional|package|available/i.test(pa) ? {v: "Not sure", t: "optional on this trim"} : {v: "No", t: "not on this trim"};
  // "Yes" only when a named premium system is standard: "SONOS optional on Premium Plus, standard on Prestige" is not
  const head = (pa.match(/^(.*?)\bstandard\b/i) || [])[1];
  if (head != null && SOUND_BRANDS.test(head) && !/optional|available|package|unknown/i.test(head))
    return {v: "Yes", t: head.replace(/[,;\s]+$/, "") + " (standard on this trim)"};
  return {v: "Not sure", t: /optional|package/i.test(pa) ? "optional on this trim" : ""};
}
const SEAT_WORD = {leather: "Leather", synthetic: "Synthetic leather", cloth: "Cloth"};
function guideCall(c, call) {   // what the Trim guide says for this car: its matched trim, else every trim it could be
  const t = trimInfo(c); if (t) return call(t);
  const m = guideFor(c), y = m && (m.years || []).find(y => y.year === parseInt(c.year)); if (!y) return null;
  // the dealer's trim name is shorter than the guide's ("Premium Plus" vs "2.5 S Premium Plus Package"), or missing:
  // use every trim it could be, but only when they all say the same thing
  const model = trimWords(m.model), gw = n => gradeWords(n).filter(w => !model.includes(w));
  const mine = trimWords(c.trim), grade = gw(c.trim);
  // same grade first ("Premium" = "Q3 40 TFSI Premium" and "45 S line Premium", not "Premium Plus"), else every trim containing its words
  let pick = grade.length ? (y.trims || []).filter(t => sameWords(gw(t.name), grade)) : [];
  if (!pick.length) pick = (y.trims || []).filter(t => t.on_list !== false || !mine.length)
    .filter(t => mine.every(w => (" " + trimWords(t.name).join(" ") + " ").includes(" " + w + " ")));
  const calls = pick.map(call);
  if (!calls.length || !calls.every(x => x.v === calls[0].v) || calls[0].v === "Not sure") return null;
  const why = mine.length ? "standard on this trim" : "standard on every trim of this model";
  return calls.every(x => x.t === calls[0].t) && mine.length ? calls[0] : {v: calls[0].v, t: calls[0].v === "Yes" ? why : ""};
}
function seatCall(t) {
  const first = String(t.seats || "").split(";")[0].toLowerCase();
  const kind = /synthetic|leatherette|inteluxe|duo ?leather|luxtec|mb-?tex|nuluxe|syntex|sensatec|vegan|softex|sensafin|v-?tex|artico|dinamica|microtech/.test(first) ? "synthetic"
             : /cloth|fabric/.test(first) ? "cloth" : /leather|nappa|merino|vernasca|aniline/.test(first) ? "leather" : "";
  return kind ? {v: SEAT_WORD[kind], t: "standard on this trim"} : {v: "Not sure", t: ""};
}
function roofCall(t) {
  const s = String(t.sunroof || "").toLowerCase();
  // the roof must open (Oct 24 2026): a fixed glass roof is a "No"; fixed standard with an opening one optional = not sure
  const fixed = /fixed|does ?n[o']?t open|non-opening|sky lounge/.test(s), opens = /\bopens\b|tilt|slid|opening|power skyglass/.test(s);
  if (fixed && !opens) return {v: "No", t: "fixed glass roof (doesn't open)"};
  if (fixed && opens && !/^standard (tilt|slid|opening|power)/.test(s)) return {v: "Not sure", t: "fixed roof standard; opening roof optional"};
  if (/^(standard|yes)/.test(s)) return {v: "Yes", t: "standard on this trim"};
  if (/^(not available|not offered|none|no\b)/.test(s)) return {v: "No", t: "not on this trim"};
  return {v: "Not sure", t: /optional|package/.test(s) ? "optional on this trim" : ""};
}
function seatOf(c) {       // seat material: the dealer's page, else what the Trim guide says this trim comes with
  if (c._seat) return c._seat;
  const r = SEAT_WORD[c.seats] ? {v: SEAT_WORD[c.seats], t: ""} : guideCall(c, seatCall) || {v: "Not sure", t: ""};
  c.seat = r.v; return c._seat = r;
}
function roofFromGuide(c) {   // like soundFromGuide: optional + a full equipment list that never mentions a roof = no roof
  const r = guideCall(c, t => { const x = roofCall(t); return x.v === "Not sure" && x.t ? {v: "Optional", t: ""} : x; });
  if (r && r.v !== "Optional") return r;
  if (r && num(c.page_features) >= 25) return {v: "No", t: "not on the dealer's equipment list"};
  return {v: "Not sure", t: r ? "optional on this trim" : ""};
}
function roofOf(c) {       // sunroof: the dealer's page / brand feed / your check, else the Trim guide
  if (c._roof) return c._roof;
  const r = c.sunroof === "True" ? {v: "Yes", t: ""} : c.sunroof === "False" ? {v: "No", t: ""}
          : roofFromGuide(c);
  c.roof = r.v; return c._roof = r;
}
function soundFromGuide(c) {
  const r = guideCall(c, t => { const x = soundCall(t.premium_audio);
    return x.v === "Not sure" && /optional|package|available/i.test(String(t.premium_audio || "")) ? {v: "Optional", t: ""} : x; });
  if (r && r.v !== "Optional") return r;
  // optional on this trim: a dealer page with a full equipment list names the system when the car has it
  if (r && num(c.page_features) >= 25) return {v: "No", t: "not on the dealer's equipment list"};
  return {v: "Not sure", t: r ? "optional on this trim" : ""};
}
function soundOf(c) {      // upgraded sound: the dealer's page names the system, else what the Trim guide says for this trim
  if (c._snd) return c._snd;
  const r = c.audio ? {v: "Yes", t: c.audio} : c.audio_none ? {v: "No", t: "checked by you: no premium system"}
          : soundFromGuide(c);
  c.snd = r.v; return c._snd = r;
}
function trimInfo(c) {      // this car's trim card in the Trim guide, when the trim name matches well enough
  const m = guideFor(c); if (!m) return null;
  const y = (m.years || []).find(y => y.year === parseInt(c.year)); if (!y) return null;
  // the car's name plus the words in its web address, which often name the trim (".../2023-Toyota-bZ4X-XLE-JTM...")
  const slug = decodeURIComponent(String(c.listing_url || "").split("?")[0]).split("/").slice(3).join(" ").replace(/[_+.]/g, " ");
  const title = (" " + c.title + " " + slug + " ").toLowerCase().replace(/-/g, " ");     // "X-Line" = "x line"
  let best = null, bestScore = 0, bestN = 0;
  (y.trims || []).forEach(t => {
    const words = trimWords(t.name);
    // a short word must match whole ("s" is not the start of "sportage"); a longer one may start a word
    const n = words.filter(w => title.includes(" " + w + " ") || (w.length > 2 && title.includes(" " + w))).length, hit = n / (words.length || 1);
    if (hit > bestScore || (hit === bestScore && n > bestN)) { bestScore = hit; bestN = n; best = t; } });   // ties: more words matched ("Premium Plus" over "Premium")
  return bestScore >= 0.6 ? best : null;
}
// Compare tab rows: [label, show(car), value(car) for the ★, "low"/"high" = which is better]; a label alone = section heading
const SCORE_NAMES = {price: "Price", phev: "Plug-in / electric", mpg: "Gas mileage", audio: "Premium sound", leather: "Leather",
  real_leather: "Real leather", ventilated_seats: "Cooled seats", ground_clearance: "8+ in clearance", spare_tire: "Spare tire",
  sunroof: "Sunroof", awd: "All-wheel drive", exterior_color: "Color", mileage: "Mileage"};
const yesNo = v => v === "True" ? "Yes" : v === "False" ? "No" : "Not shown";
const ageYears = c => { const y = num(c.year); if (!y) return null;      // in service ~April of the model year (as the warranty column)
  return Math.max(0.25, (Date.now() - new Date(y, 3, 1)) / (365.25 * 864e5)); };
const perYear = c => { const m = num(c.mileage), a = ageYears(c); return m == null || !a ? null : Math.round(m / a); };
const belowSticker = c => { const p = num(c.price_total), m = c.msrp; return p && m ? Math.round(100 * (1 - p / m)) : null; };
const daysListed = c => { const a = Date.parse(c.first_seen); return isNaN(a) ? null : Math.round((Date.now() - a) / 864e5); };
const recalls = c => String(c.recall_flags || "").split(";").map(x => x.trim()).filter(Boolean);
const badgeWords = c => [...new Set(String(c.carfax_badges || "").split(",").map(b => /own/.test(b) ? "one owner" : /accident/.test(b) ? "no accidents"
  : /service/.test(b) ? "service records" : /personal/.test(b) ? "personal use" : "").filter(Boolean))].join(", ");
const pf = c => c.perf || {};
const hpOf = c => { if (num(pf(c).hp) != null) return {v: num(pf(c).hp), t: ""};     // spec table, else the Trim guide's engine line
  const t = trimInfo(c), m = t && String(t.powertrain || "").match(/(\d{3})\s*hp/i); return m ? {v: +m[1], t: "trim guide"} : null; };
const dcOf = c => num(pf(c).dc_kw) != null || num(pf(c).dc_min) != null;
const homeHours = c => { const b = num(pf(c).battery_kwh), k = num(pf(c).ac_kw);       // empty to full, ~10% charging losses
  return b && k ? Math.round(b / k * 1.1 * 2) / 2 : null; };
const plug = c => c.fuel_type === "ev" || c.fuel_type === "phev";
const NONE = '<span class="muted">—</span>';
const FIELDS = [
  ["Price & value"],
  ["Price (with fees)", c => priceCell(c), c => num(c.price_total), "low"],
  ["Fees", c => c.fees_estimated === "True" ? "estimated (not shown on the listing)" : num(c.price) && num(c.price_total) && num(c.price_total) > num(c.price)
      ? fmt$(num(c.price_total) - num(c.price)) + " included" : "included in the price", null, null],
  ["Price cut", c => c.dropped ? `&#9660; ${fmt$(c.cut)} since first seen` + (c.lastCut ? `<div class="small">latest ${fmt$(c.lastCut.amt)} on ${esc(shortDate(c.lastCut.on))}</div>` : "") : "none yet",
      c => c.cut || 0, "high"],
  ["Original price", c => origCell(c), null, null],
  ["Price history", c => (c.hist || []).length > 1 ? (c.hist || []).map(h => `${esc(shortDate(h[0]))}: ${fmt$(h[1])}`).join("<br>") : "no changes", null, null],
  ["Sticker when new", c => msrpCell(c), null, null],
  ["Below sticker", c => belowSticker(c) == null ? "?" : belowSticker(c) + "% less than new" + (c.msrp_source === "trim base" ? ' <span class="small">(vs the trim\'s base price)</span>' : ""), c => belowSticker(c), "high"],
  ["Est. monthly", c => fmt$(c.est_monthly_cost), c => num(c.est_monthly_cost), "low"],
  ["Match & score"],
  ["Status", c => c.needs_call ? `<span class="chip call">needs a call</span> <span class="small">${esc(c.needs_call)}</span>` : '<span class="chip match">match</span>', null, null],
  ["Score", c => esc(c.score), c => num(c.score), "high"],
  ["Score breakdown", c => (c.score_parts || []).length ? (c.score_parts || []).map(([k, pts, max]) =>
      `<div class="sbar"><span>${esc(SCORE_NAMES[k] || k)}</span><span class="sb"><i style="width:${max ? Math.round(100 * pts / max) : 0}%"></i></span><b>${Math.round(pts)}/${Math.round(max)}</b></div>`).join("") : "—", null, null],
  ["Your mark", c => mark(c) === "Favorite" ? "&#9829; Favorite" : mark(c) === "Disliked" ? "Disliked" : "—", null, null],
  ["Window sticker seen", c => c.sticker ? '<span class="chip match">&#10003; features verified</span>' : "no", null, null],
  ["The car"],
  ["Year", c => esc(c.year), c => num(c.year), "high"],
  ["Body", c => esc(c.body || "SUV"), null, null],
  ["Fuel", c => esc(c.fuel), null, null],
  ["Drive", c => esc(c.drive), c => c.drive === "AWD" ? 1 : c.drive === "Not sure" ? null : 0, "high"],
  ["Engine / motor", c => { const t = trimInfo(c); return t && t.powertrain ? esc(t.powertrain) + ` <span class="small">(trim guide)</span>` : '<span class="muted">—</span>'; }, null, null],
  ["MPG", c => num(c.mpg_combined) == null ? (c.fuel_type === "ev" ? "— (electric)" : "?") : Math.round(num(c.mpg_combined)) + " combined"
      + (num(c.mpg_city) != null ? `<div class="small">${Math.round(num(c.mpg_city))} city / ${Math.round(num(c.mpg_hwy))} hwy${c.fuel_type === "phev" ? ", gas only" : ""}</div>` : "")
      + (c.mpg_source === "EPA" ? ' <span class="small">EPA</span>' : c.mpg_source === "guide" ? ' <span class="small">trim guide</span>' : ""), c => num(c.mpg_combined), "high"],
  ["Miles", c => num(c.mileage) == null ? "?" : Math.round(num(c.mileage)).toLocaleString(), c => num(c.mileage), "low"],
  ["Miles per year", c => perYear(c) == null ? "?" : perYear(c).toLocaleString() + ' <span class="small">(in service ~Apr ' + esc(c.year) + ")</span>", c => perYear(c), "low"],
  ["Exterior", c => esc(c.ext_color || "?"), null, null],
  ["Interior", c => esc(c.int_color || "?"), null, null],
  ["Performance, range & charging"],
  ["Horsepower", c => { const h = hpOf(c); return h ? h.v + " hp" + (num(pf(c).hp_boost) ? `<div class="small">${num(pf(c).hp_boost)} hp with Boost</div>` : "")
      + (h.t ? ` <span class="small">${h.t}</span>` : "") : "?"; }, c => hpOf(c) ? hpOf(c).v : null, "high"],
  ["Torque", c => num(pf(c).torque) != null ? num(pf(c).torque) + " lb-ft" : NONE, c => num(pf(c).torque), "high"],
  ["0-60 mph", c => num(pf(c).zero_60) != null ? num(pf(c).zero_60).toFixed(1) + " s" : NONE, c => num(pf(c).zero_60), "low"],
  ["Electric range", c => num(c.ev_range) == null ? (plug(c) ? "?" : "—") : Math.round(num(c.ev_range)) + " mi" + (c.ev_range_src ? ` <span class="small">${esc(c.ev_range_src)}</span>` : ""), c => num(c.ev_range), "high"],
  ["Battery", c => num(pf(c).battery_kwh) != null ? num(pf(c).battery_kwh) + " kWh" : (plug(c) ? "?" : "—"), c => num(pf(c).battery_kwh), "high"],
  ["Fast charging (DC)", c => !plug(c) ? "—" : !dcOf(c) ? (c.fuel_type === "phev" && num(pf(c).battery_kwh) != null ? "not offered" : "?")
      : (num(pf(c).dc_min) != null ? `${num(pf(c).dc_min)} min <span class="small">(${esc(pf(c).dc_window || "")})</span>` : "")
        + (num(pf(c).dc_kw) != null ? `<div class="small">up to ${num(pf(c).dc_kw)} kW</div>` : ""), c => num(pf(c).dc_min), "low"],
  ["Fast-charge peak", c => num(pf(c).dc_kw) != null ? num(pf(c).dc_kw) + " kW" : (plug(c) ? NONE : "—"), c => num(pf(c).dc_kw), "high"],
  ["Home charging (Level 2)", c => !plug(c) ? "—" : num(pf(c).ac_kw) == null ? "?" : `${num(pf(c).ac_kw)} kW`
      + (homeHours(c) != null ? `<div class="small">about ${homeHours(c)} h empty to full</div>` : ""), c => num(pf(c).ac_kw), "high"],   // ★ = fastest charger (a small plug-in battery fills sooner anyway)
  ["Ground clearance", c => num(c.clearance) == null ? "?" : num(c.clearance).toFixed(1) + " in" + (c.clearance_src ? ` <span class="small">${esc(c.clearance_src)}</span>` : ""), c => num(c.clearance), "high"],
  ["Cargo behind rear seats", c => num(pf(c).cargo_cu_ft) != null ? num(pf(c).cargo_cu_ft) + " cu ft" : NONE, c => num(pf(c).cargo_cu_ft), "high"],
  ["Towing", c => num(pf(c).tow_lb) != null ? num(pf(c).tow_lb).toLocaleString() + " lb" : NONE, c => num(pf(c).tow_lb), "high"],
  ["Where these specs come from", c => pf(c).source ? `<span class="small">${esc(pf(c).source)}</span>` : NONE, null, null],
  ["Features"],
  ["Sunroof", c => esc(roofOf(c).v) + (roofOf(c).t ? ` <span class="small">${esc(roofOf(c).t)}</span>` : ""), null, null],
  ["Upgraded sound", c => esc(soundOf(c).v) + (soundOf(c).t ? ` <span class="small">${esc(soundOf(c).t)}</span>` : ""), null, null],
  ["Seats", c => esc(seatOf(c).v) + (seatOf(c).t ? ` <span class="small">${esc(seatOf(c).t)}</span>` : ""), null, null],
  ["Ventilated (cooled) seats", c => c.ventilated_seats ? yesNo(c.ventilated_seats) : (trimInfo(c) && /ventilat|cooled/i.test(trimInfo(c).seats || "") && !/no (ventilat|cool)|not? ventilat|without (ventilat|cool)/i.test(trimInfo(c).seats || "")
      ? "Yes <span class=\"small\">trim guide</span>" : "Not shown"), null, null],
  ["Spare tire", c => c.spare_tire === "True" ? "Yes" : c.spare_tire === "False" ? "No (repair kit)" : (trimInfo(c) && trimInfo(c).spare ? esc(trimInfo(c).spare) + ' <span class="small">trim guide</span>' : "Not shown"), null, null],
  ["Seats (trim guide)", c => { const t = trimInfo(c); return t ? `${esc(t.seats)} <span class="small">(${esc(t.name)})</span>` : '<span class="muted">—</span>'; }, null, null],
  ["What this trim adds", c => { const t = trimInfo(c); return t && (t.highlights || []).length
      ? `<span class="small">${t.builds_on ? "over " + esc(t.builds_on) + ":" : "comes with:"}</span><ul class="hl">${t.highlights.slice(0, 10).map(h => `<li>${esc(h)}</li>`).join("")}</ul>` : '<span class="muted">—</span>'; }, null, null],
  ["Warranty & history"],
  ["Warranty ends", c => c.warr_end ? "~" + monthYr(new Date(c.warr_end)) : "?", c => c.warr_end || null, "high"],
  ["Bumper-to-bumper ends", c => c.warr_full_end ? "~" + monthYr(new Date(c.warr_full_end)) : (c.warr_end ? "over" : "?"), c => c.warr_full_end || null, "high"],
  ["Warranty detail", c => c.warr_html, null, null],
  ["Certified program", c => esc(c.cpo_program || "?") + (c.cpo_warranty_terms ? `<div class="small">${esc(String(c.cpo_warranty_terms).slice(0, 220))}</div>` : ""), null, null],
  ["CARFAX", c => esc({clean: "no accidents", accident: "accident", not_verified: "not verified"}[c.carfax_status] || c.carfax_status)
      + (badgeWords(c) ? `<div class="small">dealer page shows: ${esc(badgeWords(c))}</div>` : ""), null, null],
  ["Safety recalls (model)", c => recalls(c).length ? `${recalls(c).length}<div class="small">${recalls(c).map(esc).join("<br>")}</div><div class="small">ask the dealer if they're done</div>` : "none found",
      c => recalls(c).length, "low"],
  ["Dealer & listing"],
  ["Dealer", c => `${esc(c.dealer)}<div class="small">${esc(c.distance_mi)} mi from home</div>`, c => num(c.distance_mi), "low"],
  ["On the tracker", c => daysListed(c) == null ? "?" : `${daysListed(c)} day${daysListed(c) === 1 ? "" : "s"} <span class="small">(first seen ${esc(c.first_seen)})</span>`, null, null],
  ["Notes", c => esc(c.notes || "—"), null, null],
  ["Listing", c => `<a href="${esc(c.listing_url)}" target="_blank" rel="noopener">dealer's page</a>`, null, null],
  ["VIN", c => `<span class="vin">${esc(c.vin)}</span>`, null, null],
];

function renderCompare() {
  const cars = cmp.map(v => D.cars.find(c => c.vin === v)).filter(Boolean), el = document.getElementById("cmp");
  if (!cars.length) { el.innerHTML = '<p class="muted">Tap <b>+ Compare</b> on up to 6 cars in the Available tab, then come back here to see them side by side. The best value in each row gets a ★.</p>'; return; }
  const L = i => `<span class="cl k${i}">${String.fromCharCode(65 + i)}</span>`;
  // on a phone every value line repeats its car's letter, colour and a short name ("B · GV70 '23"), so a row reads on its own
  const short = c => `${String(c.model || "").replace(/^Electrified /, "").replace(/Plug-in Hybrid/i, "PHEV")} '${String(c.year).slice(2)}`;
  const tag = (c, i) => `<span class="ctag">${L(i)}<span class="cn">${esc(short(c))}</span></span>`;
  const head = `<div class="crow chead"><div class="clabel">Car</div>${cars.map((c, i) => `<div class="ch k${i}">${L(i)}<a href="${esc(c.listing_url)}" target="_blank" rel="noopener">${esc(c.title)}</a>
      <div class="small">${esc(c.dealer)}</div><button type="button" class="rm" data-vin="${esc(c.vin)}">remove</button></div>`).join("")}</div>`;
  const rows = FIELDS.map(([label, show, val, better]) => {
    if (!show) return `<div class="crow csec"><div>${esc(label)}</div></div>`;
    const shown = cars.map(show);
    if (shown.every(v => v === NONE || v === "—")) return "";        // nothing known for any of these cars (e.g. towing)
    let bestV = null;
    if (val && better && cars.length > 1) { const vs = cars.map(val).filter(v => v != null);
      if (vs.length > 1 && new Set(vs).size > 1) bestV = better === "low" ? Math.min(...vs) : Math.max(...vs); }
    return `<div class="crow"><div class="clabel">${esc(label)}</div>${cars.map((c, i) =>
      `<div class="cval k${i}${bestV != null && val(c) === bestV ? " best" : ""}">${tag(c, i)}<div>${shown[i]}</div></div>`).join("")}</div>`; }).join("");
  el.innerHTML = `<div class="cmptop"><span class="muted">Comparing ${cars.length} car${cars.length > 1 ? "s" : ""}</span>
      <button type="button" class="cbtn ghost" id="cmp-clear">Clear compare</button></div>
    <div class="cmp" style="--n:${cars.length}">${head}${rows}</div>
    <p class="small">★ = best in that row: lowest price, monthly, miles, miles per year, recalls and distance; biggest price cut and discount below sticker; highest score, year, MPG, range and clearance; all-wheel drive; latest warranty end. Engine, trim features and cooled seats/spare marked "trim guide" come from the Trim guide for the matched trim, not the dealer's page.</p>`;
  document.getElementById("cmp-clear").onclick = clearCmp;
}
saveCmp();
document.getElementById("cmpbar-clear").addEventListener("click", clearCmp);
document.getElementById("cmpbar-view").addEventListener("click", () => showTab("cmp"));
let sortK = "score", dir = -1, gK = "removed_on", gDir = -1;
const sorter = (k, d) => (a, b) => { let x = a[k], y = b[k];
  const ex = x == null || x === "", ey = y == null || y === ""; if (ex || ey) return ex - ey;   // blanks last
  const nx = num(x), ny = num(y); if (nx != null && ny != null && !/_(seen|on)$/.test(k)) return (nx - ny) * d;
  return String(x ?? "").localeCompare(String(y ?? "")) * d; };
function render() { renderRows(); stickHeads(); }

// ---- Map: dealers of the cars the filters show (OpenStreetMap via Leaflet, loaded only when the map is opened) ----
let lastCars = [], mapOn = false, map = null, mapLayer = null, mapFit = true, trip = [];
try { trip = JSON.parse(localStorage.getItem(PK + "trip") || "[]"); } catch (e) {}
const PL = (D.places && D.places.dealers) || {}, HOME = (D.places && D.places.home) || {};
const HOME_Q = HOME.zip ? `${HOME.zip}` : "";
const placeQ = n => [n, (PL[n] || {}).address, (PL[n] || {}).city, "CA"].filter(Boolean).join(", ");
const gmSearch = n => "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(placeQ(n));
function miles(a, b) {           // straight-line distance between two dealers, in miles
  const R = 3958.8, t = x => x * Math.PI / 180, dl = t(b.lat - a.lat), dn = t(b.lon - a.lon);
  const h = Math.sin(dl / 2) ** 2 + Math.cos(t(a.lat)) * Math.cos(t(b.lat)) * Math.sin(dn / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  return new Promise((ok, bad) => {
    const css = document.createElement("link"); css.rel = "stylesheet";
    css.href = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"; document.head.appendChild(css);
    const js = document.createElement("script"); js.src = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js";
    js.onload = ok; js.onerror = bad; document.head.appendChild(js);
  });
}
function byDealer(cars) {
  const g = {};
  cars.forEach(c => { if (PL[c.dealer]) (g[c.dealer] = g[c.dealer] || []).push(c); });
  return g;
}
function popupHtml(name, list, groups) {
  const p = PL[name], inTrip = trip.includes(name);
  const near = Object.keys(groups).filter(n => n !== name).map(n => [n, miles(p, PL[n])]).filter(x => x[1] <= 8)
    .sort((a, b) => a[1] - b[1]).slice(0, 4);
  return `<div class="mpop"><h4>${esc(name)}</h4><div class="small">${esc(list[0].distance_mi)} mi from home${p.approx ? " · pin is the city center, not the exact spot" : ""}</div>
    <ul>${list.map(c => `<li><a href="${esc(c.listing_url)}" target="_blank" rel="noopener">${esc(c.title)}</a><br>
      <span class="small">${fmt$(c.price_total)} · ${num(c.mileage) == null ? "? mi" : Math.round(num(c.mileage)).toLocaleString() + " mi"}${c.needs_call ? " · needs a call" : ""}${fav.includes(c.vin) ? " · &#9829;" : ""}</span></li>`).join("")}</ul>
    ${near.length ? `<div class="small"><b>Close by:</b> ${near.map(([n, d]) => `${esc(n)} (${d.toFixed(1)} mi, ${groups[n].length} car${groups[n].length > 1 ? "s" : ""})`).join("; ")}</div>` : ""}
    <div class="acts"><button type="button" class="cbtn" data-trip="${esc(name)}">${inTrip ? "&#10003; In your trip (remove)" : "+ Add to trip"}</button>
      <a class="cbtn ghost" href="${gmSearch(name)}" target="_blank" rel="noopener">Open in Google Maps</a></div></div>`;
}
function drawTrip() {
  const box = document.getElementById("trip");
  trip = trip.filter(n => PL[n]);
  if (!trip.length) { box.innerHTML = '<div class="small">Plan a test-drive trip: tap a pin, then <b>+ Add to trip</b>. Google Maps puts the stops in a route from home.</div>'; return; }
  const stops = trip.map(placeQ);
  const url = "https://www.google.com/maps/dir/?api=1&travelmode=driving" + (HOME_Q ? "&origin=" + encodeURIComponent(HOME_Q) : "")
    + "&destination=" + encodeURIComponent(stops[stops.length - 1])
    + (stops.length > 1 ? "&waypoints=" + encodeURIComponent(stops.slice(0, -1).join("|")) : "");
  const count = n => lastCars.filter(c => c.dealer === n).length;
  box.innerHTML = `<b>Your trip</b> <span class="small">(${trip.length} stop${trip.length > 1 ? "s" : ""}, in this order)</span>
    <ol>${trip.map((n, i) => `<li>${esc(n)} <span class="small">${count(n)} car${count(n) === 1 ? "" : "s"} shown</span>
      ${i ? `<button type="button" class="x" data-up="${i}" aria-label="Move up">&#8593;</button>` : ""}<button type="button" class="x" data-trip="${esc(n)}" aria-label="Remove">&times;</button></li>`).join("")}</ol>
    <a class="cbtn" href="${url}" target="_blank" rel="noopener">Open the route in Google Maps</a>
    <button type="button" class="cbtn ghost" id="trip-clear">Clear trip</button>`;
}
function drawMap() {
  if (!map) return;
  const groups = byDealer(lastCars);
  mapLayer.clearLayers();
  const pts = [];
  if (HOME.lat) {
    L.marker([HOME.lat, HOME.lon], {icon: L.divIcon({className: "pinwrap", html: '<span class="pin home">&#8962;</span>', iconSize: [26, 26], iconAnchor: [13, 13]}),
      title: "Home", zIndexOffset: -100}).addTo(mapLayer);
    pts.push([HOME.lat, HOME.lon]);
  }
  Object.entries(groups).forEach(([name, list]) => {
    const p = PL[name], calls = list.some(c => c.needs_call), hasFav = list.some(c => fav.includes(c.vin));
    const cls = `pin ${calls ? "c" : "m"}${p.approx ? " approx" : ""}${hasFav ? " fav" : ""}${trip.includes(name) ? " trip" : ""}`;
    L.marker([p.lat, p.lon], {icon: L.divIcon({className: "pinwrap", html: `<span class="${cls}">${list.length}</span>`, iconSize: [30, 26], iconAnchor: [15, 13]}),
      title: `${name}: ${list.length} car${list.length > 1 ? "s" : ""}`})
      .bindPopup(() => popupHtml(name, list, groups), {maxWidth: 290}).addTo(mapLayer);
    pts.push([p.lat, p.lon]);
  });
  if (mapFit && pts.length) { map.fitBounds(pts, {padding: [24, 24], maxZoom: 12}); }
  drawTrip();
}
document.getElementById("map-toggle").addEventListener("click", async e => {
  mapOn = !mapOn; e.currentTarget.setAttribute("aria-pressed", mapOn);
  e.currentTarget.innerHTML = mapOn ? "&#128506; Hide the map" : "&#128506; Show on a map";
  document.getElementById("map-box").hidden = !mapOn;
  if (!mapOn) return;
  try { await loadLeaflet(); } catch (err) {
    document.getElementById("map").innerHTML = '<p class="muted" style="padding:12px">The map couldn\'t load (no internet connection?).</p>'; return; }
  if (!map) {
    map = L.map("map", {scrollWheelZoom: false, zoomSnap: 0.25});
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);
    mapLayer = L.layerGroup().addTo(map);
    map.on("zoomstart dragstart", () => { mapFit = false; });   // keep the view the viewer chose while filters change
  }
  mapFit = true; setTimeout(() => { map.invalidateSize(); drawMap(); }, 30);   // size first, so the view fits the screen
});
document.addEventListener("click", e => {
  const t = e.target.closest("[data-trip]"), up = e.target.closest("[data-up]");
  if (t) { const n = t.dataset.trip; trip = trip.includes(n) ? trip.filter(x => x !== n) : trip.concat([n]); }
  else if (up) { const i = +up.dataset.up; [trip[i - 1], trip[i]] = [trip[i], trip[i - 1]]; }
  else if (e.target.id === "trip-clear") trip = [];
  else return;
  try { localStorage.setItem(PK + "trip", JSON.stringify(trip)); } catch (err) {}
  if (map) { map.closePopup(); const f = mapFit; mapFit = false; drawMap(); mapFit = f; } else drawTrip();
});
function renderRows() {
  const q = document.getElementById("q").value.toLowerCase(), show = picked("f-show"), mk = picked("f-make"), fu = picked("f-fuel"), yr = picked("f-year"), bd = picked("f-body"), dv = picked("f-drive"),
        rf = picked("f-roof"), sd = picked("f-sound"), st = picked("f-seat"), mn = picked("f-mine"),
        lo = +pmin.value, hi = +pmax.value, priced = lo > P_LO || hi < P_HI,
        mlo = +mmin.value, mhi = +mmax.value, milesSet = mlo > M_LO || mhi < M_HI;
  const base = c => (!q || JSON.stringify(c).toLowerCase().includes(q)) && (!mk.size || mk.has(c.make)) && (!fu.size || fu.has(c.fuel))
                    && (!yr.size || yr.has(String(c.year))) && (!bd.size || bd.has(c.body || "SUV")) && (!dv.size || dv.has(c.drive || "Not sure"))
                    && (!rf.size || rf.has(roofOf(c).v)) && (!sd.size || sd.has(soundOf(c).v)) && (!st.size || st.has(seatOf(c).v))
                    && (!priced || (num(c.price_total) != null && num(c.price_total) >= lo && num(c.price_total) <= hi))
                    && (!milesSet || (num(c.mileage) != null && num(c.mileage) >= mlo && num(c.mileage) <= mhi))
                    && (!clearS.on() || clearS.ok(num(c.clearance))) && (!rangeS.on() || rangeS.ok(num(c.ev_range)))
                    && (!mn.size || mn.has(mark(c)));
  const wasStatus = c => c.needs_call ? "Needs a call" : "Meets all criteria";
  const onlyNew = document.getElementById("only-new").checked, onlyCut = document.getElementById("only-cut").checked;
  document.getElementById("cut-tile").setAttribute("aria-pressed", onlyCut);
  let cars = D.cars.filter(c => base(c) && (!show.size || show.has(wasStatus(c))) && (!favOnly || fav.includes(c.vin))
                            && (!onlyNew || c.is_new) && (!onlyCut || c.dropped));
  cars.sort(sorter(sortK, dir));
  lastCars = cars; if (mapOn) drawMap();
  const gone = D.gone.filter(c => base(c) && (!show.size || show.has(wasStatus(c)))).sort(sorter(gK, gDir));
  document.getElementById("gone-rows").innerHTML = gone.map(c => `<tr>
    <td class="car"><a href="${esc(c.listing_url)}" target="_blank" rel="noopener">${esc(c.title)}</a><div class="vin">${esc(c.vin)}</div>
      <div class="small">was ${c.needs_call ? "needs a call" : "a match"}</div><button type="button" class="favbtn" data-vin="${esc(c.vin)}" aria-pressed="${fav.includes(c.vin)}">${fav.includes(c.vin) ? "&#9829; Saved" : "&#9825; Save"}</button></td>
    <td class="num" data-l="Year">${esc(c.year)}</td>
    <td class="span2" data-l="Dealer">${esc(c.dealer)}<div class="small">${esc(c.distance_mi)} mi</div></td>
    <td class="num p-price" data-l="Last price">${priceCell(c)}</td><td class="num" data-l="Original price">${origCell(c)}</td>
    <td class="num" data-l="Miles">${num(c.mileage) == null ? "?" : Math.round(num(c.mileage)).toLocaleString()}</td>
    <td data-l="Fuel">${esc(c.fuel)}</td><td class="wide" data-l="Colors">${esc(c.colors)}</td><td class="small" data-l="First seen">${esc(c.first_seen)}</td>
    <td class="small" data-l="Gone since">${esc(c.removed_on || c.last_seen)}</td><td class="num" data-l="Days listed">${esc(c.days)}</td>
    <td class="small wide" data-l="Why">${esc(c.fail_reasons)}</td></tr>`).join("")
    || `<tr><td colspan="12" class="muted">${D.gone.length ? "No cars match these filters." : "Nothing yet. Cars that leave the dashboard because they sold or were taken down will show up here."}</td></tr>`;
  document.getElementById("rows").innerHTML = cars.map(c => `<tr${dis.includes(c.vin) ? ' class="disliked"' : ""}>
    <td class="num p-score" data-l="Score">${esc(c.score)}<br>${c.needs_call ? '<span class="chip call">needs a call</span>' : '<span class="chip match">match</span>'}</td>
    <td class="car${c.sticker ? " has-sticker" : ""}">${c.sticker ? '<button type="button" class="stickerok" data-tip="Features verified by window sticker" aria-label="Features verified by window sticker">&#10003;</button>' : ""}<a href="${esc(c.listing_url)}" target="_blank" rel="noopener">${esc(c.title)}</a>${c.is_new ? '<span class="newchip" title="New since the last refresh">NEW</span>' : ""}<div class="vin">${esc(c.vin)}${guideLink(c)}</div>
      ${c.needs_call ? `<div class="small">Ask about: ${esc(c.needs_call)}</div>` : ""}${c.notes ? `<div class="small">${esc(c.notes)}</div>` : ""}
      <button type="button" class="favbtn" data-vin="${esc(c.vin)}" aria-pressed="${fav.includes(c.vin)}">${fav.includes(c.vin) ? "&#9829; Saved" : "&#9825; Save"}</button><button type="button" class="cmpbtn" data-vin="${esc(c.vin)}" aria-pressed="${cmp.includes(c.vin)}">${cmp.includes(c.vin) ? "✓ Comparing" : "+ Compare"}</button><button type="button" class="disbtn" data-vin="${esc(c.vin)}" aria-pressed="${dis.includes(c.vin)}">${dis.includes(c.vin) ? "&#10005; Disliked" : "Dislike"}</button></td>
    <td class="num p-year" data-l="Year">${esc(c.year)}</td>
    <td class="span2" data-l="Dealer">${esc(c.dealer)}<div class="small">${esc(c.distance_mi)} mi</div><div class="small">${esc(c.cpo_program)}</div></td>
    <td class="num p-price" data-l="Price">${priceCell(c)}${c.fees_estimated === "True" ? '<div class="small">fees est.</div>' : ""}</td>
    <td class="num" data-l="Original price">${origCell(c)}</td><td class="num" data-l="Sticker when new">${msrpCell(c)}</td><td class="num" data-l="Miles">${num(c.mileage) == null ? "?" : Math.round(num(c.mileage)).toLocaleString()}</td>
    <td data-l="Fuel">${esc(c.fuel)}</td><td data-l="Drive">${esc(c.drive)}</td>
    <td class="num" data-l="MPG">${num(c.mpg_combined) == null ? (c.fuel_type === "ev" ? '—<div class="small">electric</div>' : "?") : Math.round(num(c.mpg_combined))}<div class="small">${num(c.mpg_city) != null ? Math.round(num(c.mpg_city)) + "/" + Math.round(num(c.mpg_hwy)) : ""}${c.fuel_type === "phev" ? " gas" : ""}${c.mpg_source === "EPA" ? " EPA" : c.mpg_source === "guide" ? " trim guide" : ""}</div></td>
    <td class="wide" data-l="Colors">${esc(c.colors)}</td><td data-l="Sunroof">${esc(roofOf(c).v)}${roofOf(c).t ? `<div class="small">${esc(roofOf(c).t)}</div>` : ""}</td><td data-l="Upgraded sound">${esc(soundOf(c).v)}${soundOf(c).t ? `<div class="small">${esc(soundOf(c).t)}</div>` : ""}</td><td data-l="Seats">${esc(seatOf(c).v)}${seatOf(c).t ? `<div class="small">${esc(seatOf(c).t)}</div>` : ""}</td>
    <td class="num" data-l="Ground clearance">${num(c.clearance) == null ? "?" : num(c.clearance).toFixed(1) + " in" + (c.clearance_src ? `<div class="small">${esc(c.clearance_src)}</div>` : "")}</td>
    <td class="num" data-l="Electric range">${num(c.ev_range) != null ? Math.round(num(c.ev_range)) + " mi" + (c.ev_range_src ? `<div class="small">${esc(c.ev_range_src)}</div>` : "") : (c.fuel_type === "ev" || c.fuel_type === "phev" ? "?" : "—")}</td>
    <td class="${esc(c.carfax_status)}" data-l="CARFAX">${esc({clean:"no accidents", accident:"accident", not_verified:"not verified"}[c.carfax_status] || c.carfax_status)}</td>
    <td class="num p-mo" data-l="Est./mo">${fmt$(c.est_monthly_cost)}</td><td class="warr wide" data-l="Warranty (estimated)">${c.warr_html}</td><td class="small wide" data-l="First seen">${esc(c.first_seen)}</td></tr>`).join("")
    || `<tr><td colspan="20" class="muted">${favOnly && !fav.some(v => D.cars.some(c => c.vin === v)) ? "No favorites yet. Tap &#9825; Save on a car in the Available tab." : "No cars match these filters."}</td></tr>`;
  // how many cars these filters leave, out of how many on this tab
  const totA = favOnly ? D.cars.filter(c => fav.includes(c.vin)).length : D.cars.length;
  const shownLine = (n, tot, what) => !tot ? "" : n === tot ? `Showing all ${tot} ${what}`
    : `Showing ${n} of ${tot} ${what} <button type="button" class="clear" data-clearall>Clear filters</button>`;
  document.getElementById("shown-a").innerHTML = shownLine(cars.length, totA, favOnly ? "favorites" : "cars");
  document.getElementById("shown-g").innerHTML = shownLine(gone.length, D.gone.length, "cars");
  document.getElementById("shown-f").textContent = cars.length === totA ? "" : `${cars.length} of ${totA} shown`;
  if (favOnly) {
    const gf = D.gone.filter(c => fav.includes(c.vin));
    document.getElementById("fav-gone").innerHTML = gf.length ? `<div class="small"><b>Favorites that are no longer available:</b></div><ul>${gf.map(c =>
      `<li><a href="${esc(c.listing_url)}" target="_blank" rel="noopener">${esc(c.title)}</a> at ${esc(c.dealer)}, last ${fmt$(c.price_total)}, gone since ${esc(c.removed_on || c.last_seen)}</li>`).join("")}</ul>` : "";
  }
}
document.querySelectorAll("th[data-k]").forEach(th => th.addEventListener("click", () => {
  const k = th.dataset.k; dir = sortK === k ? -dir : (k === "score" || k === "year" || k === "warr_end" ? -1 : 1); sortK = k; render(); }));
document.querySelectorAll("th[data-g]").forEach(th => th.addEventListener("click", () => {
  const k = th.dataset.g; gDir = gK === k ? -gDir : (/_(seen|on)$/.test(k) ? -1 : 1); gK = k; render(); }));
// Keep each table's header row visible at the top of the screen while its rows scroll past.
// (CSS position:sticky can't do this here: the table sits in a sideways-scrolling box for phones.)
const safeTop = () => { const el = document.getElementById("safe-top"); return el ? el.getBoundingClientRect().height : 0; };
function stickHeads() {
  const top = safeTop();
  document.querySelectorAll(".wrap").forEach(w => {
    const head = w.querySelector("thead");
    if (!head || w.offsetParent === null || head.offsetParent === null) return;   // hidden tab, or phone card view
    const r = w.getBoundingClientRect(), h = head.getBoundingClientRect().height;
    const off = Math.max(0, Math.min(top - r.top, r.height - h * 2));
    head.classList.toggle("stuck", off > 0);
    head.querySelectorAll("th").forEach(th => { th.style.transform = off > 0 ? `translateY(${off}px)` : ""; });
  });
}
window.addEventListener("scroll", stickHeads, {passive: true});
const toTop = document.getElementById("totop");
const showTop = () => toTop.classList.toggle("show", window.scrollY > 600);
window.addEventListener("scroll", showTop, {passive: true}); showTop();
toTop.addEventListener("click", () => window.scrollTo({top: 0,
  behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"}));
window.addEventListener("resize", stickHeads);
function showTab(which) {
  favOnly = which === "fav";
  const panel = favOnly ? "avail" : which;
  ["avail", "fav", "gone", "cmp", "guide", "check"].forEach(t => document.getElementById("tab-" + t).setAttribute("aria-selected", String(t === which)));
  ["avail", "gone", "cmp", "guide", "check"].forEach(t => document.getElementById("panel-" + t).hidden = t !== panel);
  document.getElementById("fav-extra").hidden = !favOnly;
  render();
  document.querySelector(".filters").hidden = which === "guide" || which === "cmp" || which === "check";   // car filters don't apply there
  document.getElementById("footnote").hidden = which === "guide" || which === "check";
  if (which === "cmp") renderCompare();
  try { localStorage.setItem(PK + "tab", which); } catch (e) {}
  stickHeads();
}
document.getElementById("tab-avail").addEventListener("click", () => showTab("avail"));
document.getElementById("tab-gone").addEventListener("click", () => showTab("gone"));
document.getElementById("tab-guide").addEventListener("click", () => showTab("guide"));
document.getElementById("tab-cmp").addEventListener("click", () => showTab("cmp"));
document.getElementById("tab-fav").addEventListener("click", () => showTab("fav"));
document.getElementById("tab-check").addEventListener("click", () => showTab("check"));
renderGuide(); renderWarranty(); renderCheck(); pullChecked();
try { const t = location.hash.slice(1) || localStorage.getItem(PK + "tab"); if (t === "favorites") showTab("fav"); else if (["gone", "guide", "cmp", "fav", "check"].includes(t)) showTab(t); } catch (e) {}
// Phone card view has no column headers to tap, so it sorts with a menu instead.
document.getElementById("sort-a").addEventListener("change", e => { const [k, d] = e.target.value.split(":"); sortK = k; dir = +d; render(); });
document.getElementById("sort-g").addEventListener("change", e => { const [k, d] = e.target.value.split(":"); gK = k; gDir = +d; render(); });
document.getElementById("nnew").textContent = D.cars.filter(c => c.is_new).length;
document.getElementById("ncut").textContent = document.getElementById("ncut-tile").textContent = D.cars.filter(c => c.dropped).length;
// turning on "Price cut" (the filter or the tile at the top) also sorts biggest cut first
const sortByCut = () => { sortK = "cut"; dir = -1; const sa = document.getElementById("sort-a"); if (sa) sa.value = "cut:-1"; };
document.getElementById("only-cut").addEventListener("change", e => { if (e.target.checked) { sortByCut(); render(); } });
document.getElementById("cut-tile").addEventListener("click", () => {
  const box = document.getElementById("only-cut"); box.checked = !box.checked;
  if (box.checked) { sortByCut(); showTab("avail"); }
  render(); document.getElementById("shown-a").scrollIntoView({behavior: "smooth", block: "start"}); });
["q", "f-show", "f-make", "f-fuel", "f-year", "f-body", "f-drive", "f-roof", "f-sound", "f-seat", "f-mine", "f-new"].forEach(id => document.getElementById(id).addEventListener("input", render));
[pmin, pmax].forEach(el => el.addEventListener("input", () => { showPrice(); render(); }));
[mmin, mmax].forEach(el => el.addEventListener("input", () => { showMiles(); render(); }));
document.addEventListener("click", e => { if (e.target.closest("[data-clearall]")) document.getElementById("clear").click(); });
document.addEventListener("click", e => {      // the green check: a tap shows "Features verified by window sticker"
  const b = e.target.closest(".stickerok");
  document.querySelectorAll(".stickerok.open").forEach(x => { if (x !== b) x.classList.remove("open"); });
  if (b) b.classList.toggle("open");
});
document.getElementById("clear").addEventListener("click", () => {
  document.querySelectorAll(".filters input[type=checkbox]").forEach(i => i.checked = false);
  document.getElementById("q").value = ""; resetPrice(); resetMiles(); clearS.reset(); rangeS.reset(); render(); });
// MPG missing (fueleconomy.gov's robots.txt often can't be read, so the search stays off it): the Trim guide's
// EPA figure for this trim ("city/hwy/combined"), when every trim the car could be agrees
function mpgFromGuide(c) {
  if (num(c.mpg_combined) != null || c.fuel_type === "ev") return;
  const r = guideCall(c, t => { const m = String(t.mpg || "").match(/^(\d+)\/(\d+)\/(\d+)/);
    return m ? {v: m[3], t: m[1] + "/" + m[2]} : {v: "Not sure", t: ""}; });
  if (!r) return;
  c.mpg_combined = r.v; c.mpg_source = "guide";
  const ch = /^(\d+)\/(\d+)$/.exec(r.t || ""); if (ch) { c.mpg_city = ch[1]; c.mpg_hwy = ch[2]; }
}
D.cars.forEach(c => { mpgFromGuide(c); soundOf(c); seatOf(c); roofOf(c); });   // fills MPG gaps and c.snd / c.seat / c.roof for sorting
render();
stickHeads();

// Welcome animation: an SUV drives across the top once, laying tire marks that fade away.
(function drive() {
  try {
    if (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const wrap = document.createElement("div"); wrap.id = "drive"; wrap.setAttribute("aria-hidden", "true");
    // compact luxury SUV in side view, facing right (direction of travel): short hood, raked windshield,
    // roofline sloping to an angled tailgate, roof rails, dark lower cladding, big wheels
    wrap.innerHTML = `<canvas></canvas><svg class="car" viewBox="0 0 150 64">
      <rect x="31" y="8.6" width="44" height="2" rx="1" fill="var(--fg)" opacity=".55"/>
      <path fill="currentColor" d="M8 50 L7 38 Q7 30 12 26 L18 20 Q24 14 34 13 L76 12 Q84 12 90 16 L104 25 L132 28 Q142 30 144 35 L145 45 Q145 50 141 50 L130 50 A14 14 0 0 0 102 50 L48 50 A14 14 0 0 0 20 50 Z"/>
      <path fill="var(--fg)" opacity=".28" d="M8 44 L20 44 A14 14 0 0 1 48 44 L102 44 A14 14 0 0 1 130 44 L145 44 L145 46 Q145 50 141 50 L130 50 A14 14 0 0 0 102 50 L48 50 A14 14 0 0 0 20 50 L8 50 Z"/>
      <path fill="var(--bg)" opacity=".85" d="M21 25 Q25 17 33 16 L44 16 L44 25 Z M48 16 L72 16 L72 25 L48 25 Z M76 16 Q83 16 88 19 L97 25 L76 25 Z"/>
      <path d="M46 16 L46 25 M74 16 L74 25" stroke="currentColor" stroke-width="2"/>
      <rect x="135" y="30" width="9" height="3" rx="1.5" fill="#f6d36b"/>
      <rect x="7" y="29" width="5" height="4" rx="1.5" fill="#d9534f"/>
      <g class="wheel"><circle cx="34" cy="50" r="11" fill="var(--fg)"/><circle cx="34" cy="50" r="7" fill="var(--muted)"/><circle cx="34" cy="50" r="2.5" fill="var(--fg)"/><rect x="33" y="43" width="2" height="14" fill="var(--fg)"/><rect x="27" y="49" width="14" height="2" fill="var(--fg)"/></g>
      <g class="wheel"><circle cx="116" cy="50" r="11" fill="var(--fg)"/><circle cx="116" cy="50" r="7" fill="var(--muted)"/><circle cx="116" cy="50" r="2.5" fill="var(--fg)"/><rect x="115" y="43" width="2" height="14" fill="var(--fg)"/><rect x="109" y="49" width="14" height="2" fill="var(--fg)"/></g>
    </svg>`;
    document.body.appendChild(wrap);
    const cv = wrap.querySelector("canvas"), car = wrap.querySelector(".car"), ctx = cv.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const size = () => { cv.width = innerWidth * dpr; cv.height = 150 * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); };
    size();
    const mark = getComputedStyle(document.documentElement).getPropertyValue("--fg").trim() || "#222";
    const W = innerWidth, start = -170, end = W + 20, dur = Math.max(2200, W * 1.6), fade = 1800;
    const groundY = 44 + 61;                       // where the tires meet the "road"
    let t0 = null, lastX = null;
    function frame(t) {
      if (t0 === null) t0 = t;
      const el = t - t0, p = Math.min(1, el / dur);
      const ease = p < .5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
      const x = start + (end - start) * ease;
      const bob = Math.sin(el / 70) * 0.8;
      car.style.transform = `translate(${x}px, ${bob}px)`;
      // fade old marks a little every frame
      ctx.globalCompositeOperation = "destination-out";
      ctx.fillStyle = "rgba(0,0,0,0.035)";
      ctx.fillRect(0, 0, W, 150);
      ctx.globalCompositeOperation = "source-over";
      if (p < 1 && lastX !== null) {
        ctx.strokeStyle = mark; ctx.globalAlpha = 0.45; ctx.lineCap = "round";
        for (const [wx, off, lw] of [[34, 0, 3.5], [116, 0, 3.5], [34, 4, 1.5], [116, 4, 1.5]]) {
          ctx.lineWidth = lw; ctx.beginPath();
          ctx.moveTo(lastX + wx, groundY + off); ctx.lineTo(x + wx, groundY + off); ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }
      lastX = x;
      if (el < dur + fade) requestAnimationFrame(frame); else wrap.remove();
    }
    requestAnimationFrame(frame);
  } catch (e) { document.getElementById("drive")?.remove(); }
})();
</script></body></html>
"""
