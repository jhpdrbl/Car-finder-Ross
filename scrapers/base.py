"""Shared fetching: caching, per-domain rate limiting, robots.txt, User-Agent."""
from __future__ import annotations

import os
import random
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

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


class Robots:
    """robots.txt per RFC 9309: groups by user-agent (most specific match, else *), Allow/Disallow with
    * and $ patterns, longest match wins, Allow wins a tie. (Python's urllib.robotparser ignores
    wildcards, which made some disallowed URLs look allowed.)"""

    def __init__(self, text: str = "", allow_all: bool = False, deny_all: bool = False, why: str = ""):
        self.allow_all, self.deny_all, self.why = allow_all, deny_all, why
        self.groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        in_rules = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if in_rules:                      # a new group starts
                    self.groups.append((agents, rules))
                    agents, rules, in_rules = [], [], False
                agents.append(val.lower())
            elif key in ("allow", "disallow"):
                in_rules = True
                if val:                           # "Disallow:" (empty) allows everything
                    rules.append((key == "allow", val))
        if agents:
            self.groups.append((agents, rules))

    def _rules_for(self, ua: str) -> list[tuple[bool, str]]:
        ua = ua.lower()
        mine = [r for agents, r in self.groups for a in agents if a != "*" and a in ua]
        if mine:
            return [x for r in mine for x in r]
        return [x for agents, r in self.groups if "*" in agents for x in r]

    @staticmethod
    def _matches(pattern: str, path: str) -> int:
        """Length of the pattern if it matches the path (from its start), else -1."""
        rx = "^" + re.escape(pattern).replace(r"\*", ".*")
        if rx.endswith(r"\$"):
            rx = rx[:-2] + "$"
        return len(pattern) if re.match(rx, path) else -1

    def can_fetch(self, ua: str, url: str) -> bool:
        if self.allow_all:
            return True
        if self.deny_all:
            return False
        p = urlparse(url)
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        best_len, allowed = -1, True
        for allow, pattern in self._rules_for(ua):
            n = self._matches(pattern, path)
            if n > best_len or (n == best_len and allow):
                best_len, allowed = n, allow
        return allowed


class Fetcher:
    def __init__(self, cache_name: str = ".cache/http", use_cache: bool = True):
        (ROOT / ".cache").mkdir(exist_ok=True)
        if use_cache:
            # Pages are kept in memory for the run. The SQLite cache breaks when many threads share it:
            # it deadlocked on the iPad (Oct 15 2026) and failed with "DatabaseError: another row available"
            # on the laptop once feeds and dealer sites ran side by side (Oct 24 2026). Runs are a day apart
            # and the cache only lasts 6 h, so keeping it on disk gained little. CARFINDER_CACHE=sqlite brings it back.
            self.session = requests_cache.CachedSession(
                str(ROOT / cache_name),
                backend=os.environ.get("CARFINDER_CACHE", "memory"),
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
        self._robots: dict[str, Robots] = {}
        self._last_hit: dict[str, float] = {}
        self._host_locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    # -- politeness -------------------------------------------------------
    def _robots_for(self, url: str) -> Robots:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        with self._lock:
            lock = self._host_locks.setdefault("robots:" + base, threading.Lock())
        with lock:
            return self._load_robots(base)

    def _load_robots(self, base: str) -> Robots:
        # RFC 9309: 2xx -> follow the file; 4xx (no file / forbidden) -> everything allowed;
        # 5xx or unreachable -> treat the whole site as off limits.
        if base not in self._robots:
            for wait in (5, 20, None):
                # A connection that breaks (SSLError, reset, timeout) is tried again before the site is written off:
                # on Oct 24 2026 the laptop's connection dropped for a few minutes and ~30 dealers failed at once.
                try:
                    r = self._raw_get(base + "/robots.txt", check_robots=False)
                    break
                except (requests.RequestException, FetchError) as e:
                    r = e
                    if wait is None or not isinstance(e, (requests.ConnectionError, requests.Timeout)):
                        break
                    time.sleep(wait)
            try:
                if isinstance(r, Exception):
                    raise r
                if r.status_code >= 500:
                    rp = Robots(deny_all=True, why=f"robots.txt unavailable (HTTP {r.status_code}), so the site is off limits")
                elif r.status_code >= 400:
                    rp = Robots(allow_all=True)
                else:
                    rp = Robots(r.text)
            except (requests.RequestException, FetchError) as e:
                rp = Robots(deny_all=True, why=f"robots.txt unreachable ({type(e).__name__}), so the site is off limits")
            self._robots[base] = rp
        return self._robots[base]

    def allowed(self, url: str) -> bool:
        ua = SCRAPE["user_agent"].split("/")[0]
        return self._robots_for(url).can_fetch(ua, url)

    def robots_reason(self, url: str) -> str:
        rp = self._robots_for(url)
        return rp.why or f"robots.txt disallows {url}"

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
            raise RobotsDisallowed(self.robots_reason(url))
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
            raise RobotsDisallowed(self.robots_reason(url))
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

    def forget(self, url: str) -> None:
        """Drop the cached copy of a URL (e.g. an error answer that came back with HTTP 200)."""
        cached = getattr(self.session, "cache", None)
        if cached is not None:
            try:
                cached.delete(urls=[url])
            except Exception:
                pass

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
