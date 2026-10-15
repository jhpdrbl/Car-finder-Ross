"""Check candidate dealer homepages: does the site exist, is it that brand's
dealer, and what address does it publish (schema.org AutoDealer JSON-LD)?

Usage: python -m tools.verify_dealer_sites candidates.csv out.csv
"""
from __future__ import annotations

import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

from scrapers.base import FetchError, Fetcher
from scrapers.generic_jsonld import PARSER

BRAND_WORDS = {"Audi": ["audi"], "BMW": ["bmw"], "Mercedes-Benz": ["mercedes"], "Ford": ["ford"],
               "Volvo": ["volvo"], "Volkswagen": ["volkswagen", "vw"]}


def jsonld_address(html: str):
    soup = BeautifulSoup(html, PARSER)
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                if "@graph" in d:
                    stack.extend(d["@graph"])
                a = d.get("address")
                if isinstance(a, list) and a:
                    a = a[0]
                if isinstance(a, dict) and a.get("streetAddress"):
                    geo = d.get("geo") or {}
                    return (a.get("streetAddress", ""), a.get("addressLocality", ""), a.get("postalCode", ""),
                            str(geo.get("latitude", "")), str(geo.get("longitude", "")), d.get("name", ""))
    return None


def check(row: dict) -> dict:
    f = Fetcher(use_cache=True)
    out = dict(row, site_status="", final_url="", title="", brand_ok="", address="", addr_city="",
               zip="", lat="", lon="", site_name="")
    try:
        r = f.get(row["homepage"] + "/")
    except FetchError as e:
        out["site_status"] = f"error: {e}"[:120]
        return out
    out["site_status"] = str(r.status_code)
    out["final_url"] = r.url
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, PARSER)
        out["title"] = (soup.title.get_text(strip=True) if soup.title else "")[:120]
        words = BRAND_WORDS.get(row["brand"], [row["brand"].lower()])
        out["brand_ok"] = str(any(w in (out["title"] + r.url).lower() for w in words))
        a = jsonld_address(r.text)
        if a:
            out.update(address=a[0], addr_city=a[1], zip=a[2], lat=a[3], lon=a[4], site_name=a[5])
    return out


if __name__ == "__main__":
    rows = list(csv.DictReader(open(sys.argv[1])))
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(check, rows))
    with open(sys.argv[2], "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(res[0].keys()))
        w.writeheader()
        w.writerows(res)
    for r in res:
        print(r["brand"], "|", r["dealer_name"], "|", r["site_status"], "|", r["final_url"][:60], "|", r["title"][:60], "|", r["addr_city"], r["zip"])
