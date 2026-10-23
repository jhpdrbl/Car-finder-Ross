"""CPO SUV finder.

  python run.py refresh                 scrape everything, write CSVs, digest, dashboard
  python run.py refresh --brands Audi   only some brands (comma-separated)
  python run.py diagnose --brand Audi   record what dealer sites expose (send the report to Claude)
  python run.py dealers                 rebuild data/dealers.csv from the brand dealer locators
"""
from __future__ import annotations

import argparse
import re
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
    from core import criteria, history, outputs, pipeline, profiles
    from scrapers.brand_feeds import SUPPLEMENT_FEEDS
    from verify import vin_decode

    t0 = time.time()
    today = date.today().isoformat()
    brands = {b.strip() for b in (args.brands or "").split(",") if b.strip()}
    dealers = pipeline.load_dealers()
    if args.dealers:
        want = args.dealers.lower()
        dealers = [d for d in dealers if want in d["dealer_name"].lower()]
    by_name = {d["dealer_name"]: d for d in pipeline.load_dealers()}
    from scrapers import playwright_fallback
    buyers = profiles.all_profiles()
    log(f"Refresh {today}: {len(dealers)} dealers, for {' and '.join(b.label for b in buyers)}"
        + (f", brands {sorted(brands)}" if brands else "")
        + ("" if playwright_fallback.available() else " (Playwright not installed: browser fallback off)"))

    # Reuse last run's rows for cars every buyer excluded for permanent reasons, unless the rules changed.
    rules_id = _rules_fingerprint()
    state = _read_state()
    prev_rows: dict = {}       # listing URL or VIN -> {profile id: last run's row}
    if args.full:
        log("   --full: re-reading every listing page")
    elif state.get("rules") != rules_id:
        log("   rules changed since the last run: re-reading every listing page this time")
    else:
        per = {}
        for P in buyers:
            hand_checked = set(history.load_confirmed(P.data))     # never reuse a row the user has since confirmed facts for
            m = {}
            for r in history.read_csv(P.data / "listings.csv"):
                if r["vin"].upper() not in hand_checked:
                    m[r["listing_url"]] = m[r["vin"]] = r
            per[P.id] = m
        for key in per[buyers[0].id]:
            if all(key in per[P.id] for P in buyers):
                prev_rows[key] = {P.id: per[P.id][key] for P in buyers}

    # The three reading steps overlap (Oct 23 2026: one after another took 45 min). Each website still gets at most
    # 1 request every 2-3 s; what changes is that different websites are read at the same time:
    #   - the brand feeds all at once;
    #   - meanwhile the dealer sites of every brand whose feed can't replace them, biggest dealers first;
    #   - when the feeds are done: the sites of brands whose feed failed, and the feed cars' own dealer pages.
    from concurrent.futures import ThreadPoolExecutor
    log(f"1/4 Brand feeds, dealer websites ({args.workers} at a time) and feed cars' dealer pages, side by side")
    pipeline.load_url_vins()
    wait_for_feed = set() if args.dealers else set(pipeline.FEEDS) - set(SUPPLEMENT_FEEDS)
    first, _ = pipeline.dealer_jobs([d for d in dealers if d["brand"] not in wait_for_feed], brands, set())
    pool = pipeline.DealerPool(args.workers, log, prev_rows, today)
    pool.add(first)
    feed_listings, feed_stats = pipeline.run_brand_feeds(brands, log) if not args.dealers else ([], {})
    covered = {b for b, st in feed_stats.items() if st.get("status") == "success" and b not in SUPPLEMENT_FEEDS}
    later, skipped = pipeline.dealer_jobs([d for d in dealers if d["brand"] in wait_for_feed], brands, covered)
    pool.add(later)               # brands whose feed failed: read their dealer sites instead

    todo = [L for L in feed_listings if args.enrich and (L.year or 0) >= profiles.MIN_YEAR and (L.mileage or 0) < 40000
            and (L.price or 0) <= profiles.MAX_PRICE + 1500]
    homes = sorted({by_name.get(L.dealer, {}).get("homepage", "") for L in todo} - {""})
    with ThreadPoolExecutor(max_workers=16) as ex:        # different dealer sites in parallel; same site still 2-3 s apart
        reachable = dict(zip(homes, ex.map(lambda h: pipeline.homepage_status(h)[0], homes)))
        ok_cars = [L for L in todo if reachable.get(by_name.get(L.dealer, {}).get("homepage", ""))]
        list(ex.map(pipeline.enrich_from_dealer_page, ok_cars))
    n_enriched = len(ok_cars)
    blocked_feed_dealers = sorted(h for h, ok in reachable.items() if not ok)
    log(f"   feed cars: read {n_enriched} dealer pages; {len(blocked_feed_dealers)} feed dealers' sites blocked")

    results = skipped + pool.finish()
    pipeline.save_url_vins()
    n_read = sum(r.parsed for r in results)
    n_reused = sum(len(r.carried) for r in results)
    n_skip = sum(r.skipped_pages for r in results)
    log(f"   dealer sites: {n_read} listing pages read; {n_reused} unchanged exclusions reused; {n_skip} skipped by URL/VIN pre-filter")

    log("2/4 VIN decode (NHTSA vPIC) and filters")
    listings = pipeline.dedupe(feed_listings + [L for r in results for L in r.listings] + pipeline.load_manual())
    decodes = vin_decode.decode_many([L.vin for L in listings])
    prepare(listings, decodes)
    ok_dealers = {r.dealer["dealer_name"] for r in results if r.status == "success"}
    for brand, st in feed_stats.items():
        if st["status"] == "success":
            ok_dealers |= {d["dealer_name"] for d in by_name.values() if d["brand"] == brand}
    gone = {u: why for r in results for u, why in r.gone}
    run_id = datetime.now().strftime("%Y-%m-%d %H:%M")
    per_buyer = {}
    for P in buyers:
        criteria.use(P.cfg)
        excluded = history.load_exclusions(P.data)
        confirmed = history.load_confirmed(P.data)
        rows = []
        for L0 in listings:
            r = evaluate_row(L0, by_name.get(L0.dealer, {}), decodes.get(L0.vin) or {}, listings, excluded, confirmed, today)
            rows.append({k: ("" if v is None else v) for k, v in r.items()})
        fresh = {r["vin"] for r in rows}
        for c in (c for r in results for c in r.carried if P.id in c):    # reused exclusions, one row per car
            if c[P.id]["vin"] not in fresh:
                fresh.add(c[P.id]["vin"])
                rows.append(dict(c[P.id]))
        n_match = sum(1 for r in rows if r["status"] == "active" and not r["needs_call"])
        n_call = sum(1 for r in rows if r["status"] == "active" and r["needs_call"])
        log(f"   {P.label}: {len(rows)} listings checked: {n_match} meet all criteria, {n_call} need a call")
        per_buyer[P.id] = (rows, n_match, n_call)
    criteria.use(profiles.get().cfg)

    log("3/4 Comparing with the last run")
    updated = {}
    for P in buyers:
        updated[P.id] = history.update(per_buyer[P.id][0], ok_dealers, gone, today, run_id=run_id, data=P.data)

    log("4/4 Writing digest, dashboard, coverage")
    cov = outputs.coverage_rows(results, feed_stats)
    for c in cov:
        if c["homepage"] in blocked_feed_dealers:
            c["reason"] += " (dealer site blocked; cars still covered by the brand feed)"
    if args.dealers or brands:          # partial run: keep last run's report for everything not re-read
        names = {(d["brand"], d["dealer_name"]) for d in pipeline.load_dealers()}
        redone = {(c["brand"], c["dealer"]) for c in cov}
        cov += [c for c in history.read_csv(history.DATA / "coverage.csv")
                if (c["brand"], c["dealer"]) not in redone
                and ((c["brand"], c["dealer"]) in names or c["dealer"].endswith("brand CPO feed"))]
        cov.sort(key=lambda c: (c["brand"], c["status"] != "success", float(c.get("distance_mi") or 0)))
    history.write_csv(history.DATA / "coverage.csv", cov,
                      ["brand", "dealer", "status", "reason", "listings", "distance_mi", "homepage", "method"])
    out_files = {}
    for P in buyers:
        all_rows, changes = updated[P.id]
        out_files[P.id] = (outputs.write_digest(all_rows, changes, cov, today, profile=P),
                           outputs.write_dashboard(all_rows, history.read_csv(P.data / "price_history.csv"), cov, today, profile=P))
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
    for P in buyers:
        _, n_match, n_call = per_buyer[P.id]
        changes = updated[P.id][1]
        print(f"RESULTS for {P.label}:  {n_match} meet all criteria · {n_call} need a call · "
              f"{len(changes['new'])} new · {len(changes['price'])} price changes · {len(changes['removed'])} sold/removed")
        print(f"   Dashboard: {out_files[P.id][1]}   Listings: {P.data / 'listings.csv'}")
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


