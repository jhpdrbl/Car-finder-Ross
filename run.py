"""CPO SUV finder.

  python run.py refresh                 scrape everything, write CSVs, digest, dashboard
  python run.py refresh --brands Audi   only some brands (comma-separated)
  python run.py diagnose --brand Audi   record what dealer sites expose (send the report to Claude)
  python run.py dealers                 rebuild data/dealers.csv from the brand dealer locators
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

try:  # Windows consoles default to cp1252; the digest uses emoji
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


def refresh(args) -> None:
    from core import criteria, history, outputs, pipeline
    from verify import recalls, vin_decode

    t0 = time.time()
    today = date.today().isoformat()
    brands = {b.strip() for b in (args.brands or "").split(",") if b.strip()}
    dealers = pipeline.load_dealers()
    if args.dealers:
        want = args.dealers.lower()
        dealers = [d for d in dealers if want in d["dealer_name"].lower()]
    by_name = {d["dealer_name"]: d for d in pipeline.load_dealers()}
    from scrapers import playwright_fallback
    log(f"Refresh {today}: {len(dealers)} dealers"
        + (f", brands {sorted(brands)}" if brands else "")
        + ("" if playwright_fallback.available() else " (Playwright not installed: browser fallback off)"))

    # Reuse last run's rows for cars excluded for permanent reasons, unless the rules changed.
    rules_id = _rules_fingerprint()
    state = _read_state()
    prev_rows: dict = {}
    if args.full:
        log("   --full: re-reading every listing page")
    elif state.get("rules") != rules_id:
        log("   rules changed since the last run: re-reading every listing page this time")
    else:
        hand_checked = set(history.load_confirmed())     # never reuse a row the user has since confirmed facts for
        for r in history.read_csv(history.DATA / "listings.csv"):
            if r["vin"].upper() in hand_checked:
                continue
            prev_rows[r["listing_url"]] = r
            prev_rows[r["vin"]] = r

    log("1/6 Brand certified-inventory feeds")
    feed_listings, feed_stats = pipeline.run_brand_feeds(brands, log) if not args.dealers else ([], {})

    log(f"2/6 Dealer websites ({args.workers} at a time, 1 request per 2-3 s per site)")
    covered = {b for b, st in feed_stats.items() if st.get("status") == "success"}
    results = pipeline.scrape_all(dealers, brands, args.workers, log, prev_rows, today, covered)
    n_read = sum(r.parsed for r in results)
    n_reused = sum(len(r.carried) for r in results)
    n_skip = sum(r.skipped_pages for r in results)
    log(f"   {n_read} listing pages read; {n_reused} unchanged exclusions reused; {n_skip} skipped by URL/VIN pre-filter")

    log("3/6 Reading dealer pages for brand-feed cars (sunroof, audio, CARFAX badges...)")
    from concurrent.futures import ThreadPoolExecutor
    todo = [L for L in feed_listings if args.enrich and (L.year or 0) >= 2023 and (L.mileage or 0) < 40000
            and (L.price or 0) <= 42000]
    homes = sorted({by_name.get(L.dealer, {}).get("homepage", "") for L in todo} - {""})
    with ThreadPoolExecutor(max_workers=16) as ex:        # different dealer sites in parallel; same site still 2-3 s apart
        reachable = dict(zip(homes, ex.map(lambda h: pipeline.homepage_status(h)[0], homes)))
        ok_cars = [L for L in todo if reachable.get(by_name.get(L.dealer, {}).get("homepage", ""))]
        list(ex.map(pipeline.enrich_from_dealer_page, ok_cars))
    n_enriched = len(ok_cars)
    blocked_feed_dealers = sorted(h for h, ok in reachable.items() if not ok)
    log(f"   read {n_enriched} dealer pages; {len(blocked_feed_dealers)} feed dealers' sites blocked")

    log("4/6 VIN decode (NHTSA vPIC) and filters")
    listings = pipeline.dedupe(feed_listings + [L for r in results for L in r.listings])
    decodes = vin_decode.decode_many([L.vin for L in listings])
    for L in listings:
        d = decodes.get(L.vin) or {}
        if L.fuel_type != "ev" or d:
            L.fuel_type = vin_decode.fuel_class(d) if d else (L.fuel_type or "gas")
    excluded = history.load_exclusions()
    confirmed = history.load_confirmed()
    rows = []
    for L in listings:
        dealer = by_name.get(L.dealer, {})
        apply_confirmed(L, confirmed.get(L.vin.upper()))
        fails, unknown, notes = criteria.evaluate(L, decodes.get(L.vin) or {}, dealer, listings, excluded)
        loc = pipeline.location_check(L)
        if loc:
            notes.append(loc)
        if L.vin.upper() in confirmed:
            notes.append("checked by you: " + (confirmed[L.vin.upper()].get("note") or "details confirmed"))
        status = "excluded" if fails else "active"
        flags = []
        if status == "active":
            flags = recalls.campaigns(L.make or (decodes.get(L.vin) or {}).get("Make", ""), L.model, L.year)
            fill_mpg(L)
        r = L.to_dict()
        r.update(status=status, last_read=today, fail_reasons="; ".join(fails), needs_call="; ".join(unknown) if not fails else "",
                 notes="; ".join(notes), recall_flags="; ".join(flags),
                 est_monthly_cost=criteria.monthly_cost(L.price_total) or "",
                 score=criteria.score(L) if not fails else "", distance_mi=dealer.get("distance_mi", ""))
        rows.append({k: ("" if v is None else v) for k, v in r.items()})
    fresh = {r["vin"] for r in rows}
    rows += [dict(c) for r in results for c in r.carried if c["vin"] not in fresh]   # reused exclusions
    n_match = sum(1 for r in rows if r["status"] == "active" and not r["needs_call"])
    n_call = sum(1 for r in rows if r["status"] == "active" and r["needs_call"])
    log(f"   {len(rows)} listings checked: {n_match} meet all criteria, {n_call} need a call")

    log("5/6 Comparing with the last run")
    ok_dealers = {r.dealer["dealer_name"] for r in results if r.status == "success"}
    for brand, st in feed_stats.items():
        if st["status"] == "success":
            ok_dealers |= {d["dealer_name"] for d in by_name.values() if d["brand"] == brand}
    gone = {u: why for r in results for u, why in r.gone}
    all_rows, changes = history.update(rows, ok_dealers, gone, today, run_id=datetime.now().strftime("%Y-%m-%d %H:%M"))

    log("6/6 Writing digest, dashboard, coverage")
    cov = outputs.coverage_rows(results, feed_stats)
    for c in cov:
        if c["homepage"] in blocked_feed_dealers:
            c["reason"] += " (dealer site blocked; cars still covered by the brand feed)"
    history.write_csv(history.DATA / "coverage.csv", cov,
                      ["brand", "dealer", "status", "reason", "listings", "distance_mi", "homepage", "method"])
    digest = outputs.write_digest(all_rows, changes, cov, today)
    dash = outputs.write_dashboard(all_rows, history.read_csv(history.DATA / "price_history.csv"), cov, today)
    _stamp_dealers({r.dealer["dealer_name"] for r in results if r.status == "success"}, today)
    if not args.dealers and not brands:
        _write_state({"rules": rules_id, "last_full_run": today})

    failed = [c for c in cov if c["status"] == "failed"]
    print()
    print("=" * 72)
    print(f"COVERAGE: {sum(c['status'] == 'success' for c in cov)} read, {len(failed)} failed, "
          f"{sum(c['status'] == 'skipped' for c in cov)} skipped (covered by brand feeds)")
    for c in failed:
        print(f"  FAILED  {c['brand']:13} {c['dealer'][:34]:34} {c['reason'][:100]}")
    print(f"RESULTS:  {n_match} meet all criteria · {n_call} need a call · "
          f"{len(changes['new'])} new · {len(changes['price'])} price changes · {len(changes['removed'])} sold/removed")
    print(f"Digest:    {digest}")
    print(f"Dashboard: {dash}")
    print(f"Listings:  {history.DATA / 'listings.csv'}")
    print(f"Done in {(time.time() - t0) / 60:.1f} min")


STATE = Path(__file__).resolve().parent / "data" / "run_state.json"


def _rules_fingerprint() -> str:
    """Changes whenever the criteria change, so reused rows never carry stale decisions."""
    import hashlib
    root = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for f in ("config.yaml", "core/criteria.py", "verify/certification.py", "verify/vin_decode.py",
              "scrapers/generic_jsonld.py"):
        h.update((root / f).read_bytes())
    return h.hexdigest()[:16]


def _read_state() -> dict:
    import json
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    import json
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def apply_confirmed(L, c: dict | None) -> None:
    """Apply what the user confirmed by hand for this VIN (data/confirmed.csv) before the rules run."""
    if not c:
        return
    if c.get("trim"):
        L.trim = c["trim"]
    roof = (c.get("sunroof") or "").strip().lower()
    if roof in ("yes", "no"):
        L.sunroof = roof == "yes"
        L.sunroof_note = "confirmed by you"


def fill_mpg(L) -> None:
    """MPG from the listing when shown, else the EPA rating from fueleconomy.gov."""
    from verify import fuel_economy
    if L.mpg_city and L.mpg_hwy:
        L.mpg_combined = round(0.55 * L.mpg_city + 0.45 * L.mpg_hwy)
        L.mpg_source = "listing"
        return
    epa = fuel_economy.lookup(L.year, L.make, L.model, f"{L.trim} {L.title}", L.fuel_type)
    if epa:
        L.mpg_city, L.mpg_hwy, L.mpg_combined = epa
        L.mpg_source = "EPA"


def _stamp_dealers(names: set[str], today: str) -> None:
    from core import history
    path = history.DATA / "dealers.csv"
    rows = history.read_csv(path)
    if not rows:
        return
    for r in rows:
        if r["dealer_name"] in names:
            r["last_scraped"] = today
    history.write_csv(path, rows, list(rows[0].keys()))


def dealers_cmd(args) -> None:
    from tools import dealer_locator
    rows = dealer_locator.build(args.refresh_raw, args.detect)
    print(f"wrote {len(rows)} dealers to {dealer_locator.DEALERS_CSV}")


def diagnose(args) -> None:
    from tools import diagnose as dg
    path = dg.run(brand=args.brand, platform=args.platform, dealer=args.dealer, limit=args.limit)
    print(f"\nDiagnostic report: {path}\nSend this file to Claude (attach it in the chat).")


def main() -> None:
    ap = argparse.ArgumentParser(description="CPO SUV finder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh", help="run the whole search")
    r.add_argument("--brands", help="comma-separated, e.g. Audi,Subaru")
    r.add_argument("--dealers", help="only dealers whose name contains this text")
    r.add_argument("--workers", type=int, default=24, help="dealer sites scraped in parallel (default 24; each site "
                   "still gets at most 1 request per 2-3 s)")
    r.add_argument("--full", action="store_true", help="re-read every listing page (don't reuse unchanged exclusions)")
    r.add_argument("--no-enrich", dest="enrich", action="store_false", help="skip reading dealer pages for brand-feed cars")
    r.set_defaults(func=refresh)
    d = sub.add_parser("dealers", help="rebuild data/dealers.csv")
    d.add_argument("--refresh-raw", action="store_true")
    d.add_argument("--detect", action="store_true")
    d.set_defaults(func=dealers_cmd)
    g = sub.add_parser("diagnose", help="record what dealer sites expose")
    g.add_argument("--brand")
    g.add_argument("--platform")
    g.add_argument("--dealer")
    g.add_argument("--limit", type=int, default=25)
    g.set_defaults(func=diagnose)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
