"""Audi dealer sites on Audi's own dealer platform (audi<city>.com/en/...).

These sites, and audiusa.com, refuse cloud-server IPs, so this adapter could not be
tested from the development machine. It tries, in order: the site's sitemap, the
inventory pages linked from the homepage (plain HTTP), then a real browser.
`python run.py diagnose --brand Audi` (run at home) records what each site
exposes so the adapter can be tuned.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from . import playwright_fallback
from .base import FetchError, fetcher
from .generic_jsonld import discover_from_sitemaps
from .listing import VIN_ANY, url_condition, url_matches_brand_models, url_years

INVENTORY_PATHS = ["/en/inventory/used/", "/en/inventory/certified/", "/en/used-vehicles/",
                   "/en/certified-pre-owned/", "/en/inventory/"]


def _links(html: str, base: str) -> list[str]:
    host = urlparse(base).netloc.replace("www.", "")
    out = []
    for href in re.findall(r'href="([^"#]+)"', html):
        u = urljoin(base, href.replace("&amp;", "&"))
        if host in u:
            out.append(u)
    return out


def discover(homepage: str, brand: str = "Audi", inventory_url: str = "") -> tuple[list[str], str]:
    notes = []
    cands, note = discover_from_sitemaps(homepage, brand)
    notes.append(note)
    if cands:
        return cands, "; ".join(notes)
    f = fetcher()
    found: list[str] = []
    for path in ([inventory_url] if inventory_url else []) + [homepage + p for p in INVENTORY_PATHS]:
        try:
            r = f.get(path)
        except FetchError as e:
            notes.append(f"{path}: {e}"[:80])
            continue
        if r.status_code != 200:
            continue
        for u in _links(r.text, r.url):
            vdp = VIN_ANY.search(u.split("?")[0]) or "vehicleid=" in u.lower()
            if vdp and url_condition(u) != "new" and (url_matches_brand_models(u, brand) or "vehicleid=" in u.lower()):
                if not url_years(u) or max(url_years(u)) >= 2023:
                    found.append(u)
    found = list(dict.fromkeys(found))
    if found:
        return found, "; ".join(notes + [f"inventory pages: {len(found)} candidates"])
    if playwright_fallback.available():
        c, n = playwright_fallback.discover_by_browsing(homepage, brand, inventory_url)
        return c, "; ".join(notes + [n])
    return [], "; ".join(notes + ["no inventory found (install Playwright for the browser fallback)"])
