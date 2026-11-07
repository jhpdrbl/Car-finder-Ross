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


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "list":
        cmd_list(sys.argv[2] if len(sys.argv) > 2 else None)
    elif len(sys.argv) >= 3 and sys.argv[1] == "apply":
        cmd_apply(sys.argv[2])
    else:
        print(__doc__)