def prepare(listings, decodes) -> None:
    """Per car, before any buyer's rules: fuel type from the VIN, seats, sticker price, body type."""
    from core import criteria
    from scrapers.generic_jsonld import seat_material
    from verify import msrp, vin_decode
    for L in listings:
        d = decodes.get(L.vin) or {}
        if L.fuel_type != "ev" or d:
            L.fuel_type = vin_decode.fuel_class(d) if d else (L.fuel_type or "gas")
            name = f"{L.model} {L.trim} {L.title}".lower()
            if (d and not d.get("ElectrificationLevel") and L.fuel_type == "gas" and "hybrid" in name
                    and not re.search(r"plug-?in|phev|mild|\bprime\b|\d+h\+|\be-?hybrid", name)):
                L.fuel_type = "hybrid"          # VIN decode has no electrification data; the listing says hybrid
            if d and not d.get("ElectrificationLevel") and re.search(r"(?<![a-z])c ?63 ?s? ?e\b|\be ?performance\b|\be ?53 ?(hybrid|e\b)", name):
                L.fuel_type = "phev"            # AMG C 63 S E PERFORMANCE / E 53 HYBRID: some VIN records leave out the plug-in
        if not L.seats:
            L.seats = seat_material(" ".join(L.features), L.int_color)
        msrp.fill(L)                               # original sticker price: the page's, else the trim's base MSRP
        L.body = criteria.body_kind(L, d)          # "SUV" / "Sedan" (dashboard filter)
        if L.body == "Sedan" and L.fuel_type == "hybrid" and not L.mpg_combined:
            fill_mpg(L)                            # hybrid sedans must average 40+ mpg (filters.sedans.hybrid_min_mpg)


