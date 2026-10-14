"""Render data/dealers.csv as a readable page: output/dealers.html.

Usage: python -m tools.dealer_page
"""
from __future__ import annotations

import csv
import html
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAND_ORDER = ["Genesis", "Audi", "Subaru", "BMW", "Mercedes-Benz", "Volkswagen", "Lexus", "Volvo", "Toyota", "Ford"]
NOT_FOUND = [  # dealers named in the spec that the official lists / web checks did not turn up
    ("BMW", "Shelly BMW (Buena Park)", "Real dealer, but I couldn't find its website. Please check BMW's dealer finder."),
    ("Volvo", "Volvo Cars Thousand Oaks", "Not found. May be the same store as Rusnak Volvo Cars Westlake (Thousand Oaks)."),
    ("Volvo", "Volvo Cars Tustin", "Website not found. Please check Volvo's dealer finder."),
    ("Audi", "Audi Brea / Audi Thousand Oaks", "Not found. Audi North Orange County (Placentia) and Audi Westlake (Thousand Oaks) are probably these."),
    ("Lexus", "Lexus of Pasadena", "Not on Lexus's official dealer list, so it likely doesn't exist."),
    ("Toyota", "Toyota of Sherman Oaks", "Not on Toyota's official dealer list, so it likely doesn't exist."),
]


def access(row: dict) -> str:
    n = row["notes"].lower()
    if "blocked" in n or "error" in n:
        return "blocked"
    return "ok"


