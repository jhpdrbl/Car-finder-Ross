"""Rebuild output/dashboard.html from data/ with the current code, just before publishing.

A laptop search that started before a code or settings change uploads a page built with the old code
(Nov 2 2026: the test-drive price limit vanished for an hour). The publish workflow runs this first, so the
website always shows the latest results with the latest code. It also applies the hand-kept marks that may
have changed during that search: cars you said are sold (data/exclusions.csv, reason starting "sold") and
cars added by hand that are no longer in data/manual_listings.csv. No dealer site is fetched.

  python -m tools.rebuild_dashboard
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    from core import history, outputs, profiles
    today = date.today().isoformat()
    path = history.DATA / "manual_listings.csv"
    manual = {r["vin"].strip().upper() for r in csv.DictReader(path.open(encoding="utf-8"))} if path.exists() else set()
    for P in profiles.all_profiles():
        rows = history.read_csv(P.data / "listings.csv")
        if not rows:
            continue
        n = history.mark_sold_by_hand(rows, P.data, today)
        for r in rows:              # a car added by hand whose row was deleted (you said it's gone)
            if r.get("source") == "added by you" and r.get("status") == "active" and r["vin"].upper() not in manual:
                r.update(status="sold", removed_on=r.get("removed_on") or today, fail_reasons="you said it's no longer available")
                n += 1
        last = max((r.get("last_seen") or "" for r in rows), default="")
        outputs.write_dashboard(rows, history.read_csv(P.data / "price_history.csv"),
                                history.read_csv(P.data / "coverage.csv"), last, profile=P)
        print(f"{P.label}: dashboard rebuilt with the current code ({n} hand marks applied)")


if __name__ == "__main__":
    main()
