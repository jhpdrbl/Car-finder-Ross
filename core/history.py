"""listings.csv / price_history.csv: every listing ever seen, first/last seen, status, price changes."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

LISTING_COLS = ["vin", "status", "first_seen", "last_seen", "dealer", "dealer_url", "listing_url", "year", "make",
                "model", "trim", "packages", "fuel_type", "price_total", "price_history", "mileage", "ext_color",
                "int_color", "drivetrain", "sunroof", "audio", "leather", "ventilated_seats", "ground_clearance_in",
                "spare_tire", "cpo_program", "cpo_warranty_terms", "carfax_status", "recall_flags", "est_monthly_cost",
                "score", "fail_reasons",
                # extras beyond the spec's list
                "needs_call", "notes", "price", "fees_estimated", "dealer_brand", "distance_mi", "source", "carfax_badges"]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def load_exclusions() -> dict[str, str]:
    return {r["vin"].strip().upper(): r["reason"] for r in read_csv(DATA / "exclusions.csv") if r.get("vin")}


def update(current: list[dict], scraped_dealers_ok: set[str], gone_urls: dict[str, str], today: str | None = None):
    """Merge this run into listings.csv. Returns (rows, changes) where changes has new / price / removed lists.

    A listing that was active and is not seen again is only marked sold when its dealer
    (or brand feed) was read successfully this run; otherwise it stays as it was.
    """
    today = today or date.today().isoformat()
    old = {r["vin"]: r for r in read_csv(DATA / "listings.csv")}
    hist = read_csv(DATA / "price_history.csv")
    last_price = {}
    for h in hist:
        last_price[h["vin"]] = h["price"]
    changes = {"new": [], "price": [], "removed": [], "newly_excluded": []}
    seen = set()
    rows = []
    for r in current:
        vin = r["vin"]
        seen.add(vin)
        prev = old.get(vin)
        r["first_seen"] = prev["first_seen"] if prev else today
        r["last_seen"] = today
        p = r.get("price_total")
        if p not in (None, ""):
            if str(last_price.get(vin, "")) != str(p):
                hist.append({"vin": vin, "date": today, "price": p})
            if prev and prev.get("price_total") not in ("", None) and str(prev["price_total"]) != str(p):
                changes["price"].append((r, float(prev["price_total"]), float(p)))
        r["price_history"] = " → ".join(f"${float(h['price']):,.0f}" for h in hist if h["vin"] == vin)
        if not prev or prev.get("status") != "active":
            if r["status"] == "active":
                changes["new"].append(r)
        if prev and prev.get("status") == "active" and r["status"] == "excluded":
            changes["newly_excluded"].append(r)
        rows.append(r)
    for vin, prev in old.items():
        if vin in seen:
            continue
        if prev.get("status") == "active" and (prev.get("dealer") in scraped_dealers_ok
                                               or prev.get("listing_url") in gone_urls):
            prev = dict(prev, status="sold")
            prev["fail_reasons"] = gone_urls.get(prev.get("listing_url"), "no longer listed by the dealer")
            changes["removed"].append(prev)
        rows.append(prev)
    write_csv(DATA / "listings.csv", rows, LISTING_COLS)
    write_csv(DATA / "price_history.csv", hist, ["vin", "date", "price"])
    return rows, changes