def evaluate_row(L0, dealer: dict, d: dict, listings, excluded: dict, confirmed: dict, today: str) -> dict:
    """One car through the current buyer's rules (criteria.use already set) -> its listings.csv row."""
    import copy
    from core import criteria, pipeline
    from verify import recalls
    L = copy.deepcopy(L0)          # each buyer's rules fill in their own copy
    if (not L.trim or re.fullmatch(r"[A-Z]{2,4}", L.trim)) and d.get("Trim"):
        L.trim = d["Trim"]             # no trim on the listing, or only a code (Mazda's feed: "PPT") -> the VIN decoder's
    apply_confirmed(L, confirmed.get(L.vin.upper()))
    fails, unknown, notes = criteria.evaluate(L, d, dealer, listings, excluded)
    loc = pipeline.location_check(L)
    if loc:
        notes.append(loc)
    if L.link_note:
        notes.append(L.link_note)
    if L.source == "added by you":
        notes.append("added by you from the dealer's listing (this dealer blocks the search): check it's still for sale")
    if L.vin.upper() in confirmed:
        notes.append("checked by you: " + (confirmed[L.vin.upper()].get("note") or "details confirmed"))
    status = "excluded" if fails else "active"
    flags = []
    if status == "active":
        flags = recalls.campaigns(L.make or d.get("Make", ""), L.model, L.year)
        fill_mpg(L)
    r = L.to_dict()
    r.update(status=status, last_read=today, fail_reasons="; ".join(fails), needs_call="; ".join(unknown) if not fails else "",
             notes="; ".join(notes), recall_flags="; ".join(flags),
             est_monthly_cost=criteria.monthly_cost(L.price_total) or "",
             score=criteria.score(L) if not fails else "", distance_mi=dealer.get("distance_mi", ""))
    return r


