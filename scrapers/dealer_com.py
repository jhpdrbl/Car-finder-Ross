"""Dealer.com (DDC) sites: the used-inventory search page embeds each car's link,
model and VIN as JSON, and accepts ?search=<words>&start=<offset>.
"""
from __future__ import annotations

import re

from .base import FetchError, fetcher
from .listing import MODEL_TOKENS, url_matches_brand_models, url_years

CAR = re.compile(r'"link":"([^"]+)"[^{}]{0,600}?"vin":"([A-HJ-NPR-Z0-9]{17})"')
SEARCH_PAGES = ["/used-inventory/index.htm", "/certified-inventory/index.htm"]


def discover(homepage: str, brand: str, inventory_url: str = "") -> tuple[list[str], str]:
    f = fetcher()
    pages = [inventory_url.split("?")[0].replace(homepage, "")] if inventory_url else []
    pages += [p for p in SEARCH_PAGES if p not in pages]
    words = [t.replace("-", " ") for t in MODEL_TOKENS.get(brand, [])]
    found: dict[str, str] = {}
    notes = []
    for page in pages:
        for w in words:
            start = 0
            while start < 200:
                url = f"{homepage}{page}?search={w.replace(' ', '+')}&start={start}"
                try:
                    r = f.get(url)
                except FetchError as e:
                    notes.append(f"{page}: {e}"[:80])
                    break
                if r.status_code != 200:
                    notes.append(f"{page}: HTTP {r.status_code}")
                    break
                cars = CAR.findall(r.text)
                for link, vin in cars:
                    link = link if link.startswith("http") else homepage + link
                    if url_matches_brand_models(link, brand) and (not url_years(link) or max(url_years(link)) >= 2023):
                        found[vin] = link
                total = re.search(r'"totalCount"\s*:\s*(\d+)', r.text)
                size = re.search(r'"pageSize"\s*:\s*(\d+)', r.text)
                size = int(size.group(1)) if size else 24
                if not cars or not total or start + size >= int(total.group(1)):
                    break
                start += size
        if found:
            break  # the used-inventory page already includes certified cars
    return list(found.values()), f"dealer.com search: {len(found)} candidates" + (f" ({'; '.join(notes[:2])})" if notes else "")
