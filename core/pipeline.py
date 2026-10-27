"""One refresh: scrape every dealer, verify, filter, score, and diff against last run."""
from __future__ import annotations

import csv
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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


def manual_gone() -> dict[str, str]:
    """Cars the user marked 'No longer available' on the page's Added by you tab ({VIN: date}), read from the
    published site (functions/api/mine.js). Empty when the site can't be reached (then nothing changes)."""
    import requests
    from scrapers.base import CONFIG, SCRAPE
    url = ((CONFIG.get("publish") or {}).get("site_url") or "").rstrip("/")
    if not url:
        return {}
    try:
        r = requests.get(url + "/api/mine", headers={"User-Agent": SCRAPE["user_agent"]}, timeout=20)
        r.raise_for_status()
        return {v.upper(): d for v, d in (r.json().get("gone") or {}).items()}
    except Exception as e:      # noqa: BLE001
        print(f"  (couldn't read the cars you marked gone on the page: {type(e).__name__})")
        return {}


def load_manual() -> list[Listing]:
    """Cars the user added by hand from a dealer listing the search can't read (data/manual_listings.csv:
    the dealer's own page, price, fees, miles, colors). They go through the same rules as every other car,
    every run; delete a row when the car is sold."""
    path = DATA / "manual_listings.csv"
    if not path.exists():
        return []
    dealers = {d["dealer_name"]: d for d in load_dealers()}
    num = lambda v: float(v) if (v or "").strip() else None
    out = []
    for r in csv.DictReader(path.open(encoding="utf-8")):
        if not (r.get("vin") or "").strip():
            continue
        d = dealers.get(r["dealer"], {})
        L = Listing(vin=r["vin"].strip().upper(), dealer=r["dealer"], dealer_brand=d.get("brand") or r["make"],
                    dealer_url=d.get("homepage", ""), listing_url=r["listing_url"].strip(), source="added by you",
                    title=f'{r["year"]} {r["make"]} {r["model"]} {r["trim"]}'.strip(), year=int(r["year"]),
                    make=r["make"], model=r["model"], trim=r["trim"], condition="used",
                    price=num(r["price"]), doc_fee=num(r["doc_fee"]), other_fees=num(r["other_fees"]),
                    mileage=int(float(r["mileage"])) if r["mileage"] else None,
                    ext_color=r["ext_color"], int_color=r["int_color"],
                    sunroof={"yes": True, "no": False}.get((r.get("sunroof") or "").strip().lower()),
                    cert_text=f'url:certified; title:certified; {r.get("cert_text") or ""}'.strip("; "),
                    link_note="")
        out.append(L)
    return out


# A parked "domain for sale" page instead of a dealer site (seen Oct 2026: 15 researched addresses were
# GoDaddy parking pages that redirect to /lander and have a one-URL sitemap).
PARKED_PAGE = re.compile(r"""location\.href\s*=\s*["']/lander|forsale\.godaddy|this domain (?:is|may be) for sale|"""
                         r"""domain is parked|sedoparking|parkingcrew|bodis\.com""", re.I)
TINY_SITEMAP = 20       # a dealer's sitemap lists hundreds of pages; fewer than this isn't a dealer site


def homepage_status(home: str) -> tuple[bool, str]:
    for wait in (15, None):
        try:
            r = fetcher().get(home.rstrip("/") + "/")
            break
        except FetchError as e:
            # a broken connection gets one more try (Oct 24 2026: a few minutes without a working connection
            # wrote off ~30 dealers, and feed cars at 'blocked' dealers lost their sunroof/sound/seat details)
            if wait and re.search(r"SSLError|ConnectionError|ConnectTimeout|ReadTimeout|ProxyError", str(e)):
                time.sleep(wait)
                continue
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


# Listing URL -> VIN, kept between runs (data/cache, gitignored). Some sites list one car under two URLs (e.g. a
# /certified/ and a /used/ page with no VIN in the address); last run's row keeps only one of them, so without this the
# other URL was re-read every run (Long Beach BMW: 115 pages read for 52 cars, Oct 23 2026).
URL_VINS_FILE = ROOT / "data" / "cache" / "url_vins.json"
_url_vins: dict[str, str] = {}
_url_vins_lock = threading.Lock()


