"""Dealer Inspire sites: machine-readable inventory at /llm/inventory (announced in
/llms.txt), filtered by query string and paginated with page=N.

Every Dealer Inspire site blocks cloud-server IPs (Cloudflare), so this adapter
could not be tested from the development machine; it is written to the format
llms.txt documents and kept tolerant: it collects any link on the page that
carries a VIN. Run `python run.py diagnose --platform dealer_inspire` at home
to check it.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from .base import FetchError, fetcher
from .listing import MODEL_TOKENS, VIN_ANY, url_matches_brand_models, url_years

LINK = re.compile(r'href="([^"]+)"', re.I)


def has_feed(homepage: str) -> bool:
    try:
        r = fetcher().get(homepage + "/llms.txt")
        return r.status_code == 200 and "llm/inventory" in r.text
    except FetchError:
        return False


def discover(homepage: str, brand: str) -> tuple[list[str], str]:
    f = fetcher()
    found: dict[str, str] = {}
    errors = []
    for token in MODEL_TOKENS.get(brand, []):
        model = token.replace("-", " ")
        for page in range(1, 11):
            url = (f"{homepage}/llm/inventory/?type=used&make={brand.replace(' ', '+')}&model={model.replace(' ', '+')}"
                   f"&year_min=2023&limit=100&page={page}")
            try:
                r = f.get(url)
            except FetchError as e:
                errors.append(str(e)[:80])
                break
            if r.status_code != 200:
                errors.append(f"HTTP {r.status_code}" + (" (cloudflare)" if "cloudflare" in r.text[:3000].lower() else ""))
                break
            before = len(found)
            for href in LINK.findall(r.text):
                full = urljoin(homepage + "/", href)
                m = VIN_ANY.search(full.split("?")[0])
                if not m or "/llm/" in full:
                    continue
                if url_matches_brand_models(full, brand) and (not url_years(full) or max(url_years(full)) >= 2023):
                    found.setdefault(m.group(1).upper(), full)
            # stop paging once a page adds nothing new
            if len(found) == before:
                break
    note = f"/llm/inventory: {len(found)} candidates"
    if errors:
        note += f" ({errors[0]})"
    return list(found.values()), note
