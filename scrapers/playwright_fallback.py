"""Last resort for JavaScript-only sites: load pages in a real (headless) Chromium.

Optional: needs `pip install playwright` and `python -m playwright install chromium`.
It is a normal browser visit with the same honest User-Agent marker, robots.txt
check and rate limit as every other fetch. It does not try to get past bot
challenges; a site that serves one is reported as blocked.
"""
from __future__ import annotations

import re
import threading
from urllib.parse import urljoin, urlparse

from .base import CONFIG, FetchError, fetcher
from core.profiles import min_year
from .listing import VIN_ANY, url_condition, url_matches_brand_models, url_years

_lock = threading.BoundedSemaphore(3)   # up to 3 browsers at once (different sites); keeps memory use modest
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36 "
      + CONFIG["scrape"]["user_agent"].split(" ")[0])
INVENTORY_HINT = re.compile(r"(used|pre-?owned|certified|cpo|inventory|search)", re.I)
CHALLENGE = re.compile(r"(just a moment|attention required|access denied|verify you are human|site currently not available)", re.I)


def available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def render(url: str, wait_ms: int = 6000) -> tuple[str, str]:
    """Return (final_url, html). Raises FetchError when blocked or unavailable."""
    if not available():
        raise FetchError("playwright not installed")
    f = fetcher()
    if not f.allowed(url):
        raise FetchError(f"robots.txt disallows {url}")
    f._throttle(urlparse(url).netloc.lower())
    from playwright.sync_api import sync_playwright
    with _lock, sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context(user_agent=UA, locale="en-US").new_page()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(wait_ms)
            for _ in range(3):  # lazy-loaded result grids
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(800)
            html, final = page.content(), page.url
            status = resp.status if resp else 0
        finally:
            browser.close()
    if status >= 400 or CHALLENGE.search(html[:5000]):
        raise FetchError(f"browser blocked (HTTP {status})")
    return final, html


def _vdp_links(html: str, base: str, brand: str) -> list[str]:
    out = []
    host = urlparse(base).netloc.replace("www.", "")
    for href in re.findall(r'href="([^"#]+)"', html):
        u = urljoin(base, href.replace("&amp;", "&"))
        if host not in u or url_condition(u) == "new":
            continue
        has_id = VIN_ANY.search(u.split("?")[0]) or re.search(r"vehicleid=|/vdp/|[0-9a-f]{32}", u, re.I)
        if has_id and url_matches_brand_models(u, brand) and (not url_years(u) or max(url_years(u)) >= min_year(brand)):
            out.append(u)
    return list(dict.fromkeys(out))


def discover_by_browsing(homepage: str, brand: str, inventory_url: str = "") -> tuple[list[str], str]:
    """Open the dealer's used/certified inventory pages in a browser and collect car links."""
    try:
        start_pages = [inventory_url] if inventory_url else []
        if not start_pages:
            final, html = render(homepage)
            links = [urljoin(final, h) for h in re.findall(r'href="([^"#]+)"', html)]
            start_pages = [u for u in dict.fromkeys(links)
                           if urlparse(homepage).netloc.replace("www.", "") in u and INVENTORY_HINT.search(u)
                           and url_condition(u) != "new"][:4]
        found: list[str] = []
        for sp in start_pages:
            final, html = render(sp)
            found += _vdp_links(html, final, brand)
        found = list(dict.fromkeys(found))
        return found, f"browser: {len(start_pages)} inventory pages, {len(found)} candidates"
    except FetchError as e:
        return [], f"browser: {e}"


def fetch_vdp_rendered(url: str):
    from .generic_jsonld import parse_vdp
    try:
        final, html = render(url, wait_ms=4000)
    except FetchError as e:
        return None, str(e)
    L = parse_vdp(html, final)
    return (L, "") if L else (None, "no vehicle data on rendered page")
