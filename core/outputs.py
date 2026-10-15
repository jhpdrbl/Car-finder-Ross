"""Digest (markdown for Apple Notes), coverage report, and the static HTML dashboard."""
from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

from scrapers.base import CONFIG

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"


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
    if r.get("fuel_type") in ("hybrid", "phev", "ev"):
        bits.append({"hybrid": "hybrid", "phev": "plug-in hybrid", "ev": "EV"}[r["fuel_type"]])
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
                     "reason": r.reason, "listings": r.parsed, "distance_mi": r.dealer["distance_mi"],
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
    cars = []
    for r in active:
        cars.append({k: r.get(k, "") for k in ("vin", "dealer", "listing_url", "year", "make", "model", "trim", "price_total",
                                               "mileage", "ext_color", "int_color", "fuel_type", "sunroof", "audio",
                                               "carfax_status", "est_monthly_cost", "score", "needs_call", "notes",
                                               "mpg_combined", "mpg_city", "mpg_hwy", "mpg_source",
                                               "cpo_program", "first_seen", "distance_mi", "fees_estimated")}
                    | {"hist": hist.get(r["vin"], [])})
    ok = sum(c["status"] == "success" for c in cov)
    failed = [c for c in cov if c["status"] == "failed"]
    skipped = sum(c["status"] == "skipped" for c in cov)
    data = json.dumps({"cars": cars, "failed": failed}, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", data).replace("__DATE__", html.escape(today)) \
        .replace("__OK__", str(ok)).replace("__FAILED__", str(len(failed))).replace("__SKIPPED__", str(skipped)) \
        .replace("__MATCHES__", str(sum(1 for c in cars if not c["needs_call"]))) \
        .replace("__CALLS__", str(sum(1 for c in cars if c["needs_call"])))
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
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; padding-block:20px; padding-left:max(16px, env(safe-area-inset-left, 0px)); padding-right:max(16px, env(safe-area-inset-right, 0px)); }
main { max-width:1200px; margin:0 auto; display:grid; gap:18px; }
h1 { margin:0; font-size:26px; letter-spacing:-.01em; } .muted { color:var(--muted); }
.tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(140px,1fr)); gap:10px; }
.tile { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
.tile b { display:block; font-size:24px; font-variant-numeric:tabular-nums; }
details { background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
details li { margin:3px 0; }
.controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
input, select { font:inherit; padding:6px 8px; border:1px solid var(--line); border-radius:6px; background:var(--surface); color:var(--fg); }
.wrap { overflow-x:auto; background:var(--surface); border:1px solid var(--line); border-radius:8px; }
table { border-collapse:collapse; width:100%; min-width:900px; }
th { text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); padding:9px 10px;
  border-bottom:1px solid var(--line); cursor:pointer; white-space:nowrap; user-select:none; }
th:hover { color:var(--fg); } td { padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
td.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
a { color:var(--accent); } .car a { font-weight:600; color:var(--fg); text-decoration:none; } .car a:hover { color:var(--accent); text-decoration:underline; }
.vin { font:12px ui-monospace, Menlo, Consolas, monospace; color:var(--muted); }
.chip { display:inline-block; font-size:12px; font-weight:600; padding:1px 7px; border-radius:999px; white-space:nowrap; }
.match { background:var(--ok-bg); color:var(--ok); } .call { background:var(--warn-bg); color:var(--warn); }
.clean { color:var(--ok); } .accident { color:var(--bad); } .small { font-size:12px; color:var(--muted); }
svg.spark { display:block; } svg.spark path { fill:none; stroke:var(--accent); stroke-width:1.6; } svg.spark circle { fill:var(--accent); }
</style></head><body><main>
<div><h1>CPO SUV Finder</h1><div class="muted">Refreshed __DATE__ · every car links to the dealer's own listing</div></div>
<div class="tiles">
  <div class="tile"><b>__MATCHES__</b><span class="muted">meet all criteria</span></div>
  <div class="tile"><b>__CALLS__</b><span class="muted">need a call</span></div>
  <div class="tile"><b>__OK__</b><span class="muted">sources read</span></div>
  <div class="tile"><b>__FAILED__</b><span class="muted">sources failed</span></div>
  <div class="tile"><b>__SKIPPED__</b><span class="muted">covered by brand feeds</span></div>
</div>
<details id="cov"><summary><b>Coverage:</b> <span id="covsum"></span></summary><ul id="covlist"></ul></details>
<div class="controls">
  <input id="q" placeholder="Filter: dealer, model, color…" aria-label="Filter">
  <select id="show" aria-label="Show"><option value="all">All</option><option value="match">Meets all criteria</option><option value="call">Needs a call</option></select>
  <select id="make" aria-label="Make"><option value="">All makes</option></select>
</div>
<div class="wrap"><table><thead><tr>
  <th data-k="score">Score</th><th data-k="title">Car</th><th data-k="dealer">Dealer</th><th data-k="price_total">Price</th>
  <th data-k="hist">Price history</th><th data-k="mileage">Miles</th><th data-k="mpg_combined">MPG</th><th data-k="colors">Colors</th><th data-k="feat">Features</th>
  <th data-k="carfax_status">CARFAX</th><th data-k="est_monthly_cost">Est./mo</th><th data-k="first_seen">First seen</th>
</tr></thead><tbody id="rows"></tbody></table></div>
<p class="small">Price = advertised price + dealer fees (estimated when the page didn't list them), before tax. Monthly = $8,000 down, 60 months at 5.34%, 9.75% tax, $400 gov't fees. MPG = combined (city/hwy below); "EPA" means the listing didn't show it, so it's the official rating from fueleconomy.gov; plug-in hybrids show gas-only MPG.</p>
</main>
<script>
const D = __DATA__;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const num = v => { const n = parseFloat(v); return isNaN(n) ? null : n; };
const fmt$ = v => num(v) == null ? "?" : "$" + Math.round(num(v)).toLocaleString();
D.cars.forEach(c => { c.title = [c.year, c.make, c.model, c.trim].filter(Boolean).join(" ");
  c.colors = [c.ext_color, c.int_color].filter(Boolean).join(" / ");
  c.feat = [c.sunroof === "True" ? "sunroof" : "", c.audio, {hybrid:"hybrid", phev:"plug-in hybrid", ev:"EV"}[c.fuel_type] || ""].filter(Boolean).join(", "); });
const makes = [...new Set(D.cars.map(c => c.make))].sort();
makes.forEach(m => document.getElementById("make").insertAdjacentHTML("beforeend", `<option>${esc(m)}</option>`));
document.getElementById("covsum").textContent = D.failed.length ? `${D.failed.length} sources failed (tap to see why)` : "all sources read";
document.getElementById("covlist").innerHTML = D.failed.map(f => `<li><b>${esc(f.brand)} · ${esc(f.dealer)}</b>: ${esc(f.reason)}</li>`).join("") || "<li>Nothing failed.</li>";
function spark(h) {
  if (!h || h.length < 2) return h && h.length ? `<span class="small">${fmt$(h[0][1])}</span>` : "";
  const w = 90, ht = 24, ps = h.map(x => x[1]), lo = Math.min(...ps), hi = Math.max(...ps), sp = hi - lo || 1;
  const pts = ps.map((p, i) => [i * (w - 4) / (ps.length - 1) + 2, ht - 3 - (p - lo) / sp * (ht - 6)]);
  const last = pts[pts.length - 1];
  return `<svg class="spark" width="${w}" height="${ht}" role="img" aria-label="price history"><title>${h.map(x => x[0] + ": " + fmt$(x[1])).join("\n")}</title><path d="M${pts.map(p => p.join(",")).join(" L")}"/><circle cx="${last[0]}" cy="${last[1]}" r="2.5"/></svg>`;
}
let sortK = "score", dir = -1;
function render() {
  const q = document.getElementById("q").value.toLowerCase(), show = document.getElementById("show").value, mk = document.getElementById("make").value;
  let cars = D.cars.filter(c => (!q || JSON.stringify(c).toLowerCase().includes(q)) && (!mk || c.make === mk)
    && (show === "all" || (show === "match" ? !c.needs_call : !!c.needs_call)));
  cars.sort((a, b) => { let x = a[sortK], y = b[sortK];
    if (sortK === "hist") { x = a.hist.length; y = b.hist.length; }
    const nx = num(x), ny = num(y); if (nx != null && ny != null) return (nx - ny) * dir;
    return String(x ?? "").localeCompare(String(y ?? "")) * dir; });
  document.getElementById("rows").innerHTML = cars.map(c => `<tr>
    <td class="num">${esc(c.score)}<br>${c.needs_call ? '<span class="chip call">needs a call</span>' : '<span class="chip match">match</span>'}</td>
    <td class="car"><a href="${esc(c.listing_url)}" target="_blank" rel="noopener">${esc(c.title)}</a><div class="vin">${esc(c.vin)}</div>
      ${c.needs_call ? `<div class="small">Ask about: ${esc(c.needs_call)}</div>` : ""}${c.notes ? `<div class="small">${esc(c.notes)}</div>` : ""}</td>
    <td>${esc(c.dealer)}<div class="small">${esc(c.distance_mi)} mi</div></td>
    <td class="num">${fmt$(c.price_total)}${c.fees_estimated === "True" ? '<div class="small">fees est.</div>' : ""}</td>
    <td>${spark(c.hist)}</td><td class="num">${num(c.mileage) == null ? "?" : Math.round(num(c.mileage)).toLocaleString()}</td>
    <td class="num">${num(c.mpg_combined) == null ? "?" : Math.round(num(c.mpg_combined))}<div class="small">${num(c.mpg_city) != null ? Math.round(num(c.mpg_city)) + "/" + Math.round(num(c.mpg_hwy)) : ""}${c.fuel_type === "phev" ? " gas" : ""}${c.mpg_source === "EPA" ? " EPA" : ""}</div></td>
    <td>${esc(c.colors)}</td><td>${esc(c.feat)}<div class="small">${esc(c.cpo_program)}</div></td>
    <td class="${esc(c.carfax_status)}">${esc({clean:"no accidents", accident:"accident", not_verified:"not verified"}[c.carfax_status] || c.carfax_status)}</td>
    <td class="num">${fmt$(c.est_monthly_cost)}</td><td class="small">${esc(c.first_seen)}</td></tr>`).join("")
    || '<tr><td colspan="12" class="muted">No cars match these filters.</td></tr>';
}
document.querySelectorAll("th").forEach(th => th.addEventListener("click", () => {
  const k = th.dataset.k; dir = sortK === k ? -dir : (k === "score" ? -1 : 1); sortK = k; render(); }));
["q", "show", "make"].forEach(id => document.getElementById(id).addEventListener("input", render));
render();
</script></body></html>
"""
