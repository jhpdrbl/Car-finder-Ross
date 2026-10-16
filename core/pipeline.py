"""One refresh: scrape every dealer, verify, filter, score, and diff against last run."""
from __future__ import annotations

import csv
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from scrapers import audi_network, dealer_com, dealer_inspire, dealeron, playwright_fallback
from core.profiles import could_want
from scrapers.base import CONFIG, FetchError, fetcher
from scrapers.brand_feeds import FEEDS
from scrapers.generic_jsonld import discover_from_sitemaps, fetch_vdp
from scrapers.listing import URL_SKIP, Listing, norm_url_text, url_vin

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MAX_VDPS = CONFIG["scrape"]["max_vdps_per_dealer"]


@dataclass
class DealerResult:
    dealer: dict
    status: str = "failed"        # success / failed / skipped
    reason: str = ""
    method: str = ""
    candidates: int = 0
    parsed: int = 0
    errors: list[str] = field(default_factory=list)
    listings: list[Listing] = field(default_factory=list)
    gone: list[tuple[str, str]] = field(default_factory=list)   # (url, reason): sold/removed pages
    carried: list[dict] = field(default_factory=list)           # previous rows reused without re-reading: {profile: row}
    skipped_pages: int = 0                                       # dropped by URL / VIN pre-filter
    seconds: float = 0.0


