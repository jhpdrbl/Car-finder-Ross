"""Build the phone-friendly website (site/) from the latest laptop run's output/.

  index.html   Ross's dashboard (with several buyers: a start page to pick whose search); ross/index.html too
  digest.html  the latest digest, rendered, WITHOUT the buying-context lines
               (down payment, pre-approval) unless config publish.include_buying_context
  _headers     tells search engines not to index the site

Used by .github/workflows/publish.yml; you can also run it locally:
  python -m tools.build_site
"""
from __future__ import annotations

import html
import re
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
SITE = ROOT / "site"

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>CPO SUV Digest</title>
<style>
:root {{ --bg:#f5f6f4; --fg:#1d211f; --muted:#5f6862; --accent:#2c6e57; color-scheme: light; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#121513; --fg:#e5e9e6; --muted:#9aa49e; --accent:#7cc7a8; color-scheme: dark; }} }}
body {{ background:var(--bg); color:var(--fg); font:16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  max-width:780px; margin:0 auto; padding:20px max(16px, env(safe-area-inset-left, 0px)); }}
a {{ color:var(--accent); }} h1 {{ font-size:24px; }} h2 {{ font-size:19px; margin-top:28px; }}
li {{ margin:6px 0; }} em {{ color:var(--muted); }} nav {{ margin-bottom:12px; }}
</style></head><body><nav><a href="index.html">← Dashboard</a></nav>
{body}
</body></html>"""


def latest_digest(out: Path = OUT) -> Path | None:
    files = sorted(out.glob("digest_*.md"))
    return files[-1] if files else None


def strip_buying_context(md: str, cfg: dict) -> str:
    if cfg.get("publish", {}).get("include_buying_context"):
        return md
    private = {f"- {b}" for b in cfg.get("buying_context", [])}
    return "\n".join(l for l in md.splitlines() if l.strip() not in private)


def _page(out: Path, dest: Path, cfg: dict) -> None:
    """One buyer's dashboard (+ digest) from out/ into dest/."""
    dest.mkdir(parents=True, exist_ok=True)
    page = (out / "dashboard.html").read_text(encoding="utf-8")
    page = page.replace('<meta name="viewport"', '<meta name="robots" content="noindex"><meta name="viewport"', 1)
    dg = latest_digest(out)
    if dg:
        page = page.replace("every car links to the dealer's own listing</div>",
                            "every car links to the dealer's own listing · <a href=\"digest.html\">Read the digest</a></div>", 1)
        md = strip_buying_context(dg.read_text(encoding="utf-8"), cfg)
        try:
            import markdown
            body = markdown.markdown(md)
        except ImportError:
            body = "<pre>" + html.escape(md) + "</pre>"
        body = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', body)
        (dest / "digest.html").write_text(PAGE.format(body=body), encoding="utf-8")
    (dest / "index.html").write_text(page, encoding="utf-8")


def build() -> Path:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir()
    if not (OUT / "dashboard.html").exists():
        raise SystemExit("output/dashboard.html not found: run `python run.py refresh` first")
    # front page: pick whose search (output/index.html); each buyer's tracker at site/<id>/ (/ross/, /jenna/)
    front = OUT / "index.html"
    others = [pid for pid in (cfg.get("profiles") or {}) if pid != "ross"]
    _page(OUT, SITE / "ross", cfg)
    if others and front.exists() and all((OUT / pid / "dashboard.html").exists() for pid in others):
        (SITE / "index.html").write_text(front.read_text(encoding="utf-8").replace(
            '<meta name="viewport"', '<meta name="robots" content="noindex"><meta name="viewport"', 1), encoding="utf-8")
    else:                                                  # one buyer, or not every buyer has a page yet: Ross's page is the front page
        _page(OUT, SITE, cfg)
    for pid in (cfg.get("profiles") or {}):
        if pid != "ross" and (OUT / pid / "dashboard.html").exists():
            _page(OUT / pid, SITE / pid, cfg)
    (SITE / "_headers").write_text("/*\n  X-Robots-Tag: noindex, nofollow\n", encoding="utf-8")
    return SITE


if __name__ == "__main__":
    print(f"built {build()}")