def add_manual(args) -> None:
    """Put the cars in data/manual_listings.csv on the dashboard now, without a search."""
    from core import criteria, history, outputs, pipeline, profiles
    from verify import vin_decode
    today = date.today().isoformat()
    by_name = {d["dealer_name"]: d for d in pipeline.load_dealers()}
    listings = pipeline.load_manual()
    decodes = vin_decode.decode_many([L.vin for L in listings])
    prepare(listings, decodes)
    cov = history.read_csv(history.DATA / "coverage.csv")
    for P in profiles.all_profiles():
        criteria.use(P.cfg)
        rows = history.read_csv(P.data / "listings.csv")
        old = {r["vin"]: r for r in rows}
        run = max((r.get("seen_run") or "" for r in rows), default="")
        excluded, confirmed = history.load_exclusions(P.data), history.load_confirmed(P.data)
        for L in listings:
            r = {k: ("" if v is None else v) for k, v in evaluate_row(L, by_name.get(L.dealer, {}), decodes.get(L.vin) or {},
                                                                     listings, excluded, confirmed, today).items()}
            prev = old.get(L.vin, {})
            r.update(first_seen=prev.get("first_seen") or today, last_seen=today, seen_run=run,
                     new_run=prev.get("new_run") or run, price_history=prev.get("price_history", ""))
            old[L.vin] = {**prev, **r}
            print(f"{P.label}: {L.year} {L.model} {L.trim} {L.vin}: {r['status']}"
                  + (f" ({r['fail_reasons'] or r['needs_call']})" if r['fail_reasons'] or r['needs_call'] else " (meets all criteria)"))
        rows = list(old.values())
        history.write_csv(P.data / "listings.csv", rows, history.LISTING_COLS)
        last = max((x.get("last_seen") or "" for x in rows), default="")
        outputs.write_dashboard(rows, history.read_csv(P.data / "price_history.csv"), cov, last, profile=P)
    criteria.use(profiles.get().cfg)


def apply_confirmed(L, c: dict | None) -> None:
    """Apply what the user confirmed by hand for this VIN (data/confirmed.csv) before the rules run."""
    if not c:
        return
    if c.get("trim"):
        L.trim = c["trim"]
    if (c.get("ext_color") or "").strip():
        L.ext_color = c["ext_color"].strip()
    roof = (c.get("sunroof") or "").strip().lower()
    if roof in ("yes", "no"):
        L.sunroof = roof == "yes"
        L.sunroof_note = "confirmed by you"
    audio = (c.get("audio") or "").strip()
    if audio:                                  # 'none' = checked: no premium system
        L.audio = "" if audio.lower() == "none" else audio
    seats = (c.get("seats") or "").strip().lower()
    if seats in ("leather", "synthetic", "cloth"):
        L.seats = seats
        L.leather = seats == "leather"
    if _fees_confirmed(c, L.price):            # the user read the dealer's fee breakdown for this price
        L.doc_fee, L.other_fees = float(c["fees"]), 0.0
    if (c.get("msrp_new") or "").strip():      # the window sticker's total
        L.msrp_new, L.msrp_source = float(c["msrp_new"]), "listing"


def _fees_confirmed(c: dict | None, price) -> bool:
    """confirmed.csv 'listed_price' + 'fees': the fees the user saw for that price (0 = the price already
    includes them). Ignored once the dealer changes the price."""
    try:
        return bool(c) and price is not None and abs(float(c["listed_price"]) - float(price)) < 1 and c.get("fees", "") != ""
    except (KeyError, TypeError, ValueError):
        return False


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


