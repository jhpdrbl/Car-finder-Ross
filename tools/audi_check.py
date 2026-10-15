"""Can this device see Audi's own certified search (audiusa.com), and does audiusa.com allow it?
Made for running on the iPad (a-Shell) on home Wi-Fi:

    python tools/audi_check.py

Prints: robots.txt status and the rules that matter, whether the CPO search page loads, and any
data (API) addresses the page refers to. Screenshot the output for Claude. Read-only, a few requests.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.robotparser import RobotFileParser

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from scrapers.base import CONFIG  # noqa: E402

UA = CONFIG["scrape"]["user_agent"]
SITE = "https://www.audiusa.com"
PAGE = SITE + "/en/inventory/?entry=true&type=cpo"
API_HINT = re.compile(r"""["'(]((?:https?:)?//[^"'()\s]*?(?:api|graphql|inventory|vehicle|search|stock|scs)[^"'()\s]*)""", re.I)


def main() -> None:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

    r = s.get(SITE + "/robots.txt", timeout=30)
    print(f"robots.txt: HTTP {r.status_code}")
    rp = None
    if r.ok:
        rp = RobotFileParser()
        rp.parse(r.text.splitlines())
        rules = [l for l in r.text.splitlines() if re.match(r"\s*(user-agent|disallow|allow)\s*:", l, re.I)]
        print("  rules:", " | ".join(rules[:25]) or "(none)")
        ua = UA.split("/")[0]
        for path in ("/en/inventory/", "/en/inventory/?type=cpo", "/content/dam/", "/api/"):
            print(f"  allowed for us: {path:28} {rp.can_fetch(ua, SITE + path)}")
    time.sleep(3)

    r = s.get(PAGE, timeout=30)
    html = r.text
    print(f"CPO search page: HTTP {r.status_code}, {len(html):,} characters")
    if r.ok:
        print("  title:", (re.search(r"<title>(.*?)</title>", html, re.S | re.I) or [None, "?"])[1].strip()[:100])
        urls = sorted({u for u in API_HINT.findall(html) if "audi" in u.lower()})
        print(f"  data addresses mentioned on the page ({len(urls)}):")
        for u in urls[:20]:
            print("   ", u[:150])
        if "vin" in html.lower():
            print("  the page text mentions VINs (cars may be in the page itself)")
    print("Done. Screenshot this for Claude.")


if __name__ == "__main__":
    main()