def main() -> Path:
    rows = list(csv.DictReader((ROOT / "data" / "dealers.csv").open()))
    by_brand = defaultdict(list)
    for r in rows:
        by_brand[r["brand"]].append(r)
    total = len(rows)
    reachable = sum(access(r) == "ok" for r in rows)
    official = sum(r["source"] == "brand locator" for r in rows)
    within = sum(float(r["distance_mi"]) <= 50 for r in rows)

    def e(s):
        return html.escape(str(s or ""))

    sections = []
    for brand in BRAND_ORDER:
        rs = sorted(by_brand.get(brand, []), key=lambda r: float(r["distance_mi"]))
        if not rs:
            continue
        src_official = rs[0]["source"] == "brand locator"
        ok = sum(access(r) == "ok" for r in rs)
        trs = []
        for r in rs:
            d = float(r["distance_mi"])
            acc = access(r)
            host = r["homepage"].replace("https://", "").replace("www.", "")
            trs.append(
                f'<tr class="{"edge" if d > 50 else ""}">'
                f'<td class="name"><a href="{e(r["homepage"])}" target="_blank" rel="noopener">{e(r["dealer_name"])}</a>'
                f'<span class="host">{e(host)}</span></td>'
                f'<td>{e(r["city"])}</td>'
                f'<td class="num">{d:.0f}{"<small> edge</small>" if d > 50 else ""}</td>'
                f'<td><span class="chip {acc}">{"Loads" if acc == "ok" else "Blocks me"}</span></td>'
                f'<td class="plat">{e(r["platform"].replace("_", " ") or "–")}</td></tr>')
        sections.append(f"""
<section class="brand" id="{e(brand.lower().replace(' ', '-'))}">
  <header>
    <h2>{e(brand)} <span class="count">{len(rs)}</span></h2>
    <p class="src {'official' if src_official else 'manual'}">{'From ' + brand + "'s official dealer finder" if src_official else brand + "'s dealer finder blocked me. Found by web research, so please double-check"}</p>
    <p class="reach">{ok} of {len(rs)} websites load for me</p>
  </header>
  <div class="scroll"><table>
    <thead><tr><th>Dealer</th><th>City</th><th class="num">Miles</th><th>Website from the cloud</th><th>Platform</th></tr></thead>
    <tbody>{''.join(trs)}</tbody>
  </table></div>
</section>""")

    nf = "".join(f"<li><b>{e(b)}: {e(n)}.</b> {e(w)}</li>" for b, n, w in NOT_FOUND)
    page = f"""<title>LA CPO Dealer List</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono:wght@400&display=swap">
<style>
/* Layout: one reading column; brand sections stacked; tables scroll sideways on phones */
:root {{
  --bg: #f4f5f7; --surface: #ffffff; --fg: #1b1f27; --muted: #5d6573; --line: #dde1e7;
  --accent: #2f5d8a; --ok: #1f7a4d; --ok-bg: #e3f3ea; --bad: #a3361f; --bad-bg: #f8e6e1; --warn-bg: #fbf3dc; --warn: #7a5a00;
  --display: "Archivo", "Helvetica Neue", Arial, sans-serif;
  --body: "Source Sans 3", "Segoe UI", system-ui, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #12151b; --surface: #1a1e26; --fg: #e6e8ec; --muted: #9aa3b2; --line: #2b313c;
  --accent: #8db6e0; --ok: #7fd4a6; --ok-bg: #173226; --bad: #f0a08c; --bad-bg: #3a1f19; --warn-bg: #33290f; --warn: #e8c766; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --bg: #12151b; --surface: #1a1e26; --fg: #e6e8ec; --muted: #9aa3b2; --line: #2b313c;
  --accent: #8db6e0; --ok: #7fd4a6; --ok-bg: #173226; --bad: #f0a08c; --bad-bg: #3a1f19; --warn-bg: #33290f; --warn: #e8c766; color-scheme: dark; }}
body {{ background: var(--bg); color: var(--fg); font: 16px/1.5 var(--body);
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 24px 48px; }}
main {{ max-width: 980px; margin: 0 auto; display: grid; gap: 28px; }}
h1 {{ font: 800 clamp(26px, 5vw, 38px)/1.1 var(--display); margin: 0; letter-spacing: -0.01em; text-wrap: balance; }}
.lede {{ color: var(--muted); max-width: 62ch; margin: 8px 0 0; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }}
.stat {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; }}
.stat b {{ display: block; font: 700 26px/1.1 var(--display); font-variant-numeric: tabular-nums; }}
.stat span {{ color: var(--muted); font-size: 14px; }}
.callout {{ background: var(--warn-bg); color: var(--fg); border-radius: 8px; padding: 14px 16px; }}
.callout h3 {{ margin: 0 0 6px; font: 700 17px var(--display); color: var(--warn); }}
.callout p, .callout ul {{ margin: 6px 0 0; }}
.callout li {{ margin: 4px 0; }}
nav {{ display: flex; flex-wrap: wrap; gap: 8px; }}
nav a {{ color: var(--accent); text-decoration: none; border: 1px solid var(--line); border-radius: 999px; padding: 4px 12px; font-size: 14px; background: var(--surface); }}
nav a:focus-visible, td a:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
.brand header {{ display: grid; gap: 2px; margin-bottom: 8px; }}
h2 {{ font: 700 22px/1.2 var(--display); margin: 0; }}
.count {{ color: var(--muted); font-weight: 500; font-size: 16px; margin-left: 6px; }}
.src, .reach {{ margin: 0; font-size: 14px; }}
.src.official {{ color: var(--ok); }} .src.manual {{ color: var(--warn); }}
.reach {{ color: var(--muted); }}
.scroll {{ overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; }}
table {{ border-collapse: collapse; width: 100%; min-width: 560px; font-size: 15px; }}
th {{ text-align: left; font: 600 12px var(--body); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); padding: 10px 12px; border-bottom: 1px solid var(--line); }}
td {{ padding: 8px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
tr:last-child td {{ border-bottom: 0; }}
td.name a {{ color: var(--fg); font-weight: 600; text-decoration: none; }}
td.name a:hover {{ color: var(--accent); text-decoration: underline; }}
.host {{ display: block; font: 12px var(--mono); color: var(--muted); }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.num small {{ color: var(--warn); margin-left: 4px; }}
tr.edge td {{ color: var(--muted); }}
.chip {{ display: inline-block; font-size: 13px; font-weight: 600; padding: 1px 8px; border-radius: 999px; white-space: nowrap; }}
.chip.ok {{ background: var(--ok-bg); color: var(--ok); }}
.chip.blocked {{ background: var(--bad-bg); color: var(--bad); }}
.plat {{ color: var(--muted); font-size: 14px; }}
footer {{ color: var(--muted); font-size: 13px; }}
</style>
<main>
  <div>
    <h1>LA CPO Dealer List</h1>
    <p class="lede">Every franchise dealer for your 10 brands within 60 miles of 90039. Dealers 50–60 miles away are greyed and marked “edge”. Tap a dealer to open its website.</p>
  </div>
  <div class="stats">
    <div class="stat"><b>{total}</b><span>dealers</span></div>
    <div class="stat"><b>{within}</b><span>within 50 miles</span></div>
    <div class="stat"><b>{official}</b><span>from official dealer finders</span></div>
    <div class="stat"><b>{reachable}</b><span>websites that load for me</span></div>
  </div>
  <div class="callout">
    <h3>{total - reachable} dealer websites block me</h3>
    <p>Their security service blocks this cloud computer, not the cars. That includes every site on the Dealer Inspire platform, such as Genesis of Cerritos. From a home internet connection these sites normally load fine.</p>
  </div>
  <nav>{''.join(f'<a href="#{b.lower().replace(" ", "-")}">{b}</a>' for b in BRAND_ORDER if b in by_brand)}</nav>
  {''.join(sections)}
  <div class="callout">
    <h3>From your spec but not found</h3>
    <ul>{nf}</ul>
  </div>
  <footer>Built from data/dealers.csv. Official lists: Genesis, Subaru, Lexus, Toyota, Volkswagen. Web research: Audi, BMW, Mercedes-Benz, Ford, Volvo.</footer>
</main>
"""
    out = ROOT / "output" / "dealers.html"
    out.write_text(page)
    return out


if __name__ == "__main__":
    print(main())