def rescore(args) -> None:
    """Re-apply scores, color/interior rules and sticker prices to the last results, without searching
    (for a rules change between searches). Only rules that need nothing beyond what listings.csv holds."""
    from core import criteria, history, outputs, profiles
    from scrapers.listing import Listing
    from verify import msrp
    b = {"True": True, "False": False}
    f = lambda v: float(v) if v not in ("", None) else None
    cov = history.read_csv(history.DATA / "coverage.csv")
    for P in profiles.all_profiles():
        criteria.use(P.cfg)
        rows = history.read_csv(P.data / "listings.csv")
        excluded, confirmed = history.load_exclusions(P.data), history.load_confirmed(P.data)
        n_out = 0
        for r in rows:
            if r.get("status") != "active":
                continue
            if r["vin"] in excluded:                  # ruled out by hand since the last search
                r.update(status="excluded", fail_reasons=f"manually excluded: {excluded[r['vin']]}", needs_call="", score="")
                n_out += 1
                continue
            c = confirmed.get(r["vin"].upper())
            if _fees_confirmed(c, f(r.get("price"))):
                r["price_total"], r["fees_estimated"] = round(f(r["price"]) + float(c["fees"])), "False"
                r["est_monthly_cost"] = criteria.monthly_cost(f(r["price_total"])) or ""
                r["notes"] = "; ".join(x for x in (r.get("notes") or "").split("; ") if x and x != "fees estimated")
            L = Listing(vin=r["vin"], make=r["make"], model=r["model"], trim=r["trim"], listing_url=r["listing_url"],
                        year=int(r["year"]) if r["year"] else None, price_total=f(r["price_total"]),
                        mileage=int(float(r["mileage"])) if r["mileage"] else None, fuel_type=r["fuel_type"],
                        ext_color=r["ext_color"], int_color=r["int_color"], mpg_combined=f(r["mpg_combined"]),
                        audio=r["audio"], leather=b.get(r["leather"]), seats=r.get("seats", ""), sunroof=b.get(r["sunroof"]),
                        ventilated_seats=b.get(r["ventilated_seats"]), spare_tire=b.get(r["spare_tire"]),
                        ground_clearance_in=f(r["ground_clearance_in"]), msrp_new=f(r.get("msrp_new")),
                        msrp_source=r.get("msrp_source", ""))
            apply_confirmed(L, confirmed.get(L.vin.upper()))
            msrp.fill(L)
            L.ext_color = criteria.full_color_name(L.make, L.ext_color)
            r["msrp_new"], r["msrp_source"], r["ext_color"] = L.msrp_new or "", L.msrp_source, L.ext_color
            r["trim"], r["audio"], r["seats"], r["leather"] = L.trim, L.audio, L.seats, "" if L.leather is None else str(L.leather)
            if L.sunroof is not None:
                r["sunroof"] = str(L.sunroof)
                if (confirmed.get(L.vin.upper()) or {}).get("sunroof"):   # the open question is answered
                    r["needs_call"] = "; ".join(x for x in (r.get("needs_call") or "").split("; ") if x and "sunroof" not in x)
            fails = [why for st, why in (criteria.exterior_ok(L.ext_color), criteria.interior_ok(L.int_color)) if st == "fail"]
            spec = criteria.MODELS.get(L.make)            # a model taken off the list since the last search
            if spec and not re.search(spec["allow"], L.model.lower()):
                fails.append(f"model {L.model} not on the {L.make} list ({spec['list']})")
            if fails:
                r.update(status="excluded", fail_reasons="; ".join(fails), needs_call="", score="")
                n_out += 1
            else:
                r["score"] = criteria.score(L)
        history.write_csv(P.data / "listings.csv", rows, history.LISTING_COLS)
        last = max((x.get("last_seen") or "" for x in rows), default="")
        outputs.write_dashboard(rows, history.read_csv(P.data / "price_history.csv"), cov, last, profile=P)
        print(f"{P.label}: rescored; {n_out} now excluded (color/model rules or ruled out by hand)")
    criteria.use(profiles.get().cfg)


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
    sub.add_parser("rescore", help="re-apply scores, color rules and sticker prices to the last results (no search)").set_defaults(func=rescore)
    sub.add_parser("add-manual", help="put the cars in data/manual_listings.csv on the dashboard now (no search)").set_defaults(func=add_manual)
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
