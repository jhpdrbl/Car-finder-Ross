"""Digest (markdown for Apple Notes), coverage report, and the static HTML dashboard."""
from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

from scrapers.base import CONFIG

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
TRIM_GUIDE = ROOT / "data" / "trim_guide.json"   # hand-researched reference for the Trim guide tab
WARRANTY = ROOT / "data" / "warranty.json"        # factory + certified pre-owned warranty terms by brand


FUEL_LABEL = {"gas": "Gas", "hybrid": "Hybrid", "phev": "Plug-in hybrid", "ev": "Electric"}


def _money(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "?"


def _miles(v) -> str:
    try:
        return f"{int(float(v)):,} mi"
    except (TypeError, ValueError):
        return "? mi"


def _features(r: dict) -> str:
    bits = []
    if r.get("sunroof") == "True":
        bits.append("sunroof")
    if r.get("audio"):
        bits.append(r["audio"])
    if r.get("leather") == "True":
        bits.append("leather")
    if r.get("ventilated_seats") == "True":
        bits.append("ventilated seats")
    if r.get("cpo_program"):
        bits.append(r["cpo_program"])
    return ", ".join(bits)


def _carfax(r: dict) -> str:
    s = r.get("carfax_status", "not_verified")
    return {"clean": "CARFAX: no accidents", "accident": "CARFAX: accident"}.get(s, "CARFAX: not verified")


def _title(r: dict) -> str:
    return " ".join(x for x in (str(r.get("year") or ""), r.get("make", ""), r.get("model", ""), r.get("trim", "")) if x).strip()


def _line(r: dict) -> str:
    t = _title(r)
    link = f"[{t}]({r['listing_url']})" if r.get("listing_url") else t
    colors = " / ".join(x for x in (r.get("ext_color"), r.get("int_color")) if x) or "colors ?"
    parts = [f"**{link}** at {r.get('dealer', '?')}", f"VIN {r['vin']}", _money(r.get("price_total")) +
             (" (fees est.)" if r.get("fees_estimated") == "True" else ""), _miles(r.get("mileage")), colors]
    parts.append(FUEL_LABEL.get(r.get("fuel_type", ""), "fuel ?"))
    if r.get("mpg_combined"):
        parts.append(f"{float(r['mpg_combined']):.0f} mpg" + (" gas-only" if r.get("fuel_type") == "phev" else "")
                     + (" (EPA)" if r.get("mpg_source") == "EPA" else ""))
    feats = _features(r)
    if feats:
        parts.append(feats)
    parts.append(_carfax(r))
    if r.get("est_monthly_cost"):
        parts.append(f"~{_money(r['est_monthly_cost'])}/mo")
    if r.get("score"):
        parts.append(f"score {r['score']}")
    line = "- " + " · ".join(parts)
    extra = [n for n in (r.get("notes") or "").split("; ") if n]
    if r.get("recall_flags"):
        extra.append(f"recalls to confirm completed: {r['recall_flags'][:160]}")
    if extra:
        line += "\n  - " + "; ".join(extra)
    return line


def coverage_rows(results, feed_stats: dict) -> list[dict]:
    rows = []
    for brand, st in feed_stats.items():
        rows.append({"brand": brand, "dealer": f"{brand} brand CPO feed", "status": st["status"],
                     "reason": st.get("reason") or f"{st.get('in_area', 0)} certified listings at our dealers",
                     "listings": st.get("in_area", ""), "distance_mi": "", "homepage": ""})
    for r in sorted(results, key=lambda r: (r.dealer["brand"], r.status != "success", float(r.dealer["distance_mi"] or 0))):
        rows.append({"brand": r.dealer["brand"], "dealer": r.dealer["dealer_name"], "status": r.status,
                     "reason": r.reason, "listings": r.parsed + len(r.carried), "distance_mi": r.dealer["distance_mi"],
                     "homepage": r.dealer["homepage"], "method": r.method})
    return rows


def write_digest(rows: list[dict], changes: dict, cov: list[dict], today: str | None = None) -> Path:
    today = today or date.today().isoformat()
    active = [r for r in rows if r.get("status") == "active"]
    matches = sorted([r for r in active if not r.get("needs_call")], key=lambda r: -float(r.get("score") or 0))
    calls = sorted([r for r in active if r.get("needs_call")], key=lambda r: -float(r.get("score") or 0))
    ok = [c for c in cov if c["status"] == "success"]
    failed = [c for c in cov if c["status"] == "failed"]
    skipped = [c for c in cov if c["status"] == "skipped"]
    L = [f"# CPO SUV digest — {today}", ""]
    L += [f"- {b}" for b in CONFIG["buying_context"]]
    L += ["", "## Coverage report", "",
          f"{len(ok)} sources read · {len(failed)} failed · {len(skipped)} skipped (covered by a brand feed)", ""]
    if failed:
        L.append("**Failed:**")
        for c in failed:
            L.append(f"- {c['brand']} · {c['dealer']} ({c['distance_mi']} mi): {c['reason']}")
        L.append("")
    L.append("**Read:**")
    for c in ok:
        L.append(f"- {c['brand']} · {c['dealer']}: {c['reason']}")
    L += ["", f"## ✅ Meets all criteria ({len(matches)})", ""]
    L += [_line(r) for r in matches] or ["- none this run"]
    new_vins = {r["vin"] for r in changes["new"]}
    L += ["", f"## 🆕 New since last run ({len([r for r in active if r['vin'] in new_vins])})", ""]
    L += [_line(r) + ("\n  - ⚠️ needs a call: " + r["needs_call"] if r.get("needs_call") else "")
          for r in active if r["vin"] in new_vins] or ["- none"]
    L += ["", f"## 💲 Price changes ({len(changes['price'])})", ""]
    for r, old, new in changes["price"]:
        if r.get("status") == "active":
            arrow = "⬇️" if new < old else "⬆️"
            L.append(f"- {arrow} [{_title(r)}]({r.get('listing_url', '')}) at {r.get('dealer')}: {_money(old)} → {_money(new)} · VIN {r['vin']}")
    if not changes["price"]:
        L.append("- none")
    L += ["", f"## ⚠️ Needs a call ({len(calls)})", "", "_Passes everything the page showed; the items listed weren't on the page._", ""]
    for r in calls:
        L.append(_line(r) + f"\n  - **ask about:** {r['needs_call']}")
    if not calls:
        L.append("- none")
    gone = changes["removed"] + changes["newly_excluded"]
    L += ["", f"## ❌ Removed / sold / newly excluded ({len(gone)})", ""]
    for r in gone:
        L.append(f"- {_title(r)} at {r.get('dealer')} · VIN {r['vin']}: {r.get('fail_reasons') or r.get('status')}")
    if not gone:
        L.append("- none")
    L += ["", "_Every result links to the dealer's own listing page. CARFAX status comes from the dealer page's badge only. "
          "Recalls are model-level campaigns; check the VIN at https://www.nhtsa.gov/recalls._", ""]
    OUT.mkdir(exist_ok=True)
    path = OUT / f"digest_{today}.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def write_dashboard(rows: list[dict], history: list[dict], cov: list[dict], today: str | None = None) -> Path:
    today = today or date.today().isoformat()
    active = [r for r in rows if r.get("status") == "active"]
    hist: dict[str, list] = {}
    for h in history:
        hist.setdefault(h["vin"], []).append([h["date"], float(h["price"])])
    latest_run = max((r.get("seen_run") or "" for r in rows), default="")
    cars = []
    for r in active:
        cars.append({k: r.get(k, "") for k in ("vin", "dealer", "listing_url", "year", "make", "model", "trim", "price_total",
                                               "mileage", "ext_color", "int_color", "fuel_type", "sunroof", "audio",
                                               "carfax_status", "est_monthly_cost", "score", "needs_call", "notes",
                                               "mpg_combined", "mpg_city", "mpg_hwy", "mpg_source",
                                               "cpo_program", "first_seen", "distance_mi", "fees_estimated")}
                    | {"hist": hist.get(r["vin"], []),
                       "is_new": bool(latest_run) and r.get("new_run") == latest_run})
    ok = sum(c["status"] == "success" for c in cov)
    failed = [c for c in cov if c["status"] == "failed"]
    skipped = sum(c["status"] == "skipped" for c in cov)
    # cars that were on the dashboard (active) and have since sold / been removed by the dealer
    gone = []
    for r in rows:
        if r.get("status") == "sold":
            gone.append({k: r.get(k, "") for k in ("vin", "dealer", "listing_url", "year", "make", "model", "trim",
                                                   "price_total", "mileage", "ext_color", "int_color", "fuel_type",
                                                   "mpg_combined", "needs_call", "first_seen", "last_seen",
                                                   "removed_on", "fail_reasons", "distance_mi")}
                        | {"hist": hist.get(r["vin"], [])})
    guide = json.loads(TRIM_GUIDE.read_text(encoding="utf-8")) if TRIM_GUIDE.exists() else {"models": []}
    warranty = json.loads(WARRANTY.read_text(encoding="utf-8")) if WARRANTY.exists() else {"brands": []}
    data = json.dumps({"cars": cars, "gone": gone, "failed": failed, "guide": guide, "warranty": warranty}, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", data).replace("__DATE__", html.escape(today)) \
        .replace("__OK__", str(ok)).replace("__FAILED__", str(len(failed))).replace("__SKIPPED__", str(skipped)) \
        .replace("__MATCHES__", str(sum(1 for c in cars if not c["needs_call"]))) \
        .replace("__CALLS__", str(sum(1 for c in cars if c["needs_call"]))) \
        .replace("__NAVAIL__", str(len(cars))).replace("__NGONE__", str(len(gone)))
    OUT.mkdir(exist_ok=True)
    path = OUT / "dashboard.html"
    path.write_text(page, encoding="utf-8")
    return path


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CPO SUV Finder</title>
<style>
:root { --bg:#f5f6f4; --surface:#fff; --fg:#1d211f; --muted:#5f6862; --line:#dde2de; --accent:#2c6e57;
  --ok:#1f7a4d; --ok-bg:#e2f2e9; --warn:#7a5a00; --warn-bg:#fbf1d6; --bad:#a3361f; --bad-bg:#f7e4df; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#121513; --surface:#1a1f1c; --fg:#e5e9e6; --muted:#9aa49e; --line:#2a312d;
  --accent:#7cc7a8; --ok:#7fd4a6; --ok-bg:#173226; --warn:#e8c766; --warn-bg:#33290f; --bad:#f0a08c; --bad-bg:#3a1f19; color-scheme: dark; } }
:root[data-theme="dark"] { --bg:#121513; --surface:#1a1f1c; --fg:#e5e9e6; --muted:#9aa49e; --line:#2a312d;
  --accent:#7cc7a8; --ok:#7fd4a6; --ok-bg:#173226; --warn:#e8c766; --warn-bg:#33290f; --bad:#f0a08c; --bad-bg:#3a1f19; color-scheme: dark; }
[hidden] { display:none !important; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; padding-block:20px; padding-left:max(16px, env(safe-area-inset-left, 0px)); padding-right:max(16px, env(safe-area-inset-right, 0px)); }
main { max-width:1200px; margin:0 auto; display:grid; gap:18px; }
main > * { min-width:0; }  /* wide tables scroll inside .wrap instead of widening the page */
h1 { margin:0; font-size:26px; letter-spacing:-.01em; } .muted { color:var(--muted); }
.tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(140px,1fr)); gap:10px; }
.tile { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
.tile b { display:block; font-size:24px; font-variant-numeric:tabular-nums; }
details { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
details li { margin:3px 0; }
.controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
input, select { font:inherit; padding:6px 8px; border:1px solid var(--line); border-radius:6px; background:var(--surface); color:var(--fg); }
.filters { display:grid; gap:8px; }
.tabs { display:flex; gap:4px; border-bottom:1px solid var(--line); }
.tab { font:inherit; font-weight:600; background:none; border:0; border-bottom:3px solid transparent; color:var(--muted);
  padding:8px 12px; cursor:pointer; margin-bottom:-1px; }
.tab[aria-selected="true"] { color:var(--fg); border-bottom-color:var(--accent); }
.tab:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.tab .n { font-weight:500; color:var(--muted); margin-left:4px; }
.gone td.car a { color:var(--muted); }
.group { display:flex; flex-wrap:wrap; gap:6px; align-items:center; border:0; margin:0; padding:0; }
.group legend { float:left; font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin-right:6px; padding:0; min-width:56px; }
.pill { position:relative; }
.pill input { position:absolute; opacity:0; width:1px; height:1px; }
.pill span { display:inline-block; padding:4px 11px; border:1px solid var(--line); border-radius:999px; background:var(--surface);
  font-size:14px; cursor:pointer; user-select:none; }
.pill input:checked + span { background:var(--accent); border-color:var(--accent); color:var(--bg); }
.pill input:focus-visible + span { outline:2px solid var(--accent); outline-offset:2px; }
.clear { font:inherit; font-size:13px; background:none; border:0; color:var(--accent); cursor:pointer; text-decoration:underline; padding:4px; }
.wrap { overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:8px; }
table { border-collapse:collapse; width:100%; min-width:900px; }
th { text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); padding:9px 10px;
  border-bottom:1px solid var(--line); cursor:pointer; white-space:nowrap; user-select:none; }
/* header row stays on screen while scrolling the table (moved by stickHeads() in the script) */
thead th { position:relative; z-index:3; background:var(--surface); will-change:transform; }
thead.stuck th { box-shadow:0 1px 0 var(--line), 0 6px 10px -8px rgba(0,0,0,.35); }
#safe-top { position:fixed; top:0; height:env(safe-area-inset-top, 0px); width:0; visibility:hidden; }
th:hover { color:var(--fg); } td { padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
td.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
a { color:var(--accent); } .car a { font-weight:600; color:var(--fg); text-decoration:none; } .car a:hover { color:var(--accent); text-decoration:underline; }
.vin { font:12px ui-monospace, Menlo, Consolas, monospace; color:var(--muted); }
.chip { display:inline-block; font-size:12px; font-weight:600; padding:1px 7px; border-radius:999px; white-space:nowrap; }
.match { background:var(--ok-bg); color:var(--ok); } .call { background:var(--warn-bg); color:var(--warn); }
.clean { color:var(--ok); } .accident { color:var(--bad); } .small { font-size:12px; color:var(--muted); }
#drive { position:fixed; left:0; top:0; width:100%; height:150px; pointer-events:none; z-index:50; }
#drive canvas { position:absolute; inset:0; width:100%; height:100%; }
#drive .car { position:absolute; left:0; top:44px; width:150px; height:64px; will-change:transform; color:var(--accent); }
#drive .wheel { transform-box:fill-box; transform-origin:center; animation:spin .35s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { #drive { display:none; } }
.newchip { display:inline-block; font-size:11px; font-weight:800; letter-spacing:.06em; padding:1px 7px;
  border-radius:999px; background:var(--accent); color:var(--bg); vertical-align:2px; margin-left:6px; }
.drop { color:var(--ok); font-weight:900; margin-right:3px; }
.orig { white-space:nowrap; font-variant-numeric:tabular-nums; }
.save { color:var(--ok); font-size:12px; font-weight:600; }
.sortbar { display:flex; gap:8px; align-items:center; margin-bottom:10px; }
.sortbar label { font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
.sortbar select { flex:1; min-width:0; max-width:380px; }
.phone-only { display:none; }
/* Trim guide tab */
.gmodel { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:14px; margin-bottom:14px; scroll-margin-top:12px; }
.gmodel h2 { margin:0; font-size:20px; } .gmodel .rule { margin:2px 0 10px; }
.years { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:8px; }
.years button { font:inherit; font-size:14px; padding:4px 12px; border:1px solid var(--line); border-radius:999px; background:var(--surface); color:var(--fg); cursor:pointer; }
.years button[aria-pressed="true"] { background:var(--accent); border-color:var(--accent); color:var(--bg); }
.changed { margin:0 0 10px; }
.trims { display:grid; grid-template-columns:repeat(auto-fill, minmax(270px, 1fr)); gap:10px; }
.trim { border:1px solid var(--line); border-radius:8px; padding:10px 12px; background:var(--bg); }
.trim.off { opacity:.7; }
.trim h3 { margin:0 0 4px; font-size:16px; }
.trim dl { display:grid; grid-template-columns:auto 1fr; gap:2px 10px; margin:8px 0; font-size:13px; }
.trim dt { color:var(--muted); } .trim dd { margin:0; }
.trim ul { margin:4px 0 0; padding-left:18px; font-size:14px; } .trim li { margin:2px 0; }
.off-chip { background:var(--bad-bg); color:var(--bad); }
.gtools { display:grid; gap:8px; margin-bottom:12px; }
.src { font-size:12px; color:var(--muted); margin-top:8px; overflow-wrap:anywhere; }
.glink { font:600 12px system-ui, -apple-system, sans-serif; margin-left:6px; }
.yby { margin:0 0 10px; font-size:14px; } .yby summary { cursor:pointer; color:var(--accent); font-weight:600; }
.yby ul { margin:6px 0 0; padding-left:18px; } .yby li { margin:4px 0; }
.wcards { display:grid; grid-template-columns:repeat(auto-fill, minmax(270px, 1fr)); gap:10px; margin-top:8px; }
.wcard { border:1px solid var(--line); border-radius:8px; padding:10px 12px; background:var(--bg); font-size:14px; }
.wcard h3 { margin:0 0 4px; font-size:16px; } .wcard ul { margin:4px 0; padding-left:18px; } .wcard li { margin:2px 0; }
.wline { white-space:normal; } .wline + .wline { margin-top:3px; } .wexp { color:var(--muted); text-decoration:line-through; }
td.warr { min-width:190px; font-size:13px; }
/* Phones: each car becomes a card, so nothing needs sideways scrolling */
@media (max-width: 760px) {
  .phone-only { display:flex; } .sortbar select { max-width:none; }
  .wrap { overflow:visible; background:none; border:0; border-radius:0; }
  table, tbody { display:block; min-width:0; width:auto; }
  thead { display:none; }
  tbody tr { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:10px 12px; background:var(--surface);
    border:1px solid var(--line); border-radius:10px; padding:12px; margin-bottom:12px; }
  td { display:block; padding:0; border:0; min-width:0; overflow-wrap:anywhere; }
  td.num { text-align:left; white-space:normal; }
  td[data-l]::before { content:attr(data-l); display:block; font-size:11px; text-transform:uppercase; letter-spacing:.05em;
    color:var(--muted); margin-bottom:1px; }
  td.car { grid-column:1 / -1; order:-3; font-size:16px; } td.car::before { display:none !important; }
  td.wide { grid-column:1 / -1; } td.span2 { grid-column:span 2; }
  td.p-score { order:-2; } td.p-price { order:-2; font-size:17px; font-weight:700; } td.p-mo { order:-2; }
  td[colspan] { grid-column:1 / -1; }
  tbody tr:has(td[colspan]) { display:block; }
}
</style></head><body><main>
<div id="safe-top" aria-hidden="true"></div>
<div><h1>CPO SUV Finder</h1><div class="muted">Refreshed __DATE__ · every car links to the dealer's own listing</div></div>
<div class="tiles">
  <div class="tile"><b>__MATCHES__</b><span class="muted">meet all criteria</span></div>
  <div class="tile"><b>__CALLS__</b><span class="muted">need a call</span></div>
  <div class="tile"><b>__OK__</b><span class="muted">sources read</span></div>
  <div class="tile"><b>__FAILED__</b><span class="muted">sources failed</span></div>
  <div class="tile"><b>__SKIPPED__</b><span class="muted">covered by brand feeds</span></div>
</div>
<details id="cov"><summary><b>Coverage:</b> <span id="covsum"></span></summary><ul id="covlist"></ul></details>
<div class="tabs" role="tablist">
  <button class="tab" role="tab" id="tab-avail" aria-selected="true" aria-controls="panel-avail">Available<span class="n">__NAVAIL__</span></button>
  <button class="tab" role="tab" id="tab-gone" aria-selected="false" aria-controls="panel-gone">No longer available<span class="n">__NGONE__</span></button>
  <button class="tab" role="tab" id="tab-guide" aria-selected="false" aria-controls="panel-guide">Trim guide</button>
</div>
<div class="filters">
  <div class="controls"><input id="q" placeholder="Search: dealer, model, color…" aria-label="Search">
    <button class="clear" id="clear" type="button">Clear filters</button></div>
  <fieldset class="group" id="f-show"><legend>Status</legend></fieldset>
  <fieldset class="group" id="f-make"><legend>Make</legend></fieldset>
  <fieldset class="group" id="f-fuel"><legend>Fuel</legend></fieldset>
  <div class="small">Tap to select several; nothing selected in a row means all.</div>
</div>
<div id="panel-avail" role="tabpanel" aria-labelledby="tab-avail">
<div class="sortbar phone-only"><label for="sort-a">Sort</label><select id="sort-a">
  <option value="score:-1">Best score</option><option value="price_total:1">Lowest price</option>
  <option value="est_monthly_cost:1">Lowest monthly</option><option value="mileage:1">Fewest miles</option>
  <option value="distance_mi:1">Closest dealer</option><option value="first_seen:-1">Newest listing</option>
  <option value="year:-1">Newest model year</option><option value="mpg_combined:-1">Best MPG</option><option value="warr_left:-1">Longest warranty</option></select></div>
<div class="wrap"><table><thead><tr>
  <th data-k="score">Score</th><th data-k="title">Car</th><th data-k="dealer">Dealer</th><th data-k="price_total">Price</th>
  <th data-k="orig">Original price</th><th data-k="mileage">Miles</th><th data-k="fuel">Fuel</th><th data-k="mpg_combined">MPG</th><th data-k="colors">Colors</th><th data-k="feat">Features</th>
  <th data-k="carfax_status">CARFAX</th><th data-k="est_monthly_cost">Est./mo</th><th data-k="warr_left">Warranty</th><th data-k="first_seen">First seen</th>
</tr></thead><tbody id="rows"></tbody></table></div>
</div>
<div id="panel-gone" role="tabpanel" aria-labelledby="tab-gone" hidden>
<div class="sortbar phone-only"><label for="sort-g">Sort</label><select id="sort-g">
  <option value="removed_on:-1">Gone most recently</option><option value="price_total:1">Lowest price</option>
  <option value="days:1">Fewest days listed</option><option value="mileage:1">Fewest miles</option></select></div>
<div class="wrap"><table class="gone"><thead><tr>
  <th data-g="title">Car</th><th data-g="dealer">Dealer</th><th data-g="price_total">Last price</th><th data-g="orig">Original price</th>
  <th data-g="mileage">Miles</th><th data-g="fuel">Fuel</th><th data-g="colors">Colors</th><th data-g="first_seen">First seen</th>
  <th data-g="removed_on">Gone since</th><th data-g="days">Days listed</th><th data-g="fail_reasons">Why</th>
</tr></thead><tbody id="gone-rows"></tbody></table></div>
<p class="small">Cars that were on this dashboard and later disappeared from the dealer's site (sold or taken down). The link may no longer work.</p>
</div>
<div id="panel-guide" role="tabpanel" aria-labelledby="tab-guide" hidden>
<p class="muted" style="margin-top:0">What each trim includes, by model year, for every model your search looks for.
Trims marked <span class="chip off-chip">not on your list</span> are shown so you can compare. Researched from the
manufacturers' own press sites and brochures; dealers can add options, so check the window sticker.</p>
<div class="gtools">
  <div class="sortbar"><label for="g-jump">Jump to</label><select id="g-jump"><option value="">Choose a model…</option></select></div>
  <fieldset class="group" id="g-make"><legend>Make</legend></fieldset>
  <label class="pill"><input type="checkbox" id="g-only"><span>Only trims on my list</span></label>
</div>
<details class="gmodel" id="g-warranty" open><summary><b>Warranties by brand</b> <span class="small">(new-car and certified pre-owned)</span></summary>
<p class="small">Each car on the Available tab also shows an estimate of the coverage it has left. The years count from the date the car was first sold new (its "in-service date"), which listings don't show, so the dates are a range: ask the dealer for the exact date.</p>
<div class="wcards" id="wcards"></div></details>
<div id="guide"></div>
</div>
<p class="small" id="footnote">Price = advertised price + dealer fees (estimated when the page didn't list them), before tax. Monthly = $8,000 down, 60 months at 5.34%, 9.75% tax, $400 gov't fees. MPG = combined (city/hwy below); "EPA" means the listing didn't show it, so it's the official rating from fueleconomy.gov; plug-in hybrids show gas-only MPG.</p>
</main>
<script>
const D = __DATA__;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const num = v => { const n = parseFloat(v); return isNaN(n) ? null : n; };
const FUEL = {gas: "Gas", hybrid: "Hybrid", phev: "Plug-in hybrid", ev: "Electric"};
const fmt$ = v => num(v) == null ? "?" : "$" + Math.round(num(v)).toLocaleString();
D.cars.concat(D.gone).forEach(c => { c.title = [c.year, c.make, c.model, c.trim].filter(Boolean).join(" ");
  c.colors = [c.ext_color, c.int_color].filter(Boolean).join(" / ");
  c.feat = [c.sunroof === "True" ? "sunroof" : "", c.audio].filter(Boolean).join(", ");
  c.fuel = FUEL[c.fuel_type] || "?"; });
D.cars.concat(D.gone).forEach(c => {
  c.orig = c.hist && c.hist.length ? c.hist[0][1] : num(c.price_total);
  const now = num(c.price_total);
  c.dropped = c.orig != null && now != null && now < c.orig - 1;
  c.histTip = (c.hist || []).map(x => x[0] + ": " + fmt$(x[1])).join("\n"); });
D.gone.forEach(c => { const a = Date.parse(c.first_seen), b = Date.parse(c.last_seen);
  c.days = isNaN(a) || isNaN(b) ? "" : Math.round((b - a) / 864e5) + 1; });
const makes = [...new Set(D.cars.concat(D.gone).map(c => c.make))].sort();
const pills = (id, vals) => document.getElementById(id).insertAdjacentHTML("beforeend",
  vals.map(v => `<label class="pill"><input type="checkbox" value="${esc(v)}"><span>${esc(v)}</span></label>`).join(""));
pills("f-show", ["Meets all criteria", "Needs a call"]);
pills("f-make", makes);
pills("f-fuel", ["Gas", "Hybrid", "Plug-in hybrid", "Electric"].filter(f => D.cars.concat(D.gone).some(c => c.fuel === f)));
const picked = id => new Set([...document.querySelectorAll(`#${id} input:checked`)].map(i => i.value));
document.getElementById("covsum").textContent = D.failed.length ? `${D.failed.length} sources failed (tap to see why)` : "all sources read";
document.getElementById("covlist").innerHTML = D.failed.map(f => `<li><b>${esc(f.brand)} · ${esc(f.dealer)}</b>: ${esc(f.reason)}</li>`).join("") || "<li>Nothing failed.</li>";
function priceCell(c) {
  return c.dropped
    ? `<span class="drop" title="Price dropped from ${fmt$(c.orig)}" aria-label="price dropped">&#9660;</span>${fmt$(c.price_total)}`
    : fmt$(c.price_total);
}
function origCell(c) {
  if (c.orig == null) return "?";
  const save = c.dropped ? `<div class="save">${fmt$(c.orig - num(c.price_total))} less now</div>` : "";
  return `<span class="orig" title="${esc(c.histTip)}">${fmt$(c.orig)}</span>${save}`;
}
// ---- Warranty: what coverage a car has left (estimated) ----
const W = {}; ((D.warranty && D.warranty.brands) || []).forEach(b => W[b.make.toLowerCase()] = b);
const NOW = new Date(), THIS_YEAR = NOW.getFullYear();
const kmi = n => n == null ? "unlimited miles" : (n >= 1000 ? Math.round(n / 1000) + "k" : n) + " mi";
const yrs = (a, b) => a === b ? String(a) : a + "–" + String(b).slice(-2);
// A model-year car is usually first sold between mid-(year-1) and the end of its model year.
function coverLine(cov, c, label, baseEnd) {
  const my = parseInt(c.year), mi = num(c.mileage);
  if (cov.years == null && cov.miles == null) return "";
  let lo, hi, when;
  if (/purchase/i.test(cov.starts || "")) { lo = hi = THIS_YEAR + (cov.years || 0); when = "if bought now"; }
  else if (/end of new/i.test(cov.starts || "") && baseEnd) { lo = baseEnd[0] + (cov.years || 0); hi = baseEnd[1] + (cov.years || 0); }
  else if (my) { lo = my - 1 + (cov.years || 0); hi = my + (cov.years || 0); }
  const milesLeft = cov.miles == null || mi == null ? null : cov.miles - mi;
  const expired = (milesLeft != null && milesLeft <= 0) || (hi != null && hi < THIS_YEAR);
  const until = lo != null ? `to ~${yrs(lo, hi)}${when ? " " + when : ""}` : "";
  const text = `<b>${esc(label)}:</b> ${cov.years ? cov.years + " yr / " : ""}${kmi(cov.miles)}`;
  if (expired) return {html: `<div class="wline wexp">${text}</div>`, left: 0};
  const left = milesLeft == null ? "" : ` (${kmi(milesLeft)} left)`;
  return {html: `<div class="wline">${text} · ${until}${left}</div>`, left: hi || 0};
}
function warrantyFor(c) {
  const b = W[String(c.make).toLowerCase()];
  if (!b) return {html: '<span class="muted">?</span>', left: 0};
  const my = parseInt(c.year), lines = [];
  const pick = re => (b.factory || []).find(f => re.test(f.name));
  const basic = pick(/basic|bumper|limited warranty|new vehicle/i), pt = pick(/powertrain/i);
  const hy = /hybrid|phev|ev/.test(c.fuel_type || "") ? pick(/hybrid|battery|electric|high.?voltage/i) : null;
  const baseEnd = basic && my ? [my - 1 + basic.years, my + basic.years] : null;
  ((b.cpo && b.cpo.coverage) || []).forEach(cv => lines.push(coverLine(cv, c, "CPO " + cv.name.toLowerCase(), baseEnd)));
  const cpo = (b.cpo && b.cpo.coverage) || [];
  const outdone = f => cpo.some(cv => /powertrain/i.test(cv.name) === /powertrain/i.test(f.name) && /in-service/i.test(cv.starts || "")
    && (cv.years || 0) >= (f.years || 0) && (cv.miles == null || (f.miles != null && cv.miles >= f.miles)));   // CPO already covers it for longer
  [[basic, "Factory basic"], [pt, "Factory powertrain"], [hy, "Hybrid battery"]].forEach(([f, l]) => {
    if (f && !/^no/i.test(f.transfers || "") && !(f !== hy && outdone(f))) lines.push(coverLine(f, c, l, null)); });
  const ok = lines.filter(Boolean);
  return {html: ok.map(l => l.html).join("") || '<span class="muted">?</span>', left: Math.max(0, ...ok.map(l => l.left))};
}
D.cars.forEach(c => { const w = warrantyFor(c); c.warr_html = w.html; c.warr_left = w.left; });
function renderWarranty() {
  const brands = (D.warranty && D.warranty.brands) || [];
  document.getElementById("g-warranty").hidden = !brands.length;
  const line = f => `<li><b>${esc(f.name)}:</b> ${f.years ? f.years + " yr / " : ""}${kmi(f.miles)}${f.starts ? ", from " + esc(f.starts) : ""}${f.transfers && !/^yes/i.test(f.transfers) ? " (" + esc(f.transfers === "no" ? "first owner only" : f.transfers) + ")" : ""}${f.note ? " · " + esc(f.note) : ""}</li>`;
  document.getElementById("wcards").innerHTML = brands.map(b => `<div class="wcard"><h3>${esc(b.make)}</h3>
    ${b.cpo ? `<div><b>${esc(b.cpo.program)}</b></div><div class="small">${esc(b.cpo.summary || "")}</div><ul>${(b.cpo.coverage || []).map(line).join("")}</ul>
      ${(b.cpo.perks || []).length ? `<div class="small">Also: ${b.cpo.perks.map(esc).join("; ")}</div>` : ""}` : ""}
    <div style="margin-top:6px"><b>New-car warranty</b></div><ul>${(b.factory || []).map(line).join("")}</ul>
    ${b.factory_note ? `<div class="small">${esc(b.factory_note)}</div>` : ""}
    ${b.maintenance ? `<div class="small">Maintenance: ${esc(b.maintenance)}</div>` : ""}
    ${(b.sources || []).length ? `<div class="src">Sources: ${b.sources.map(u => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u.replace(/^https?:\/\/(www\.)?/, "").split("/")[0])}</a>`).join(", ")}</div>` : ""}
  </div>`).join("");
}
// ---- Trim guide tab ----
const G = (D.guide && D.guide.models) || [];
const slug = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-");
const gYear = {};   // chosen year per model
G.forEach(m => { m.id = "g-" + slug(m.make + " " + m.model);
  const ys = (m.years || []).map(y => y.year); gYear[m.id] = ys.includes(new Date().getFullYear() - 1) ? new Date().getFullYear() - 1 : ys[ys.length - 1]; });
pills("g-make", [...new Set(G.map(m => m.make))]);
document.getElementById("g-jump").insertAdjacentHTML("beforeend", G.map(m => `<option value="${m.id}">${esc(m.make)} ${esc(m.model)}</option>`).join(""));
document.getElementById("g-jump").addEventListener("change", e => {
  const id = e.target.value; if (!id) return;
  document.querySelectorAll("#g-make input").forEach(i => i.checked = false); renderGuide();
  const el = document.getElementById(id); if (el) el.scrollIntoView({block: "start"}); e.target.value = ""; });
function guideFor(c) {      // the guide entry for a listed car: same make, longest model name contained in the car's model
  const mk = String(c.make).toLowerCase(), md = " " + String(c.model + " " + c.trim).toLowerCase().replace(/-/g, " ") + " ";
  return G.filter(m => m.make.toLowerCase() === mk && md.includes(String(m.model).toLowerCase().replace(/-/g, " ")))
          .sort((a, b) => b.model.length - a.model.length)[0];
}
function guideLink(c) {
  const m = guideFor(c);
  return m ? ` <a class="glink" href="#${m.id}" data-gid="${m.id}" data-year="${esc(c.year)}">trim info</a>` : "";
}
const row = (k, v) => v && v !== "unknown" ? `<dt>${k}</dt><dd>${esc(v)}</dd>` : "";
function trimCard(t) {
  return `<div class="trim${t.on_list ? "" : " off"}"><h3>${esc(t.name)}</h3>
    ${t.on_list ? '<span class="chip match">on your list</span>' : `<span class="chip off-chip">not on your list</span> <span class="small">${esc(t.why_not)}</span>`}
    <dl>${row("Engine", t.powertrain)}${row("Sunroof", t.sunroof)}${row("Audio", t.premium_audio)}${row("Seats", t.seats)}
      ${row("Black interior", t.black_interior)}${row("Spare", t.spare)}${row("MPG", t.mpg ? t.mpg + " (city/hwy/comb.)" : "")}</dl>
    ${(t.highlights || []).length ? `<div class="small">${t.builds_on ? "Adds over " + esc(t.builds_on) + ":" : "Comes with:"}</div>
      <ul>${t.highlights.map(h => `<li>${esc(h)}</li>`).join("")}</ul>` : ""}</div>`;
}
function renderGuide() {
  const mk = picked("g-make"), only = document.getElementById("g-only").checked;
  const html = G.filter(m => !mk.size || mk.has(m.make)).map(m => {
    const y = (m.years || []).find(y => y.year === gYear[m.id]) || (m.years || [])[0] || {trims: []};
    const trims = (y.trims || []).filter(t => !only || t.on_list);
    return `<section class="gmodel" id="${m.id}"><h2>${esc(m.make)} ${esc(m.model)}</h2>
      <div class="small rule">${esc(m.on_list_rule)}</div>
      <div class="years" role="group" aria-label="Model year">${(m.years || []).map(v =>
        `<button type="button" data-m="${m.id}" data-y="${v.year}" aria-pressed="${v.year === y.year}">${v.year}</button>`).join("")}</div>
      ${y.what_changed ? `<p class="small changed"><b>${y.year}:</b> ${esc(y.what_changed)}</p>` : ""}
      ${(m.years || []).length > 1 ? `<details class="yby"><summary>How the years differ</summary><ul>${m.years.map(v =>
        `<li><b>${v.year}:</b> ${esc(v.what_changed || "")}</li>`).join("")}</ul></details>` : ""}
      <div class="trims">${trims.map(trimCard).join("") || '<div class="muted">No trims on your list this year.</div>'}</div>
      ${(m.sources || []).length ? `<div class="src">Sources: ${m.sources.map(u => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u.replace(/^https?:\/\/(www\.)?/, "").split("/")[0])}</a>`).join(", ")}</div>` : ""}
    </section>`; }).join("");
  document.getElementById("guide").innerHTML = html || '<p class="muted">The trim guide is empty.</p>';
}
document.getElementById("guide").addEventListener("click", e => {
  const b = e.target.closest("button[data-y]"); if (!b) return;
  gYear[b.dataset.m] = +b.dataset.y; renderGuide();
  const btn = document.querySelector(`button[data-m="${b.dataset.m}"][data-y="${b.dataset.y}"]`); if (btn) btn.focus(); });
["g-make", "g-only"].forEach(id => document.getElementById(id).addEventListener("input", renderGuide));
document.addEventListener("click", e => {      // "trim info" link on a car: open its model + year in the guide
  const a = e.target.closest("a[data-gid]"); if (!a) return;
  e.preventDefault();
  const m = G.find(x => x.id === a.dataset.gid), yr = +a.dataset.year;
  if (m && m.years.some(y => y.year === yr)) gYear[m.id] = yr;
  document.querySelectorAll("#g-make input").forEach(i => i.checked = false);
  showTab("guide"); renderGuide();
  const el = document.getElementById(a.dataset.gid); if (el) el.scrollIntoView({block: "start"}); });
let sortK = "score", dir = -1, gK = "removed_on", gDir = -1;
const sorter = (k, d) => (a, b) => { let x = a[k], y = b[k];
  const ex = x == null || x === "", ey = y == null || y === ""; if (ex || ey) return ex - ey;   // blanks last
  const nx = num(x), ny = num(y); if (nx != null && ny != null && !/_(seen|on)$/.test(k)) return (nx - ny) * d;
  return String(x ?? "").localeCompare(String(y ?? "")) * d; };
function render() { renderRows(); stickHeads(); }
function renderRows() {
  const q = document.getElementById("q").value.toLowerCase(), show = picked("f-show"), mk = picked("f-make"), fu = picked("f-fuel");
  const base = c => (!q || JSON.stringify(c).toLowerCase().includes(q)) && (!mk.size || mk.has(c.make)) && (!fu.size || fu.has(c.fuel));
  const wasStatus = c => c.needs_call ? "Needs a call" : "Meets all criteria";
  let cars = D.cars.filter(c => base(c) && (!show.size || show.has(wasStatus(c))));
  cars.sort(sorter(sortK, dir));
  const gone = D.gone.filter(c => base(c) && (!show.size || show.has(wasStatus(c)))).sort(sorter(gK, gDir));
  document.getElementById("gone-rows").innerHTML = gone.map(c => `<tr>
    <td class="car"><a href="${esc(c.listing_url)}" target="_blank" rel="noopener">${esc(c.title)}</a><div class="vin">${esc(c.vin)}</div>
      <div class="small">was ${c.needs_call ? "needs a call" : "a match"}</div></td>
    <td class="span2" data-l="Dealer">${esc(c.dealer)}<div class="small">${esc(c.distance_mi)} mi</div></td>
    <td class="num p-price" data-l="Last price">${priceCell(c)}</td><td class="num" data-l="Original price">${origCell(c)}</td>
    <td class="num" data-l="Miles">${num(c.mileage) == null ? "?" : Math.round(num(c.mileage)).toLocaleString()}</td>
    <td data-l="Fuel">${esc(c.fuel)}</td><td class="wide" data-l="Colors">${esc(c.colors)}</td><td class="small" data-l="First seen">${esc(c.first_seen)}</td>
    <td class="small" data-l="Gone since">${esc(c.removed_on || c.last_seen)}</td><td class="num" data-l="Days listed">${esc(c.days)}</td>
    <td class="small wide" data-l="Why">${esc(c.fail_reasons)}</td></tr>`).join("")
    || `<tr><td colspan="11" class="muted">${D.gone.length ? "No cars match these filters." : "Nothing yet. Cars that leave the dashboard because they sold or were taken down will show up here."}</td></tr>`;
  document.getElementById("rows").innerHTML = cars.map(c => `<tr>
    <td class="num p-score" data-l="Score">${esc(c.score)}<br>${c.needs_call ? '<span class="chip call">needs a call</span>' : '<span class="chip match">match</span>'}</td>
    <td class="car"><a href="${esc(c.listing_url)}" target="_blank" rel="noopener">${esc(c.title)}</a>${c.is_new ? '<span class="newchip" title="New since the last refresh">NEW</span>' : ""}<div class="vin">${esc(c.vin)}${guideLink(c)}</div>
      ${c.needs_call ? `<div class="small">Ask about: ${esc(c.needs_call)}</div>` : ""}${c.notes ? `<div class="small">${esc(c.notes)}</div>` : ""}</td>
    <td class="span2" data-l="Dealer">${esc(c.dealer)}<div class="small">${esc(c.distance_mi)} mi</div></td>
    <td class="num p-price" data-l="Price">${priceCell(c)}${c.fees_estimated === "True" ? '<div class="small">fees est.</div>' : ""}</td>
    <td class="num" data-l="Original price">${origCell(c)}</td><td class="num" data-l="Miles">${num(c.mileage) == null ? "?" : Math.round(num(c.mileage)).toLocaleString()}</td>
    <td data-l="Fuel">${esc(c.fuel)}</td>
    <td class="num" data-l="MPG">${num(c.mpg_combined) == null ? "?" : Math.round(num(c.mpg_combined))}<div class="small">${num(c.mpg_city) != null ? Math.round(num(c.mpg_city)) + "/" + Math.round(num(c.mpg_hwy)) : ""}${c.fuel_type === "phev" ? " gas" : ""}${c.mpg_source === "EPA" ? " EPA" : ""}</div></td>
    <td class="wide" data-l="Colors">${esc(c.colors)}</td><td class="span2" data-l="Features">${esc(c.feat)}<div class="small">${esc(c.cpo_program)}</div></td>
    <td class="${esc(c.carfax_status)}" data-l="CARFAX">${esc({clean:"no accidents", accident:"accident", not_verified:"not verified"}[c.carfax_status] || c.carfax_status)}</td>
    <td class="num p-mo" data-l="Est./mo">${fmt$(c.est_monthly_cost)}</td><td class="warr wide" data-l="Warranty (estimated)">${c.warr_html}</td><td class="small wide" data-l="First seen">${esc(c.first_seen)}</td></tr>`).join("")
    || '<tr><td colspan="14" class="muted">No cars match these filters.</td></tr>';
}
document.querySelectorAll("th[data-k]").forEach(th => th.addEventListener("click", () => {
  const k = th.dataset.k; dir = sortK === k ? -dir : (k === "score" ? -1 : 1); sortK = k; render(); }));
document.querySelectorAll("th[data-g]").forEach(th => th.addEventListener("click", () => {
  const k = th.dataset.g; gDir = gK === k ? -gDir : (/_(seen|on)$/.test(k) ? -1 : 1); gK = k; render(); }));
// Keep each table's header row visible at the top of the screen while its rows scroll past.
// (CSS position:sticky can't do this here: the table sits in a sideways-scrolling box for phones.)
const safeTop = () => { const el = document.getElementById("safe-top"); return el ? el.getBoundingClientRect().height : 0; };
function stickHeads() {
  const top = safeTop();
  document.querySelectorAll(".wrap").forEach(w => {
    const head = w.querySelector("thead");
    if (!head || w.offsetParent === null || head.offsetParent === null) return;   // hidden tab, or phone card view
    const r = w.getBoundingClientRect(), h = head.getBoundingClientRect().height;
    const off = Math.max(0, Math.min(top - r.top, r.height - h * 2));
    head.classList.toggle("stuck", off > 0);
    head.querySelectorAll("th").forEach(th => { th.style.transform = off > 0 ? `translateY(${off}px)` : ""; });
  });
}
window.addEventListener("scroll", stickHeads, {passive: true});
window.addEventListener("resize", stickHeads);
function showTab(which) {
  ["avail", "gone", "guide"].forEach(t => {
    document.getElementById("tab-" + t).setAttribute("aria-selected", String(t === which));
    document.getElementById("panel-" + t).hidden = t !== which; });
  document.querySelector(".filters").hidden = which === "guide";      // car filters don't apply to the guide
  document.getElementById("footnote").hidden = which === "guide";
  try { localStorage.setItem("tab", which); } catch (e) {}
  stickHeads();
}
document.getElementById("tab-avail").addEventListener("click", () => showTab("avail"));
document.getElementById("tab-gone").addEventListener("click", () => showTab("gone"));
document.getElementById("tab-guide").addEventListener("click", () => showTab("guide"));
renderGuide(); renderWarranty();
try { const t = location.hash.slice(1) || localStorage.getItem("tab"); if (t === "gone" || t === "guide") showTab(t); } catch (e) {}
// Phone card view has no column headers to tap, so it sorts with a menu instead.
document.getElementById("sort-a").addEventListener("change", e => { const [k, d] = e.target.value.split(":"); sortK = k; dir = +d; render(); });
document.getElementById("sort-g").addEventListener("change", e => { const [k, d] = e.target.value.split(":"); gK = k; gDir = +d; render(); });
["q", "f-show", "f-make", "f-fuel"].forEach(id => document.getElementById(id).addEventListener("input", render));
document.getElementById("clear").addEventListener("click", () => {
  document.querySelectorAll(".filters input[type=checkbox]").forEach(i => i.checked = false);
  document.getElementById("q").value = ""; render(); });
render();
stickHeads();

// Welcome animation: an SUV drives across the top once, laying tire marks that fade away.
(function drive() {
  try {
    if (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const wrap = document.createElement("div"); wrap.id = "drive"; wrap.setAttribute("aria-hidden", "true");
    // compact luxury SUV in side view, facing right (direction of travel): short hood, raked windshield,
    // roofline sloping to an angled tailgate, roof rails, dark lower cladding, big wheels
    wrap.innerHTML = `<canvas></canvas><svg class="car" viewBox="0 0 150 64">
      <rect x="31" y="8.6" width="44" height="2" rx="1" fill="var(--fg)" opacity=".55"/>
      <path fill="currentColor" d="M8 50 L7 38 Q7 30 12 26 L18 20 Q24 14 34 13 L76 12 Q84 12 90 16 L104 25 L132 28 Q142 30 144 35 L145 45 Q145 50 141 50 L130 50 A14 14 0 0 0 102 50 L48 50 A14 14 0 0 0 20 50 Z"/>
      <path fill="var(--fg)" opacity=".28" d="M8 44 L20 44 A14 14 0 0 1 48 44 L102 44 A14 14 0 0 1 130 44 L145 44 L145 46 Q145 50 141 50 L130 50 A14 14 0 0 0 102 50 L48 50 A14 14 0 0 0 20 50 L8 50 Z"/>
      <path fill="var(--bg)" opacity=".85" d="M21 25 Q25 17 33 16 L44 16 L44 25 Z M48 16 L72 16 L72 25 L48 25 Z M76 16 Q83 16 88 19 L97 25 L76 25 Z"/>
      <path d="M46 16 L46 25 M74 16 L74 25" stroke="currentColor" stroke-width="2"/>
      <rect x="135" y="30" width="9" height="3" rx="1.5" fill="#f6d36b"/>
      <rect x="7" y="29" width="5" height="4" rx="1.5" fill="#d9534f"/>
      <g class="wheel"><circle cx="34" cy="50" r="11" fill="var(--fg)"/><circle cx="34" cy="50" r="7" fill="var(--muted)"/><circle cx="34" cy="50" r="2.5" fill="var(--fg)"/><rect x="33" y="43" width="2" height="14" fill="var(--fg)"/><rect x="27" y="49" width="14" height="2" fill="var(--fg)"/></g>
      <g class="wheel"><circle cx="116" cy="50" r="11" fill="var(--fg)"/><circle cx="116" cy="50" r="7" fill="var(--muted)"/><circle cx="116" cy="50" r="2.5" fill="var(--fg)"/><rect x="115" y="43" width="2" height="14" fill="var(--fg)"/><rect x="109" y="49" width="14" height="2" fill="var(--fg)"/></g>
    </svg>`;
    document.body.appendChild(wrap);
    const cv = wrap.querySelector("canvas"), car = wrap.querySelector(".car"), ctx = cv.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const size = () => { cv.width = innerWidth * dpr; cv.height = 150 * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); };
    size();
    const mark = getComputedStyle(document.documentElement).getPropertyValue("--fg").trim() || "#222";
    const W = innerWidth, start = -170, end = W + 20, dur = Math.max(2200, W * 1.6), fade = 1800;
    const groundY = 44 + 61;                       // where the tires meet the "road"
    let t0 = null, lastX = null;
    function frame(t) {
      if (t0 === null) t0 = t;
      const el = t - t0, p = Math.min(1, el / dur);
      const ease = p < .5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
      const x = start + (end - start) * ease;
      const bob = Math.sin(el / 70) * 0.8;
      car.style.transform = `translate(${x}px, ${bob}px)`;
      // fade old marks a little every frame
      ctx.globalCompositeOperation = "destination-out";
      ctx.fillStyle = "rgba(0,0,0,0.035)";
      ctx.fillRect(0, 0, W, 150);
      ctx.globalCompositeOperation = "source-over";
      if (p < 1 && lastX !== null) {
        ctx.strokeStyle = mark; ctx.globalAlpha = 0.45; ctx.lineCap = "round";
        for (const [wx, off, lw] of [[34, 0, 3.5], [116, 0, 3.5], [34, 4, 1.5], [116, 4, 1.5]]) {
          ctx.lineWidth = lw; ctx.beginPath();
          ctx.moveTo(lastX + wx, groundY + off); ctx.lineTo(x + wx, groundY + off); ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }
      lastX = x;
      if (el < dur + fade) requestAnimationFrame(frame); else wrap.remove();
    }
    requestAnimationFrame(frame);
  } catch (e) { document.getElementById("drive")?.remove(); }
})();
</script></body></html>
"""
