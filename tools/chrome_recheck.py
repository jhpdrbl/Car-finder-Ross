"""Re-check the cars added by hand (data/manual_listings.csv) with Claude in Chrome, in the user's own browser.

    python -m tools.chrome_recheck list  [out.txt]   # the instruction to paste into Claude in Chrome + every car's own link
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
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MANUAL = DATA / "manual_listings.csv"
SITE = "https://cpo-suv-finder.pages.dev"

INSTRUCTION = """Please check each car below on the dealer's own website, one page at a time (wait a few seconds between pages).
If a page asks you to prove you're human (CAPTCHA, "are you a robot", "checking your browser"), stop there and tell me which dealer; don't try to get past it.

For each car, open its link and write ONE line:
VIN | STATUS | PRICE | FEES | MILES
- STATUS: "for sale" if the page shows this exact VIN; "gone" if it says sold / no longer available, sends you to the inventory list, or shows a different car.
- PRICE: the advertised price before taxes and fees, as shown (for example $31,995). If the page shows several prices, use the one the dealer is asking now.
- FEES: each dealer fee the page lists, with its name (for example "Doc $85; EVR $37"), or "none listed".
- MILES: the odometer reading.
For a gone car, leave PRICE, FEES and MILES empty.

When you're done, put all the lines together in one code block at the end, nothing else in it.

The cars:
"""


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


def cmd_list(out: str | None) -> None:
    fav = set(_get_json("/api/favs").get("fav") or [])
    gone = set((_get_json("/api/mine").get("gone") or {}).keys())
    _, rows = read_rows()
    listed = {r["vin"]: r["status"] for r in csv.DictReader((DATA / "listings.csv").open(encoding="utf-8"))}
    by = defaultdict(list)
    for r in rows:                      # only cars on the page now (one the rules rule out isn't worth a visit)
        if r.get("vin") and r["vin"] not in gone and listed.get(r["vin"]) == "active":
            by[r["dealer"]].append(r)
    lines = [INSTRUCTION]
    for d in sorted(by, key=lambda d: (-sum(x["vin"] in fav for x in by[d]), d)):     # dealers with favorites first
        lines.append(f"\n{d}")
        for x in sorted(by[d], key=lambda x: (x["vin"] not in fav, x["model"])):
            lines.append(f"{x['vin']} | {x['year']} {x['model']} {x['trim']}".strip() + f" | {x['listing_url']}")
    text = "\n".join(lines) + "\n"
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(f"wrote {out}: {sum(len(v) for v in by.values())} cars at {len(by)} dealers")
    else:
        print(text)


money = lambda s: [float(x.replace(",", "")) for x in re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", s or "")]


def cmd_apply(src: str) -> None:
    today = date.today().isoformat()
    cols, rows = read_rows()
    by = {r["vin"].upper(): r for r in rows if r.get("vin")}
    updated, gone, unknown, odd = [], [], [], []
    for line in Path(src).read_text(encoding="utf-8").splitlines():
        f = [x.strip() for x in line.strip().strip("`").split("|")]
        if len(f) < 2 or not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", f[0].upper()):
            continue
        vin, status = f[0].upper(), f[1].lower()
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
