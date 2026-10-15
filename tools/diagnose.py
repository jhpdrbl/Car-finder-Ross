"""Record what each dealer site exposes, so adapters can be tuned for sites that
can't be reached from Claude's cloud machine (Audi, Dealer Inspire, ...).

Writes output/diagnose_<date>.md. It contains only public page structure (status
codes, sitemap sizes, sample listing URLs, which fields parsed), no personal data.
"""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

from core.pipeline import discover, homepage_status
from scrapers import playwright_fallback
from scrapers.base import FetchError, fetcher
from scrapers.generic_jsonld import fetch_vdp, sitemap_urls

ROOT = Path(__file__).resolve().parent.parent


def _probe(url: str) -> str:
    try:
        r = fetcher().get(url)
        return f"HTTP {r.status_code}, {len(r.text):,} bytes" + (" (cloudflare)" if "cloudflare" in r.text[:3000].lower() else "")
    except FetchError as e:
        return f"error: {str(e)[:100]}"


def run(brand: str | None = None, platform: str | None = None, dealer: str | None = None, limit: int = 25) -> Path:
    with (ROOT / "data" / "dealers.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if brand:
        rows = [r for r in rows if r["brand"].lower() == brand.lower()]
    if platform:
        rows = [r for r in rows if r["platform"] == platform]
    if dealer:
        rows = [r for r in rows if dealer.lower() in r["dealer_name"].lower()]
    rows = rows[:limit]
    out = [f"# Dealer site diagnostics — {date.today().isoformat()}", "",
           f"Playwright installed: {playwright_fallback.available()}", f"Dealers checked: {len(rows)}", ""]
    for d in rows:
        home = d["homepage"]
        print(f"checking {d['dealer_name']} ...", flush=True)
        out += [f"## {d['brand']} · {d['dealer_name']} ({home})", f"- platform on file: {d['platform'] or '?'}"]
        ok, why = homepage_status(home)
        out.append(f"- homepage: {'OK' if ok else why}")
        out.append(f"- /llms.txt: {_probe(home + '/llms.txt')}")
        out.append(f"- robots sitemaps: {', '.join(sitemap_urls(home))[:300]}")
        if not ok:
            out.append("")
            continue
        try:
            r = fetcher().get(home + "/")
            links = sorted(set(u for u in re.findall(r'href="([^"#]+)"', r.text)
                               if re.search(r"(used|certified|cpo|pre-?owned|inventory)", u, re.I)))[:15]
            out.append(f"- inventory-looking links on homepage: {links}")
        except FetchError as e:
            out.append(f"- homepage links: {e}")
        cands, note = discover(d)
        out.append(f"- discovery: {note}")
        out.append(f"- sample listing URLs: {cands[:5]}")
        for u in cands[:2]:
            L, err = fetch_vdp(u)
            if L is None and playwright_fallback.available():
                L, err = playwright_fallback.fetch_vdp_rendered(u)
            if L:
                got = {k: getattr(L, k) for k in ("vin", "year", "model", "trim", "price", "mileage", "ext_color",
                                                  "int_color", "drivetrain", "sunroof", "cert_text", "carfax_badges")}
                out.append(f"- parsed {u}: {got}")
            else:
                out.append(f"- could not parse {u}: {err}")
        out.append("")
    path = ROOT / "output" / f"diagnose_{date.today().isoformat()}.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return path
