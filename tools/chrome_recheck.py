"""Re-check the cars added by hand (data/manual_listings.csv) with Claude in Chrome, in the user's own browser.

    python -m tools.chrome_recheck list  [out.txt]   # parts of 10 cars, each with the instruction; cars checked in the last 2 days left out
    python -m tools.chrome_recheck apply lines.txt   # read its answer lines back: price / fees / miles, and gone cars

The dealers of these cars block automated reading, so the user's browser opens each car's own page (one at a time,
stopping at any CAPTCHA: no getting around bot protection). Answer lines look like
    VIN | for sale | $31,995 | Doc $85; EVR $37 | 21,324
    VIN | gone | | |
A car that is gone is removed from manual_listings.csv and kept on the Sold tab (exclusions.csv reason "sold ...").
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MANUAL = DATA / "manual_listings.csv"
SITE = "https://cpo-suv-finder.pages.dev"

INSTRUCTION = """Please check each car below on the dealer's own website, one page at a time (wait a few seconds between pages).
If a page asks you to prove you're human (CAPTCHA, "are you a robot", "checking your browser"), stop there and tell me which dealer; don't try to get past it.

For each car, open its link and write ONE line:
VIN | STATUS | PRICE | FEES | MILES
Open every link in a normal tab of this browser (don't fetch pages any other way: some dealer sites send other requests to their inventory list).
- STATUS: "for sale" if the page shows this exact VIN; "gone" only if the page itself says sold / no longer available, or shows a
  different car. If you land on the inventory list instead, search that list for the VIN: "for sale" if it's there, else "gone".
- PRICE: the advertised price before taxes and fees, as shown (for example $31,995). If the page shows several prices, use the one the dealer is asking now.
- FEES: each dealer fee the page lists, with its name (for example "Doc $85; EVR $37"), or "none listed".
- MILES: the odometer reading.
For a gone car, leave PRICE, FEES and MILES empty.

IMPORTANT: write each car's line in your reply as soon as you've checked that car, before opening the next one,
so nothing is lost if you have to stop early. Don't save them up for the end.

The cars ({part}):
"""
PART_SIZE = 10          # cars per part: a part fits in one Claude in Chrome session even on a slow day


def _get_json(path: str) -> dict:
    try:
        import requests
        return requests.get(SITE + path, timeout=15).json()
    except Exception:
        return {}


def read_rows() -> tuple[list[str], list[dict]]:
    text = MANUAL.read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    return text.splitlines()[0].split(","), rows


def write_rows(cols: list[str], rows: list[dict]) -> None:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=cols, lineterminator="\n", restval="")
    w.writeheader()
    w.writerows(rows)
    MANUAL.write_text(out.getvalue(), encoding="utf-8", newline="")


def cmd_list(out: str | None, fresh_days: int = 2) -> None:
    """Parts of PART_SIZE cars, each with its own instruction, so each can be pasted on its own. Cars whose price was
    read in the last `fresh_days` days (an earlier part already done) are left out: running `list` again after an
    interrupted session picks up where it stopped."""
    fav = set(_get_json("/api/favs").get("fav") or [])
    gone = set((_get_json("/api/mine").get("gone") or {}).keys())
    _, rows = read_rows()
    listed = {r["vin"]: r["status"] for r in csv.DictReader((DATA / "listings.csv").open(encoding="utf-8"))}
    cutoff = (date.today() - timedelta(days=fresh_days)).isoformat()
    by, done = defaultdict(list), 0
    for r in rows:                      # only cars on the page now (one the rules rule out isn't worth a visit)
        if not (r.get("vin") and r["vin"] not in gone and listed.get(r["vin"]) == "active"):
            continue
        if (r.get("price_on") or "") > cutoff:
            done += 1                   # checked lately: skip
            continue
        by[r["dealer"]].append(r)
    cars = []                           # dealers with favorites first, favorites first within a dealer
    for d in sorted(by, key=lambda d: (-sum(x["vin"] in fav for x in by[d]), d)):
        cars += sorted(by[d], key=lambda x: (x["vin"] not in fav, x["model"]))
    parts = [cars[i:i + PART_SIZE] for i in range(0, len(cars), PART_SIZE)]
    blocks = []
    for n, part in enumerate(parts, 1):
        body, last = [], None
        for x in part:
            if x["dealer"] != last:
                body.append(f"\n{x['dealer']}")
                last = x["dealer"]
            body.append(f"{x['vin']} | {x['year']} {x['model']} {x['trim']}".strip() + f" | {x['listing_url']}")
        blocks.append(f"===== PART {n} of {len(parts)}: copy from here =====\n\n"
                      + INSTRUCTION.format(part=f"part {n} of {len(parts)}") + "\n".join(body)
                      + f"\n\n===== end of part {n} =====\n")
    head = (f"{len(cars)} cars to check in {len(parts)} parts of up to {PART_SIZE}"
            + (f" ({done} checked in the last {fresh_days} days are left out)" if done else "") + ".\n"
            "Paste one part at a time into Claude in Chrome. After each part, send the lines it wrote to Claude here\n"
            "(even if it stopped partway: the lines it did write are kept).\n\n")
    text = head + "\n".join(blocks)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(f"wrote {out}: {len(cars)} cars in {len(parts)} parts ({done} checked lately left out)")
    else:
        print(text)


money = lambda s: [float(x.replace(",", "")) for x in re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", s or "")]


def cmd_apply(src: str) -> None:
    today = date.today().isoformat()
    cols, rows = read_rows()
    by = {r["vin"].upper(): r for r in rows if r.get("vin")}
    updated, gone, unknown, odd = [], [], [], []
    for line in Path(src).read_text(encoding="utf-8").splitlines():
        f = [x.strip().strip("`*") for x in line.strip().strip("`").split("|")]
        m = re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", f[0].upper()) if len(f) >= 2 else None   # "1. VIN", "- VIN", "**VIN**" all fine
        if not m:
            continue
        vin, status = m.group(0), f[1].lower()
        r = by.get(vin)
        if not r:
            unknown.append(vin)
            continue
        if status.startswith("gone") or "sold" in status:
            gone.append(vin)
            continue
        f += [""] * (5 - len(f))
        price, fees, miles = money(f[2]), money(re.sub(r"\([^)]*\)", "", f[3])), re.sub(r"[^\d]", "", f[4])
        if not price:
            odd.append(line)
            continue
        old = float(r["price"] or 0)
        r["price"] = str(round(price[0]))
        if fees:
            r["doc_fee"], r["other_fees"] = str(round(fees[0])), str(round(sum(fees[1:])))
        elif "none" in f[3].lower():
            r["doc_fee"], r["other_fees"] = "0", "0"
        if miles:
            if r.get("mileage") and int(miles) + 50 < int(float(r["mileage"])):
                odd.append(f"{vin}: miles went down ({r['mileage']} -> {miles}); kept the new reading, check it")
            r["mileage"] = miles
        r["price_on"] = today
        updated.append((vin, old, price[0]))
    if gone:
        rows = [r for r in rows if r.get("vin", "").upper() not in gone]
        ex = DATA / "exclusions.csv"
        names = {v: by[v] for v in gone}
        with ex.open("a", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            for v in gone:
                x = names[v]
                w.writerow([v, f"sold (your browser check {today}: no longer listed): {x['year']} {x['model']} at {x['dealer']}"])
    write_rows(cols, rows)
    print(f"updated {len(updated)}, gone {len(gone)}, not on file {len(unknown)}")
    for v, a, b in updated:
        if abs(a - b) >= 1:
            print(f"  {v}: ${a:,.0f} -> ${b:,.0f}")
    for v in gone:
        print(f"  {v}: gone -> Sold tab")
    for x in odd:
        print("  check:", x)


# ---------------------------------------------------------------------------------------------------------------
# Finding NEW cars at the dealers the search can't read (Nov 7 2026, user: "prioritize finding new cars").
#     python -m tools.chrome_recheck find [out.txt]      # parts of 3 dealers: their certified inventory + models wanted
#     python -m tools.chrome_recheck addnew lines.txt    # its answer lines -> new rows in manual_listings.csv

FIND_INSTRUCTION = """Please look through each dealer's CERTIFIED pre-owned inventory below, in a normal tab of this browser, one page at a time
(wait a few seconds between pages). If a page asks you to prove you're human (CAPTCHA, "are you a robot", "checking your
browser"), stop there and tell me which dealer; don't try to get past it.

I want certified cars I don't know about yet. Report a car only if ALL of these are true:
- it's certified pre-owned (the page or the listing says certified / CPO),
- it's one of the models listed for that dealer, model year {min_year} or newer, and NOT gas-only
  (plug-in hybrid, hybrid or electric; for Mercedes / BMW / Audi plug-ins the name has an "e", e.g. GLC 350e, 330e, 55 TFSI e),
- the price is under $41,000 and the miles are under 40,000,
- its VIN doesn't end in one of the "already known" endings listed for that dealer.
Use the site's own filters (certified, model, price) if it has them, and go through every page of results with the site's own
Next button (typing a page address can drop the certified filter).
A "checking your browser" screen that clears by itself while you wait is fine; if it asks you to click or solve anything, stop.
Only report cars at the dealer named; some sites also list cars from sister stores, which have their own entry.

For each car you report, open its own page and write ONE line:
VIN | DEALER | YEAR | MAKE | MODEL | TRIM | PRICE | FEES | MILES | EXTERIOR COLOR | INTERIOR COLOR | SUNROOF | SOUND SYSTEM | SEATS | CARFAX | LINK
- DEALER: the dealer's name exactly as written below.
- PRICE: the advertised price before taxes and fees (for example $31,995). FEES: each dealer fee the page lists with its name
  ("Doc $85; EVR $37"), or "none listed".
- SUNROOF: yes / no / not shown (a panoramic or glass roof counts as yes).
- SOUND SYSTEM: the brand name if the page names one (Bang & Olufsen, Burmester, Harman Kardon, Mark Levinson, Bose, SONOS...),
  else "not shown".
- SEATS: leather / synthetic (MB-Tex, SensaTec, Vernasca, NuLuxe, Inteluxe...) / cloth / not shown.
- CARFAX: any CARFAX badge the page shows ("CARFAX 1-Owner", "No Accident"), else "none". Don't open carfax.com.
- LINK: the address of the car's own page.
After each dealer, write one line: "DONE | <dealer> | <how many certified cars you looked at>".

IMPORTANT: write each car's line as soon as you have it, before moving on, so nothing is lost if you have to stop early.

The dealers ({part}):
"""
FIND_PART = 3            # dealers per part
FIND_ORDER = ["Audi", "Mercedes-Benz", "BMW", "Acura", "Cadillac", "Ford", "Toyota", "Alfa Romeo", "Jaguar"]
LUXURY = {"Audi", "Mercedes-Benz", "BMW", "Acura", "Cadillac"}
LAST = {"Jaguar", "Alfa Romeo"}   # luxury too, but only the I-Pace / Tonale plug-in could pass (Oct 25: no certified I-Pace within 60 mi)
NEAR_MI = 25             # luxury dealers within this distance come first (user, Nov 7 2026: "prioritize close dealerships at the luxury brands")
FIND_DONE = DATA / "chrome_find_done.csv"   # dealer,date: dealers Claude in Chrome went through (DONE lines)
FIND_FRESH_DAYS = 14     # a dealer searched in the last 14 days is left out of the next list
NOT_GAS_MODELS = {       # models worth a visit while gas cars are off (filters.fuels); the rest are gas-only
    "Audi": "Q4 e-tron, Q5 55 TFSI e (plug-in), Q6 e-tron, Q8 e-tron / SQ8 e-tron, e-tron / e-tron S, e-tron GT, A6 / S6 Sportback e-tron",
    "Mercedes-Benz": "GLC 350e, GLE 450e, EQB, EQE SUV, EQS SUV, EQE sedan, EQS sedan, AMG E 53 HYBRID, AMG C 63 S E PERFORMANCE, S 580e",
    "BMW": "X5 xDrive50e, iX, i4, i5, i7, 330e, 530e, 550e, 750e",
    "Acura": "ZDX",
    "Cadillac": "Lyriq, Optiq",
    "Ford": "Mustang Mach-E",
    "Toyota": "bZ4X / bZ, 4Runner hybrid (i-FORCE MAX), Land Cruiser (hybrid, 2024+)",
    "Alfa Romeo": "Tonale (plug-in hybrid)",
    "Jaguar": "I-Pace",
}


def _find_done() -> dict:
    if not FIND_DONE.exists():
        return {}
    return {r["dealer"]: r["date"] for r in csv.DictReader(FIND_DONE.open(encoding="utf-8"))}


def cmd_find(out: str | None) -> None:
    sys.path.insert(0, str(ROOT))
    from core import outputs, history
    cl = outputs.check_list(history.read_csv(DATA / "coverage.csv"))
    known = defaultdict(set)
    for r in csv.DictReader((DATA / "listings.csv").open(encoding="utf-8")):
        if r.get("fuel_type") != "gas" and (r.get("year") or "9999") >= "2023":   # a gas car isn't reported anyway: keep the list short
            known[r["dealer"]].add(r["vin"].upper())
    for r in read_rows()[1]:
        known[r["dealer"]].add(r["vin"].upper())
    done = _find_done()
    cutoff = (date.today() - timedelta(days=FIND_FRESH_DAYS)).isoformat()
    skipped = [c["dealer"] for c in cl if done.get(c["dealer"], "") >= cutoff]
    cl = [c for c in cl if c["brand"] in NOT_GAS_MODELS and c["dealer"] not in skipped
          and "authorized service" not in c["dealer"].lower()]   # service-only locations sell no cars
    dist = lambda c: float(c["distance_mi"] or 999)
    tier = lambda c: 0 if c["brand"] in LUXURY and dist(c) <= NEAR_MI else 1 if c["brand"] in LUXURY else 3 if c["brand"] in LAST else 2
    cl.sort(key=lambda c: (tier(c), dist(c)))     # close luxury dealers, then farther luxury, then Ford / Toyota
    parts = [cl[i:i + FIND_PART] for i in range(0, len(cl), FIND_PART)]
    blocks = []
    for n, part in enumerate(parts, 1):
        body = []
        for c in part:
            kv = sorted(v[-8:] for v in known.get(c["dealer"], ()))
            body.append(f"\n{c['dealer']} ({c['brand']}, {float(c['distance_mi'] or 0):.0f} mi)\n"
                        f"  Certified inventory: {c['cpo'] or c['homepage']}\n"
                        f"  Models: {NOT_GAS_MODELS[c['brand']]}\n"
                        f"  Already known (VIN ends in): {', '.join(kv) if kv else 'none'}")
        blocks.append(f"===== PART {n} of {len(parts)}: copy from here =====\n\n"
                      + FIND_INSTRUCTION.format(part=f"part {n} of {len(parts)}", min_year=2023) + "\n".join(body)
                      + f"\n\n===== end of part {n} =====\n")
    text = (f"{len(cl)} dealers the search can't read, in {len(parts)} parts of {FIND_PART}: luxury brands within {NEAR_MI} mi first, "
            f"then farther luxury dealers, then Ford and Toyota, then Jaguar and Alfa Romeo ({len(skipped)} searched in the last {FIND_FRESH_DAYS} days left out).\n"
            "Paste one part at a time into Claude in Chrome and send Claude here the lines it writes (partial is fine).\n\n"
            + "\n".join(blocks))
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(f"wrote {out}: {len(cl)} dealers in {len(parts)} parts")
    else:
        print(text)


def cmd_addnew(src: str) -> None:
    sys.path.insert(0, str(ROOT))
    from urllib.parse import urlparse
    today = date.today().isoformat()
    cols, rows = read_rows()
    have = {r["vin"].upper() for r in rows}
    dealers = list(csv.DictReader((DATA / "dealers.csv").open(encoding="utf-8")))
    by_name = {d["dealer_name"].lower(): d for d in dealers}
    host = lambda u: urlparse(u if "//" in u else "https://" + u).netloc.lower().removeprefix("www.")
    by_host = {host(d["homepage"]): d for d in dealers if d.get("homepage")}
    added, skipped, odd, done = [], [], [], []
    for line in Path(src).read_text(encoding="utf-8").splitlines():
        f = [x.strip().strip("`*") for x in line.strip().strip("`").split("|")]
        if f and f[0].upper().startswith("DONE") and len(f) >= 2:
            done.append(" | ".join(f[1:]))
            continue
        m = re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", f[0].upper()) if len(f) >= 10 else None
        if not m:
            continue
        f += [""] * (16 - len(f))
        vin = m.group(0)
        if vin in have:
            skipped.append(vin)
            continue
        link = f[15]
        d = by_name.get(f[1].lower()) or by_host.get(host(link)) if link else by_name.get(f[1].lower())
        if not d:
            odd.append(f"{vin}: dealer '{f[1]}' not on file")
            continue
        price, fees = money(f[6]), money(re.sub(r"\([^)]*\)", "", f[7]))
        none = lambda s: "" if re.match(r"(not shown|none|n/?a|unknown|-)$", s.strip(), re.I) else s.strip()
        roof = f[11].lower()
        r = {c: "" for c in cols}
        r.update(vin=vin, listing_url=link, dealer=d["dealer_name"], year=re.sub(r"\D", "", f[2])[:4], make=f[3], model=f[4],
                 trim=none(f[5]), price=str(round(price[0])) if price else "",
                 doc_fee=str(round(fees[0])) if fees else ("0" if "none" in f[7].lower() else ""),
                 other_fees=str(round(sum(fees[1:]))) if fees else ("0" if "none" in f[7].lower() else ""),
                 mileage=re.sub(r"[^\d]", "", f[8]), ext_color=none(f[9]), int_color=none(f[10]),
                 sunroof="yes" if roof.startswith("yes") else "no" if re.match(r"no\b(?! ?t)", roof) else "",   # "not shown" isn't "no"
                 cert_text=f"{f[3]} Certified pre-owned (dealer's certified inventory, read in your browser)",
                 added_on=today, price_on=today, audio=none(f[12]), seats=none(f[13]), carfax=none(f[14]))
        if not (r["year"] and r["price"] and link):
            odd.append(f"{vin}: missing year, price or link")
            continue
        rows.append(r)
        have.add(vin)
        added.append(f"{vin}: {r['year']} {r['make']} {r['model']} {r['trim']} ${float(r['price']):,.0f} at {r['dealer']}")
    write_rows(cols, rows)
    if done:                                      # remember which dealers were gone through, so 'find' moves on
        names = {d["dealer_name"].lower(): d["dealer_name"] for d in dealers}
        seen = _find_done()
        for x in done:
            n = names.get(x.split("|")[0].strip().lower())
            if n:
                seen[n] = today
        with FIND_DONE.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["dealer", "date"])
            w.writerows(sorted(seen.items()))
    print(f"added {len(added)} new cars, {len(skipped)} already on file")
    for x in added:
        print("  +", x)
    for x in odd:
        print("  check:", x)
    for x in done:
        print("  done:", x)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "list":
        cmd_list(sys.argv[2] if len(sys.argv) > 2 else None)
    elif len(sys.argv) >= 3 and sys.argv[1] == "apply":
        cmd_apply(sys.argv[2])
    elif len(sys.argv) >= 2 and sys.argv[1] == "find":
        cmd_find(sys.argv[2] if len(sys.argv) > 2 else None)
    elif len(sys.argv) >= 3 and sys.argv[1] == "addnew":
        cmd_addnew(sys.argv[2])
    else:
        print(__doc__)