def load_dealers() -> list[dict]:
    with (DATA / "dealers.csv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# A parked "domain for sale" page instead of a dealer site (seen Oct 2026: 15 researched addresses were
# GoDaddy parking pages that redirect to /lander and have a one-URL sitemap).
PARKED_PAGE = re.compile(r"""location\.href\s*=\s*["']/lander|forsale\.godaddy|this domain (?:is|may be) for sale|"""
                         r"""domain is parked|sedoparking|parkingcrew|bodis\.com""", re.I)
TINY_SITEMAP = 20       # a dealer's sitemap lists hundreds of pages; fewer than this isn't a dealer site


def homepage_status(home: str) -> tuple[bool, str]:
    try:
        r = fetcher().get(home + "/")
    except FetchError as e:
        return False, f"homepage unreachable ({str(e)[:80]})"
    if r.status_code in (401, 403, 429, 503) or (r.status_code >= 500):
        body = r.text[:4000].lower()
        why = ("Cloudflare bot protection" if "cloudflare" in body else
               "Akamai bot protection" if "access denied" in body or "edgesuite" in body else
               "site says unavailable" if "not available" in body else f"HTTP {r.status_code}")
        return False, f"blocked: {why} (HTTP {r.status_code})"
    if r.status_code >= 400:
        return False, f"homepage HTTP {r.status_code}"
    from scrapers.generic_jsonld import CHALLENGE_PAGE
    if CHALLENGE_PAGE.search(r.text[:5000]):
        return False, "blocked: bot challenge page (HTTP 200)"
    if PARKED_PAGE.search(r.text[:5000]) or PARKED_PAGE.search(r.url or ""):
        return False, "wrong website address: parked 'domain for sale' page, not a dealer site"
    return True, ""


def discover(dealer: dict) -> tuple[list[str], str]:
    """Find candidate VDP URLs with the best method for this dealer's platform."""
    home, brand, plat, inv = dealer["homepage"], dealer["brand"], dealer["platform"], dealer.get("inventory_url", "")
    notes = []
    cands: list[str] = []
    if plat == "dealer_com":
        c, n = dealer_com.discover(home, brand, inv)
        cands += c
        notes.append(n)
    elif plat == "dealeron":
        c, n = dealeron.discover(home, brand, inv)
        cands += c
        notes.append(n)
    elif plat == "dealer_inspire" or "llm/inventory" in dealer.get("notes", ""):
        c, n = dealer_inspire.discover(home, brand)
        cands += c
        notes.append(n)
    elif brand == "Audi" and plat == "unknown":
        c, n = audi_network.discover(home, brand, inv)
        cands += c
        notes.append(n)
    if not cands:
        c, n = discover_from_sitemaps(home, brand)
        cands += c
        notes.append(n)
    if not cands and playwright_fallback.available() and not (brand == "Audi" and plat == "unknown"):
        c, n = playwright_fallback.discover_by_browsing(home, brand, inv)
        cands += c
        notes.append(n)
    return list(dict.fromkeys(cands)), "; ".join(x for x in notes if x)


# A fail reason that can't change while the car is listed (color, model, trim, drivetrain, rows,
# mileage only goes up). Price, certification and CARFAX can change, so those cars get re-read.
CHANGEABLE = re.compile(r"over the|certif|carfax|manually|new vehicle|\bEV\b|exceptional|blue advantage", re.I)
PRICE_RECHECK_DAYS = 2


def carry_forward_ok(prev: dict, today: str) -> bool:
    """Reuse last run's row instead of re-reading the page?"""
    if not prev or prev.get("status") != "excluded":
        return False
    reasons = [r for r in (prev.get("fail_reasons") or "").split("; ") if r]
    if any(not CHANGEABLE.search(r) for r in reasons):
        return True                                   # at least one permanent reason
    if reasons and all("over the" in r for r in reasons):  # only the price: re-check every couple of days
        last = prev.get("last_read") or prev.get("last_seen") or ""
        try:
            from datetime import date
            return (date.fromisoformat(today) - date.fromisoformat(last)).days < PRICE_RECHECK_DAYS
        except ValueError:
            return False
    return False


def prefilter(cands: list[str], brand: str) -> tuple[list[str], int]:
    """Drop listing URLs we know are off-list before reading them: by URL words, then by VIN decode."""
    from verify.vin_decode import decode_many, fuel_class
    keep = [u for u in cands if not URL_SKIP.search(norm_url_text(u))]
    vins = {u: url_vin(u) for u in keep}
    known = decode_many([v for v in vins.values() if v]) if any(vins.values()) else {}
    out = []
    for u in keep:
        d = known.get(vins[u]) or {}
        if d:   # skip what no buyer wants: an Audi A4 behind a model-less ?vehicleId= link, a gas RAV4 for a hybrid-only buyer...
            year = int(d["ModelYear"]) if (d.get("ModelYear") or "").isdigit() else None
            fuel = fuel_class(d) if d.get("ElectrificationLevel") else None   # no electrification data: don't guess
            if not could_want(brand, d.get("Model") or "", year, fuel):
                continue
        out.append(u)
    return out, len(cands) - len(out)


def scrape_dealer(dealer: dict, prev_rows: dict | None = None, today: str = "") -> DealerResult:
    t0 = time.time()
    res = DealerResult(dealer=dealer)
    home = dealer["homepage"]
    if not home:
        res.status, res.reason = "skipped", "no homepage on file"
        return res
    ok, why = homepage_status(home)
    if not ok:
        res.reason = why
        res.seconds = time.time() - t0
        return res
    try:
        cands, note = discover(dealer)
    except Exception as e:  # one dealer's surprise must not stop the run
        res.reason = f"discovery error: {type(e).__name__}: {e}"[:200]
        return res
    found_any = bool(cands)
    cands, res.skipped_pages = prefilter(cands, dealer["brand"])
    res.method = note
    res.candidates = len(cands)
    if not found_any and not playwright_fallback.available():
        # Nothing found without a browser (e.g. on the iPad): the cars may only show up in one, so this
        # is "couldn't see", not "none listed", and the dealer's cars must not be marked sold.
        res.reason = f"couldn't see this site's inventory without the browser add-on ({note})"
        res.seconds = time.time() - t0
        return res
    if not cands and re.search(r"browser blocked|browser: 0 inventory pages|playwright not installed|no sitemap$", note):
        res.reason = f"couldn't see this site's inventory ({note})"   # not the same as "no matching cars"
        res.seconds = time.time() - t0
        return res
    small = re.search(r"sitemap: (\d+) urls", note)
    if not cands and small and int(small.group(1)) < TINY_SITEMAP:
        res.reason = f"wrong website address? its sitemap is too small for a dealer site ({note})"
        res.seconds = time.time() - t0
        return res
    if not cands:
        res.status = "success"
        res.reason = f"no matching {dealer['brand']} models listed ({note})"
        res.seconds = time.time() - t0
        return res
    prev_rows = prev_rows or {}
    for url in cands[:MAX_VDPS]:
        # prev = last run's row for this car per buyer ({profile: row}); reuse only if every buyer excluded it for good
        prev = prev_rows.get(url) or prev_rows.get(url_vin(url) or "-")
        if prev and all(r.get("dealer") == dealer["dealer_name"] and carry_forward_ok(r, today) for r in prev.values()):
            res.carried.append(prev)
            continue
        L, err = fetch_vdp(url)
        if L is None and err.startswith("no vehicle data") and playwright_fallback.available():
            L, err = playwright_fallback.fetch_vdp_rendered(url)
        if L is None:
            if "sold" in err or "gone" in err:
                res.gone.append((url, err))
            else:
                res.errors.append(f"{url}: {err}")
            continue
        L.dealer, L.dealer_brand, L.dealer_url = dealer["dealer_name"], dealer["brand"], home
        L.source = L.source or (dealer["platform"] or "site")
        res.listings.append(L)
    res.parsed = len(res.listings)
    if res.parsed or res.carried or not res.errors:
        res.status = "success"
        res.reason = f"{res.parsed} listings read, {len(res.carried)} unchanged exclusions reused"
        if res.errors:
            res.reason += f"; {len(res.errors)} pages failed"
    else:
        res.reason = f"all {len(res.errors)} listing pages failed (e.g. {res.errors[0][-80:]})"
    res.seconds = time.time() - t0
    return res


def enrich_from_dealer_page(L: Listing) -> None:
    """Brand-feed cars: read the dealer's own page (when reachable) for sunroof, audio, seats, CARFAX..."""
    if not L.listing_url:
        return
    P, err = fetch_vdp(L.listing_url)
    if P is None:
        L.location_note = L.location_note or ""
        return
    if P.vin and P.vin.upper() != L.vin.upper():
        return      # e.g. a dealer search page showing other cars: take nothing from it
    for attr in ("sunroof", "sunroof_note", "audio", "leather", "ventilated_seats", "spare_tire", "spare_note",
                 "third_row", "carfax_badges", "carfax_status", "cpo_warranty_terms", "doc_fee", "other_fees"):
        val = getattr(P, attr)
        if val not in (None, "", [], "not_verified"):
            setattr(L, attr, val)
    if P.trim and len(P.trim) > len(L.trim or ""):
        L.trim = P.trim
    if P.price and L.price and abs(P.price - L.price) > 1 and abs(P.price - L.price) / L.price < 0.3:
        L.price = P.price  # the dealer's own page wins (within reason: guards against misread numbers)
    L.features = list(dict.fromkeys(L.features + P.features))[:150]
    if P.listing_url:
        L.listing_url = P.listing_url
        if "search=" not in P.listing_url:
            L.link_note = ""        # landed on the car's own page: a real listing link now


def run_brand_feeds(brands: set[str], log) -> tuple[list[Listing], dict[str, dict]]:
    out, stats = [], {}
    for brand, fn in FEEDS.items():
        if brands and brand not in brands:
            continue
        try:
            ls, st = fn()
            out += ls
            stats[brand] = {"status": "success", **st}
            log(f"  {brand} brand feed: {st['in_area']} certified {brand} listings at our dealers")
        except Exception as e:  # a feed that breaks must not stop the run; its dealer sites get read instead
            stats[brand] = {"status": "failed", "reason": f"{type(e).__name__}: {e}"[:200]}
            log(f"  {brand} brand feed FAILED: {e}")
    return out, stats


def scrape_all(dealers: list[dict], brands: set[str], workers: int, log, prev_rows: dict | None = None,
               today: str = "", covered: set[str] | None = None) -> list[DealerResult]:
    """`covered`: brands whose brand feed worked this run; their dealer sites are skipped. A brand whose
    feed failed (or needs the browser add-on that isn't installed) gets its dealer sites read instead."""
    covered = set(FEEDS) if covered is None else covered
    results: list[DealerResult] = []
    todo = []
    from core.profiles import BRANDS
    for d in dealers:
        if brands and d["brand"] not in brands:
            continue
        if d["brand"] not in BRANDS:
            continue    # no buyer has a model from this brand yet (Acura, Oct 2026): nothing to look for
        if d["brand"] in covered:
            results.append(DealerResult(dealer=d, status="skipped",
                                        reason=f"covered by the {d['brand']} brand CPO feed"))
            continue
        todo.append(d)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(scrape_dealer, d, prev_rows, today): d for d in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                r = fut.result()
            except Exception as e:  # report it in the coverage report and keep going
                r = DealerResult(dealer=futs[fut], reason=f"error: {type(e).__name__}: {e}"[:200])
            results.append(r)
            mark = "ok " if r.status == "success" else "-- "
            log(f"  [{i}/{len(todo)}] {mark}{r.dealer['brand']:13} {r.dealer['dealer_name'][:34]:34} {r.reason[:90]}")
    return results


def dedupe(listings: list[Listing]) -> list[Listing]:
    """Same VIN from two sites (e.g. a group site and the store site): keep the richer record from the franchise brand."""
    best: dict[str, Listing] = {}
    for L in listings:
        cur = best.get(L.vin)
        if cur is None:
            best[L.vin] = L
            continue

        def rank(x: Listing):
            same_brand = (x.make or "").lower().startswith(x.dealer_brand.lower()[:4])
            own_page = not x.link_note          # a real link to the car's own page beats a dealer search link
            filled = sum(1 for v in (x.price, x.mileage, x.ext_color, x.int_color, x.sunroof, x.trim) if v not in (None, ""))
            return (same_brand, own_page, filled)
        keep, other = (L, cur) if rank(L) > rank(cur) else (cur, L)
        if "cpo inventory)" in (other.cert_text or "") and "cpo inventory)" not in (keep.cert_text or ""):
            keep.cert_text = f"{keep.cert_text}; {other.cert_text}".strip("; ")   # keep the brand feed's proof of certification
            keep.cpo_program = keep.cpo_program or other.cpo_program
        best[L.vin] = keep
    return list(best.values())


def location_check(L: Listing) -> str:
    loc = (L.location_note or "").strip()
    if loc and L.dealer and re.sub(r"[^a-z]", "", loc.lower()) not in re.sub(r"[^a-z]", "", L.dealer.lower()):
        junk = re.fullmatch(r"(view )?(details?|directions|map|info|more|location|here|see .*|get .*)", loc, re.I)
        if len(loc) < 60 and not junk and len(loc) > 3 and not re.search(r"\d{5}|call|contact", loc, re.I):
            return f"car is at {loc}"
    return ""
