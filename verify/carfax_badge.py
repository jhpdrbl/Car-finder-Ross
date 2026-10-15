"""CARFAX status from the dealer page's own badge/text only. carfax.com is never fetched
(scrapers/base.py blocks the domain). The parsing itself lives in
scrapers/generic_jsonld.parse_vdp; this module states the rule in one place."""
from __future__ import annotations


def status(listing) -> str:
    """clean only when the listing explicitly says no accidents; accident when it says so;
    otherwise not_verified (kept, per spec)."""
    if listing.carfax_status in ("clean", "accident"):
        return listing.carfax_status
    return "not_verified"


def label(listing) -> str:
    s = status(listing)
    badges = listing.carfax_badges.replace(",", ", ")
    if s == "clean":
        return "CARFAX: no accidents" + (f" ({badges})" if badges else "")
    if s == "accident":
        return "CARFAX: accident reported"
    return "CARFAX: not verified" + (f" (badges: {badges})" if badges else "")
