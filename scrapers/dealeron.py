"""DealerOn sites: VDP URLs carry the VIN (…-2024-Lexus-NX-350-JTJ…) and are
listed in the sitemap; the search pages also link them directly.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from .base import FetchError, fetcher
from .generic_jsonld import discover_from_sitemaps
from core.profiles import min_year
from .listing import MODEL_TOKENS, VIN_ANY, url_condition, url_matches_brand_models, url_years

SEARCH_PAGES = ["/searchused.aspx", "/certified-pre-owned.html", "/used-vehicles/"]


def discover(homepage: str, brand: str, inventory_url: str = "") -> tuple[list[str], str]:
    cands, note = discover_from_sitemaps(homepage, brand)
    found = dict.fromkeys(cands)
    f = fetcher()
    pages = ([inventory_url] if inventory_url else []) + [homepage + p for p in SEARCH_PAGES]
    for page in pages:
        for token in MODEL_TOKENS.get(brand, []):
            url = f"{page}{'&' if '?' in page else '?'}Model={token.replace('-', ' ').title().replace(' ', '+')}"
            try:
                r = f.get(url)
            except FetchError:
                continue
            if r.status_code != 200:
                continue
            for href in re.findall(r'href="([^"#]+)"', r.text):
                u = urljoin(r.url, href.replace("&amp;", "&").replace("&#x2B;", "+"))
                if VIN_ANY.search(u.split("?")[0]) and url_condition(u) != "new" and url_matches_brand_models(u, brand):
                    if not url_years(u) or max(url_years(u)) >= min_year(brand):
                        found.setdefault(u)
        if len(found) > len(cands):
            break
    return list(found), f"{note}; dealeron search: {len(found) - len(cands)} more"
