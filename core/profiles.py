"""Buyers ("profiles"): each has its own rules, list of models, results, favorites and dashboard.

The dealer search runs once for everyone; every car found is then checked against each
buyer's rules separately. Ross is the original buyer and keeps the top-level settings in
config.yaml (and data/, output/ as before). Other buyers live under `profiles:` in config.yaml:
their settings are merged over the top-level ones (`models` is replaced, not merged), and their
results go to data/<id>/ and output/<id>/.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path

from scrapers.base import CONFIG

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "output"
DEFAULT = "ross"
REPLACE = {"models", "buying_context"}     # keys a profile replaces instead of merging into


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in REPLACE:
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


@dataclass
class Profile:
    id: str
    label: str
    cfg: dict            # full settings for this buyer (top-level config with the profile's overrides)
    data: Path           # listings.csv, price_history.csv, exclusions.csv, confirmed.csv
    out: Path            # dashboard.html, digests

    @property
    def is_default(self) -> bool:
        return self.id == DEFAULT

    @property
    def href(self) -> str:
        """Where this buyer's page lives on the website (the front page "/" asks whose search to show)."""
        return f"/{self.id}/"

    def models(self) -> dict:
        return self.cfg.get("models") or {}


def _load() -> dict[str, Profile]:
    base = {k: v for k, v in CONFIG.items() if k != "profiles"}
    out = {}
    for pid, over in (CONFIG.get("profiles") or {DEFAULT: {}}).items():
        over = dict(over or {})
        label = over.pop("label", pid.title())
        if pid == DEFAULT:
            out[pid] = Profile(pid, label, _merge(base, over), DATA, OUT)
        else:
            out[pid] = Profile(pid, label, _merge(base, over), DATA / pid, OUT / pid)
    if DEFAULT not in out:
        out = {DEFAULT: Profile(DEFAULT, "Ross", base, DATA, OUT), **out}
    return out


PROFILES = _load()


def all_profiles() -> list[Profile]:
    return list(PROFILES.values())


def get(pid: str | None = None) -> Profile:
    return PROFILES[pid or DEFAULT]


# Search scope = what ANY buyer could want (the search runs once for everyone)
MIN_YEAR = min(int(p.cfg["filters"]["min_year"]) for p in PROFILES.values())
MAX_PRICE = max(max(v for v in (p.cfg["filters"].get("price_caps") or {}).values() if v) +
                (p.cfg["filters"].get("price_tolerance") or 0) for p in PROFILES.values())
BRANDS = sorted({b for p in PROFILES.values() for b in p.models()})


def model_tokens(brand: str) -> list[str]:
    """URL / search words for a brand's models, across all buyers (config `tokens:` per brand)."""
    seen: list[str] = []
    for p in PROFILES.values():
        for t in (p.models().get(brand) or {}).get("tokens") or []:
            if t not in seen:
                seen.append(t)
    return seen


def could_want(brand: str, model: str, year: int | None = None, fuel: str | None = None) -> bool:
    """Might any buyer want this car? Used to skip pages and feed rows before reading them in full."""
    m = (model or "").lower()
    for p in PROFILES.values():
        spec = p.models().get(brand)
        if not spec or (m and not re.search(spec["allow"], m)):
            continue
        if year and year < int(p.cfg["filters"]["min_year"]):
            continue
        fuels = p.cfg["filters"].get("fuels")
        if fuel and fuels and fuel not in fuels:
            continue
        return True
    return False


def min_year(brand: str) -> int:
    """Earliest model year any buyer wants from this brand (so older Audis aren't read just because Jenna takes 2020+ Toyotas)."""
    ys = [int(p.cfg["filters"]["min_year"]) for p in PROFILES.values() if brand in p.models()]
    return min(ys) if ys else MIN_YEAR
