"""One refresh: scrape every dealer, verify, filter, score, and diff against last run."""
from __future__ import annotations

import csv
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from scrapers import audi_network, dealer_com, dealer_inspire, dealeron, playwright_fallback
from scrapers.base import CONFIG, FetchError, fetcher
from scrapers.brand_feeds import FEEDS
from scrapers.generic_jsonld import discover_from_sitemaps, fetch_vdp
from scrapers.listing import Listing

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
    seconds: float = 0.0


def load_dealers() -> list[dict]:
    with (DATA / "dealers.csv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


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


def scrape_dealer(dealer: dict) -> DealerResult:
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
    res.method = note
    res.candidates = len(cands)
    if not cands:
        res.status = "success"
        res.reason = f"no matching {dealer['brand']} models listed ({note})"
        res.seconds = time.time() - t0
        return res
    for url in cands[:MAX_VDPS]:
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
    if res.parsed or not res.errors:
        res.status = "success"
        res.reason = f"{res.parsed} listings read from {res.candidates} candidates"
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
        except (FetchError, KeyError, ValueError) as e:
            stats[brand] = {"status": "failed", "reason": str(e)[:200]}
            log(f"  {brand} brand feed FAILED: {e}")
    return out, stats


def scrape_all(dealers: list[dict], brands: set[str], workers: int, log) -> list[DealerResult]:
    results: list[DealerResult] = []
    todo = []
    for d in dealers:
        if brands and d["brand"] not in brands:
            continue
        if d["brand"] in FEEDS:
            results.append(DealerResult(dealer=d, status="skipped",
                                        reason=f"covered by the {d['brand']} brand CPO feed"))
            continue
        todo.append(d)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(scrape_dealer, d): d for d in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
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
            filled = sum(1 for v in (x.price, x.mileage, x.ext_color, x.int_color, x.sunroof, x.trim) if v not in (None, ""))
            return (same_brand, filled)
        if rank(L) > rank(cur):
            best[L.vin] = L
    return list(best.values())


def location_check(L: Listing) -> str:
    loc = (L.location_note or "").strip()
    if loc and L.dealer and re.sub(r"[^a-z]", "", loc.lower()) not in re.sub(r"[^a-z]", "", L.dealer.lower()):
        if len(loc) < 60 and not re.search(r"\d{5}|call|contact", loc, re.I):
            return f"car is at {loc}"
    return ""
