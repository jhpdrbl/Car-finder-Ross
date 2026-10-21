"""Decide whether a listing is certified under the automaker's own CPO program and
sold by that brand's franchise dealer (spec section 3)."""
from __future__ import annotations

import re

PROGRAMS = {
    "Audi": (r"audi certified|audi approved|certified pre-?owned", "Audi Certified pre-owned"),
    "Genesis": (r"genesis certified|certified pre-?owned", "Genesis Certified Pre-Owned"),
    "Subaru": (r"subaru certified|certified pre-?owned", "Subaru Certified Pre-Owned"),
    "BMW": (r"bmw certified|certified pre-?owned bmw|certified pre-?owned", "BMW Certified Pre-Owned"),
    "Mercedes-Benz": (r"mercedes-benz certified|mb certified|certified pre-?owned", "Mercedes-Benz Certified Pre-Owned"),
    "Volkswagen": (r"volkswagen certified|vw certified|certified pre-?owned", "Volkswagen Certified Pre-Owned"),
    "Lexus": (r"l/certified|lexus certified", "L/Certified"),
    "Volvo": (r"volvo (?:cars )?certified|certified by volvo|certified pre-?owned", "Volvo Cars Certified by Volvo"),
    "Toyota": (r"toyota certified|tcuv|certified pre-?owned", "Toyota Certified Used Vehicle"),
    "Ford": (r"blue advantage", "Ford Blue Advantage"),
    "Acura": (r"acura precision certified|precision certified|acura certified|certified pre-?owned", "Acura Precision Certified"),
    "Alfa Romeo": (r"alfa romeo certified|certified pre-?owned", "Alfa Romeo Certified Pre-Owned"),
    "Jaguar": (r"jaguar approved|approved certified|jaguar certified|certified pre-?owned", "Jaguar Approved Certified Pre-Owned"),
}


def check(listing, dealer_brand: str) -> tuple[str, str, str]:
    """Return (cpo_program or '', reason it fails, reason it is uncertain).

    Strong evidence: the brand's own CPO feed, or the listing URL / title / structured
    data saying certified. Page text alone doesn't count: nearly every dealer site has a
    "Certified Pre-Owned" menu link, and all 9 such cars the user checked (Oct 2026) were not
    certified. User's rule: if the listing itself doesn't say certified, it's not CPO.
    """
    make = (listing.make or "").lower()
    if dealer_brand.lower().split("-")[0] not in make and not (dealer_brand == "Mercedes-Benz" and "mercedes" in make):
        return "", f"sold by a {dealer_brand} dealer, not a {listing.make} franchise (cross-brand)", ""
    text = (listing.cert_text or "").lower()
    m = re.search(r"dealer program: (\w+) certified", text)
    pat, name = PROGRAMS.get(dealer_brand, (r"certified pre-?owned", "Certified Pre-Owned"))
    strong = bool(re.search(r"url:certified|title:certified|cpo inventory\)", text))
    if m and not strong:
        return "", f"dealer's own certification ({m.group(1).title()} Certified), not {name}", ""
    if listing.condition == "new":
        return "", "new vehicle", ""
    if dealer_brand == "Ford":
        if "blue advantage" not in text:
            return "", "no Ford Blue Advantage certification shown", ""
        tier = "Gold" if "gold" in text else ("Blue" if re.search(r"advantage blue|blue advantage blue", text) else "")
        if not strong:
            return "", "Blue Advantage not shown on the listing itself (only elsewhere on the dealer's site)", ""
        return f"{name} {tier}".strip(), "", ""
    if strong:
        return name, "", ""
    if re.search(pat, text):
        return "", "certification not shown on the listing itself (only elsewhere on the dealer's site)", ""
    return "", "no automaker certification shown on the listing", ""