def load_url_vins() -> None:
    try:
        _url_vins.update(json.loads(URL_VINS_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def save_url_vins() -> None:
    import os
    with _url_vins_lock:
        URL_VINS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = URL_VINS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_url_vins), encoding="utf-8")
        os.replace(tmp, URL_VINS_FILE)


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
        prev = prev_rows.get(url) or prev_rows.get(url_vin(url) or _url_vins.get(url) or "-")
        if prev and all(r.get("dealer") == dealer["dealer_name"] and carry_forward_ok(r, today) for r in prev.values()):
            res.carried.append(prev)
            continue
        try:
            L, err = fetch_vdp(url)
        except Exception as e:     # one odd page: note it and keep reading this dealer's other cars
            L, err = None, f"page error: {type(e).__name__}: {e}"[:150]
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
        if L.vin:
            with _url_vins_lock:
                _url_vins[url] = L.vin.upper()
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
    try:
        P, err = fetch_vdp(L.listing_url)
    except Exception:   # one odd page must not stop the run: the car keeps what its brand feed said
        return
    if P is None:
        L.location_note = L.location_note or ""
        return
    if P.vin and P.vin.upper() != L.vin.upper():
        return      # e.g. a dealer search page showing other cars: take nothing from it
    if "catcher.esl" in L.listing_url and P.listing_url and "catcher.esl" not in P.listing_url:
        L.listing_url = P.listing_url   # feeds now hand out dealer.com's redirect address; keep the page it leads to
    for attr in ("sunroof", "sunroof_note", "audio", "leather", "ventilated_seats", "spare_tire", "spare_note",
                 "third_row", "carfax_badges", "carfax_status", "cpo_warranty_terms", "doc_fee", "other_fees",
                 "seats", "msrp_new", "features", "ground_clearance_in"):
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
    """Every brand feed at once (each is a different website, so politeness per site is unchanged)."""
    todo = {b: fn for b, fn in FEEDS.items() if not brands or b in brands}
    got: dict[str, tuple] = {}

    def one(brand):
        try:
            ls, st = todo[brand]()
            log(f"  {brand} brand feed: {st['in_area']} certified {brand} listings at our dealers")
            return ls, {"status": "success", **st}
        except Exception as e:  # a feed that breaks must not stop the run; its dealer sites get read instead
            log(f"  {brand} brand feed FAILED: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
            return [], {"status": "failed", "reason": f"{type(e).__name__}: {e}"[:200]}
    with ThreadPoolExecutor(max_workers=max(1, len(todo))) as ex:
        for brand, res in zip(todo, ex.map(one, todo)):
            got[brand] = res
    out, stats = [], {}
    for brand in todo:                 # FEEDS order, so results don't depend on which feed finished first
        out += got[brand][0]
        stats[brand] = got[brand][1]
    return out, stats


def expected_pages() -> dict[str, int]:
    """Listing pages each dealer needed last run (from coverage.csv), so the slowest dealers can start first."""
    out = {}
    try:
        with (ROOT / "data" / "coverage.csv").open(encoding="utf-8") as fh:
            for c in csv.DictReader(fh):
                m = re.match(r"(\d+) listings read", c.get("reason") or "")
                out[c["dealer"]] = int(m.group(1)) if m else 0
    except OSError:
        pass
    return out


def dealer_jobs(dealers: list[dict], brands: set[str], covered: set[str]) -> tuple[list[dict], list[DealerResult]]:
    """(dealers to read, biggest first; 'skipped' results for brands a brand feed covers)."""
    from core.profiles import BRANDS
    todo, skipped = [], []
    for d in dealers:
        if brands and d["brand"] not in brands:
            continue
        if d["brand"] not in BRANDS:
            continue    # no buyer has a model from this brand yet (Acura, Oct 2026): nothing to look for
        if d["brand"] in covered:
            skipped.append(DealerResult(dealer=d, status="skipped", reason=f"covered by the {d['brand']} brand CPO feed"))
            continue
        todo.append(d)
    pages = expected_pages()
    todo.sort(key=lambda d: -pages.get(d["dealer_name"], 20))   # a dealer not seen before counts as middling
    return todo, skipped


class DealerPool:
    """Dealer sites read `workers` at a time; more dealers can be added while it runs (e.g. a brand whose feed
    just failed). Each site still gets at most 1 request every 2-3 s (the fetcher's per-site throttle)."""

    def __init__(self, workers: int, log, prev_rows: dict | None, today: str):
        self.ex = ThreadPoolExecutor(max_workers=workers)
        self.log, self.prev_rows, self.today = log, prev_rows, today
        self.futs: dict = {}
        self.results: list[DealerResult] = []
        self.lock = threading.Lock()
        self.done = 0

    def add(self, dealers: list[dict]) -> None:
        for d in dealers:
            f = self.ex.submit(scrape_dealer, d, self.prev_rows, self.today)
            with self.lock:
                self.futs[f] = d
            f.add_done_callback(self._finished)

    def _finished(self, fut) -> None:
        d = self.futs[fut]
        try:
            r = fut.result()
        except Exception as e:  # report it in the coverage report and keep going
            r = DealerResult(dealer=d, reason=f"error: {type(e).__name__}: {e}"[:200])
        with self.lock:
            self.results.append(r)
            self.done += 1
            i, n = self.done, len(self.futs)
        mark = "ok " if r.status == "success" else "-- "
        self.log(f"  [{i}/{n}] {mark}{r.dealer['brand']:13} {r.dealer['dealer_name'][:34]:34} {r.reason[:90]}")

    def finish(self) -> list[DealerResult]:
        self.ex.shutdown(wait=True)
        return self.results


def scrape_all(dealers: list[dict], brands: set[str], workers: int, log, prev_rows: dict | None = None,
               today: str = "", covered: set[str] | None = None) -> list[DealerResult]:
    """`covered`: brands whose brand feed worked this run; their dealer sites are skipped. A brand whose
    feed failed (or needs the browser add-on that isn't installed) gets its dealer sites read instead."""
    covered = set(FEEDS) if covered is None else covered
    todo, skipped = dealer_jobs(dealers, brands, covered)
    pool = DealerPool(workers, log, prev_rows, today)
    pool.add(todo)
    return skipped + pool.finish()


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
