"""Shared fetching: caching, per-domain rate limiting, robots.txt, User-Agent."""
from __future__ import annotations

import os
import random
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
import requests_cache
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text())
SCRAPE = CONFIG["scrape"]

# Hosts we never fetch from. Aggregators may be used by a human for leads only.
BLOCKED_HOSTS = (
    "carfax.com", "edmunds.com", "autotrader.com", "kbb.com", "cargurus.com",
    "cars.com", "capitalone.com", "iseecars.com", "westlakefinancial.com", "westlake.com",
    "netlook.com", "netlookauto.com",
)


def is_blocked_host(host: str) -> bool:
    """True for an aggregator/CARFAX domain or any subdomain of one.

    Matches on whole domain labels, so dealer sites like volvocarsofsantamonica.com
    or mckennacars.com are not caught by "cars.com".
    """
    host = host.split(":")[0].lower().rstrip(".")
    return any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS)


class FetchError(Exception):
    """A fetch failed in a way worth reporting in the coverage report."""


class RobotsDisallowed(FetchError):
    pass


class Fetcher:
    def __init__(self, cache_name: str = ".cache/http", use_cache: bool = True):
        (ROOT / ".cache").mkdir(exist_ok=True)
        if use_cache:
            # CARFINDER_CACHE=memory (set by ipad.py): on the iPad (a-Shell) the SQLite cache deadlocks
            # when many threads share it, so pages are kept in memory for the run instead.
            self.session = requests_cache.CachedSession(
                str(ROOT / cache_name),
                backend=os.environ.get("CARFINDER_CACHE", "sqlite"),
                expire_after=SCRAPE["cache_hours"] * 3600,
                allowable_codes=(200, 301, 302, 404),
                allowable_methods=("GET", "POST"),
            )
        else:
            self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": SCRAPE["user_agent"],
            "Accept-Language": "en-US,en;q=0.9",
        })
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}
        self._host_locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    # -- politeness -------------------------------------------------------
    def _robots_for(self, url: str) -> RobotFileParser | None:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        with self._lock:
            lock = self._host_locks.setdefault("robots:" + base, threading.Lock())
        with lock:
            return self._load_robots(base)

    def _load_robots(self, base: str) -> RobotFileParser | None:
        if base not in self._robots:
            rp = RobotFileParser()
            try:
                r = self._raw_get(base + "/robots.txt", check_robots=False)
                if r.status_code >= 400:
                    rp = None  # no robots.txt -> everything allowed
                else:
                    rp.parse(r.text.splitlines())
            except (requests.RequestException, FetchError):
                rp = None
            self._robots[base] = rp
        return self._robots[base]

    def allowed(self, url: str) -> bool:
        rp = self._robots_for(url)
        if rp is None:
            return True
        ua = SCRAPE["user_agent"].split("/")[0]
        return rp.can_fetch(ua, url)

    def _throttle(self, host: str) -> None:
        """One request per 2-3 s per domain; different domains don't wait on each other."""
        with self._lock:
            lock = self._host_locks.setdefault(host, threading.Lock())
        with lock:
            wait = random.uniform(SCRAPE["min_delay_seconds"], SCRAPE["max_delay_seconds"])
            delta = time.monotonic() - self._last_hit.get(host, 0.0)
            if delta < wait:
                time.sleep(wait - delta)
            self._last_hit[host] = time.monotonic()

    def _raw_get(self, url: str, check_robots: bool = True, **kw) -> requests.Response:
        host = urlparse(url).netloc.lower()
        if is_blocked_host(host):
            raise FetchError(f"blocked host (aggregator/carfax): {host}")
        if check_robots and not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        resp = None
        cached = getattr(self.session, "cache", None)
        if cached is not None:
            try:
                resp = self.session.get(url, timeout=SCRAPE["timeout_seconds"], only_if_cached=True, **kw)
                if resp.status_code == 504:
                    resp = None
            except Exception:
                resp = None
        if resp is None:
            self._throttle(host)
            resp = self.session.get(url, timeout=SCRAPE["timeout_seconds"], **kw)
        return resp

    # -- public -----------------------------------------------------------
    def get(self, url: str, **kw) -> requests.Response:
        try:
            return self._raw_get(url, **kw)
        except requests.RequestException as e:
            raise FetchError(f"{type(e).__name__}: {e}") from e

    def post_json(self, url: str, payload, **kw):
        """POST (used for a few official JSON APIs, e.g. NHTSA batch VIN decode)."""
        host = urlparse(url).netloc.lower()
        if is_blocked_host(host):
            raise FetchError(f"blocked host (aggregator/carfax): {host}")
        if not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        self._throttle(host)
        try:
            r = self.session.post(url, data=payload, timeout=SCRAPE["timeout_seconds"], **kw)
        except requests.RequestException as e:
            raise FetchError(f"{type(e).__name__}: {e}") from e
        if r.status_code != 200:
            raise FetchError(f"HTTP {r.status_code} for {url}")
        try:
            return r.json()
        except ValueError as e:
            raise FetchError(f"non-JSON response from {url}") from e

    def get_json(self, url: str, **kw):
        r = self.get(url, **kw)
        if r.status_code != 200:
            raise FetchError(f"HTTP {r.status_code} for {url}")
        try:
            return r.json()
        except ValueError as e:
            raise FetchError(f"non-JSON response from {url}") from e


_default: Fetcher | None = None


def fetcher() -> Fetcher:
    global _default
    if _default is None:
        _default = Fetcher()
    return _default
