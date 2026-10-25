"""One-time check, run on the laptop: can the brands' own certified searches be read from a home connection?

    python search.py update
    python tools/probe_feeds.py

For each brand it reads robots.txt (and stays off pages it disallows), opens the brand's certified search
page in the browser add-on with our honest User-Agent, and lists the data requests the page makes (the
inventory service a brand feed would use). It changes nothing and uploads nothing; copy what it prints into
the chat. The full details are also written to probe_report.txt in this folder.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.base import SCRAPE, fetcher   # noqa: E402

PAGES = {   # the brand's certified search pages (several guesses each; redirects are followed)
    "Acura": ["https://www.acura.com/certified-pre-owned", "https://www.acuracertified.com/",
              "https://www.acura.com/tools/inventory-search"],
    "BMW": ["https://www.bmwusa.com/certified-preowned-search/", "https://www.bmwusa.com/certified-pre-owned.html"],
}
DATA_WORDS = ("inventory", "vehicle", "search", "cpo", "certified", "graphql", "api", "stock", "dealer")


def robots(url: str) -> tuple[str, bool]:
    f = fetcher()
    base = "{0.scheme}://{0.netloc}".format(urlparse(url))
    try:
        r = f.session.get(base + "/robots.txt", timeout=SCRAPE["timeout_seconds"])
        status = f"HTTP {r.status_code}"
    except Exception as e:      # noqa: BLE001
        status = type(e).__name__
    return status, f.allowed(url)


def probe(brand: str, pages: list[str], pw) -> dict:
    out = {"brand": brand, "pages": []}
    browser = pw.chromium.launch()
    ctx = browser.new_context(user_agent=SCRAPE["user_agent"])
    for url in pages:
        print(f"  {url}", flush=True)
        rs, ok = robots(url)
        rec = {"url": url, "robots": rs, "allowed": ok, "requests": []}
        out["pages"].append(rec)
        if not ok:
            rec["note"] = "robots.txt says no (or can't be read): not opened"
            continue
        page = ctx.new_page()
        def seen(resp, rec=rec):
            req = resp.request
            if req.resource_type in ("xhr", "fetch") and any(w in resp.url.lower() for w in DATA_WORDS):
                try:
                    size = len(resp.body())
                except Exception:   # noqa: BLE001
                    size = -1
                rec["requests"].append({"method": req.method, "status": resp.status, "bytes": size, "url": resp.url[:300],
                                        "type": resp.headers.get("content-type", "")[:40]})
        page.on("response", seen)
        try:
            r = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(8000)        # let the page ask for its inventory data
            rec["status"], rec["final_url"], rec["title"] = (r.status if r else None), page.url, page.title()[:80]
            rec["text"] = page.inner_text("body")[:300].replace("\n", " ")
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
        page.close()
    browser.close()
    return out


def main() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("The browser add-on (Playwright) isn't installed; see LAPTOP.md.")
        return
    report = []
    with sync_playwright() as pw:
        for brand, pages in PAGES.items():
            print(f"Checking {brand} ...", flush=True)
            report.append(probe(brand, pages, pw))
    (ROOT / "probe_report.txt").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("\n===== copy from here =====")
    for b in report:
        for p in b["pages"]:
            print(f"{b['brand']} | {p['url']} | robots {p['robots']}{'' if p['allowed'] else ' (not allowed)'} | "
                  f"page {p.get('status', '-')} {p.get('title', p.get('error', p.get('note', '')))}")
            for q in p["requests"][:12]:
                print(f"   {q['method']} {q['status']} {q['bytes']}b {q['url'][:160]}")
    print("===== to here =====")


if __name__ == "__main__":
    main()
