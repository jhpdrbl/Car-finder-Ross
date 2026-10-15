# CPO SUV Finder

Finds certified pre-owned, 2-row, AWD/4WD SUVs at franchise dealers near ZIP 90039 that match
the criteria in `config.yaml` (originally `car-scraper-spec.md`). It produces a newsletter-style
digest, CSVs and a dashboard, and publishes them to a private page for viewing on a phone.
Every result links to the dealer's own listing page and includes the VIN.

- **Handoff / current state for a new Claude session:** [CLAUDE.md](CLAUDE.md)
- **Running it with Claude Code on the laptop (recommended):** [LAPTOP-HANDOVER.md](LAPTOP-HANDOVER.md)
- **User's step-by-step setup (Windows laptop + phone page):** [SETUP-WINDOWS.md](SETUP-WINDOWS.md)

## Quick start on the laptop

**First time only** (about 15 minutes, details in [SETUP-WINDOWS.md](SETUP-WINDOWS.md) Part 1):

1. Install Python and Git: in PowerShell, `winget install -e --id Python.Python.3.13` and
   `winget install -e --id Git.Git`; then close and reopen PowerShell.
2. Download: `cd $HOME\Documents`, then
   `git clone -b claude/la-cpo-suv-scraper-x0pl15 https://github.com/jhpdrbl/Car-finder-Ross.git`.
3. In `Documents\Car-finder-Ross`, double-click **`setup.bat`** and press **Y** for the browser add-on.
4. Double-click **`diagnose.bat`** and send Claude the file it writes (`output\diagnose_<date>.md`).
   It shows how the Audi dealer sites look from home so the Audi part can be tuned.

**Every time:**

1. Double-click **`update.bat`** if Claude changed anything since your last run.
2. Double-click **`refresh.bat`**. The first laptop run takes about 10–20 minutes (about 80 more
   dealer sites load from home than from the cloud); later runs are faster because cars already
   ruled out for good aren't re-read. The dashboard opens when it's done.
3. When it asks **"Publish these results to your phone page?"**, press **Y**. About 2 minutes later
   <https://cpo-suv-finder.pages.dev> shows the new results (sign in with your email code).

**Reading the dashboard:** two tabs, **Available** and **No longer available**. A **NEW** bubble marks
cars that appeared since the last refresh; a bold green **▼** next to a price means it dropped,
and **Original price** shows what it was first listed at and how much less it is now. Tap the
Status / Make / Fuel pills to filter (several at once), tap a column header to sort. On a phone each car shows as a card (no sideways scrolling) and a **Sort** menu replaces the headers. **Favorites**: tap **♡ Save** on a car; the ♥ tab shows them; they sync between devices through `functions/api/favs.js` (Cloudflare KV bound as `FAVS`), or stay on the device if that isn't set up. **Compare**: tap **+ Compare** on up to 6 cars and open the Compare tab. **Trim guide**: what each trim includes by year, plus each brand's warranty. The **Warranty** column estimates the coverage left and when it ends.

**Easiest: let Claude do it.** Open Claude Code on the laptop in the `Car-finder-Ross` folder and
say *"run the refresh and publish it"* (or, the very first time, *"set this up and run the
refresh"*). It reads `CLAUDE.md`, runs the commands for you (you just click **Allow** when it
asks), and tells you the results. The double-click `.bat` files above are the manual alternative.

**If something looks wrong:** take a screenshot and send it to Claude, or describe it to Claude
Code in the folder; it reads `CLAUDE.md` and knows how everything fits together.

## How it runs

```
Laptop:  refresh.bat  →  python run.py refresh  →  share-results.bat (git push data/ output/)
GitHub:  push touching output/**  →  .github/workflows/publish.yml  →  tools/build_site.py  →  wrangler pages deploy
Phone:   https://cpo-suv-finder.pages.dev  (Cloudflare Access: email one-time code)
```

The search runs on a **home computer** because ~80 of the ~200 dealer sites block cloud and
datacenter IPs, including GitHub Actions and Claude's cloud sessions. Those are reported
as "blocked" in the coverage report, not worked around. GitHub Actions only publishes.

## Commands

```
python run.py refresh                       # the whole search (first laptop run ~10-20 min; repeat runs faster)
python run.py refresh --brands Audi,Subaru  # some brands only
python run.py refresh --dealers McKenna     # dealers whose name contains the text
python run.py refresh --workers 24 --no-enrich
python run.py refresh --full                # re-read every listing page (ignore reusable exclusions)
python run.py diagnose --brand Audi         # how dealer sites look from this machine → output/diagnose_<date>.md
python run.py diagnose --platform dealer_inspire | --dealer "Audi Pasadena"
python run.py dealers [--refresh-raw] [--detect]   # rebuild data/dealers.csv
python -m tools.build_site                  # build site/ locally (what the publish workflow deploys)
```

On Windows use `.venv\Scripts\python` (created by `setup.bat`). The `.bat` files wrap these:
`setup.bat`, `refresh.bat` (runs, opens the dashboard, offers to publish), `share-results.bat`
(pull + commit `data/` `output/` + push), `diagnose.bat`, `update.bat` (git pull).

## Pipeline (`run.py refresh`)

1. **Brand certified-inventory feeds** (`scrapers/brand_feeds.py`): genesis.com and subaru.com CPO
   searches cover every Genesis and Subaru dealer, even ones whose sites block us. Each car carries
   the dealer's own listing URL. These brands' dealers are then "skipped (covered by brand feed)".
2. **Dealer sites** (`core/pipeline.py`, 24 in parallel; each site still gets ≤ 1 request per 2–3 s):
   homepage check → discovery by platform → **pre-filter** (drop URLs that name an off-list version,
   e.g. sDrive/AMG/RX L; batch-decode VINs found in URLs, 50 per NHTSA call, and drop off-list models/years)
   → **reuse** last run's row for cars excluded for a permanent reason (color, model, trim, drivetrain,
   rows, mileage; price-only exclusions are re-read every 2 days), unless the rules changed
   (fingerprint of `config.yaml` + rule code in `data/run_state.json`) → fetch the remaining listing pages → parse.
   A typical repeat run takes ~4 min from the cloud.
   | Platform (`dealers.csv: platform`) | Discovery |
   |---|---|
   | `dealer_com` | `scrapers/dealer_com.py`: search page JSON (`?search=<model>&start=N`) |
   | `dealeron` | `scrapers/dealeron.py`: sitemap + search pages |
   | `dealer_inspire` | `scrapers/dealer_inspire.py`: `/llm/inventory` (untested: all DI sites block cloud IPs) |
   | Audi platform (`unknown`, brand Audi) | `scrapers/audi_network.py`: sitemap → inventory pages → browser (untested) |
   | anything | `scrapers/generic_jsonld.py`: sitemap discovery; `playwright_fallback.py` if installed |

   Listing pages are parsed by `generic_jsonld.parse_vdp`: schema.org JSON-LD, platform data
   attributes, label/value text, features (sunroof, audio, leather, ventilated seats, spare),
   certification wording, CARFAX badges. A listing that redirects to inventory = sold.
3. **Enrichment**: brand-feed cars get their dealer page read when it loads (sunroof, audio, CARFAX).
4. **Verification** (`verify/`): NHTSA vPIC VIN decode (year, model, drivetrain, body, seats,
   hybrid/PHEV/EV), NHTSA recall campaigns, certification rules, CARFAX badge status,
   EPA MPG from fueleconomy.gov when the listing has none.
5. **Rules** (`core/criteria.py`, driven by `config.yaml`): hard filters → `fail_reasons`
   (excluded), unknowns → `needs_call`, plus notes; nice-to-have score; monthly cost.
6. **History** (`core/history.py`): merges into `data/listings.csv` (first/last seen, status) and
   `data/price_history.csv`. A car is marked sold (with `removed_on`) only if its dealer (or brand feed)
   was read successfully this run, so partial runs never mark blocked dealers' cars as sold.
   Sold cars feed the dashboard's "No longer available" tab.
7. **Outputs** (`core/outputs.py`): `output/digest_<date>.md`, `output/dashboard.html`,
   `data/coverage.csv`; coverage summary printed at the end.

## Rules it follows

- Never uses aggregator data (Cars.com, CarGurus, KBB, Edmunds, Autotrader, Capital One, CARFAX
  listings, iSeeCars, Westlake, NetLook); blocked in `scrapers/base.py`. Official brand sites are allowed.
- Never fetches carfax.com; CARFAX status comes from the dealer page's badge/text only
  ("clean" only when it explicitly says no accidents).
- Respects robots.txt, 1 request per 2–3 s per site, caches pages 6 h, honest User-Agent.
- Doesn't try to get past bot protection.

## Files

| Path | What |
|---|---|
| `config.yaml` | Criteria, price caps + cushion, colors, **model rules (`models:`)**, trims with standard sunroof, scoring, finance, publish options |
| `data/dealers.csv` | 204 dealers ≤ 60 mi: brand, homepage, platform, distance, source (brand locator / web research) |
| `data/dealers_manual.csv` | Researched dealers for brands whose locators block cloud IPs (Audi, BMW, Mercedes, Ford, Volvo) |
| `data/locator_raw/` | Raw brand-locator responses + geocode cache |
| `data/listings.csv` | Every listing ever seen: status (active/sold/excluded), first/last seen, all fields, MPG, fail reasons, needs_call |
| `data/price_history.csv` | VIN, date, price |
| `data/trim_guide.json` | Trim guide tab: per model / year / trim features, seat material, year-to-year changes (researched from manufacturer sources) |
| `data/warranty.json` | Factory + certified pre-owned warranty terms per brand (Warranty column, warranty comparison) |
| `data/exclusions.csv` | VINs excluded by hand (VIN, reason) |
| `data/coverage.csv` | Last run: every source, success/failed/skipped and why |
| `output/digest_<date>.md` | Digest: coverage, matches, new, price changes, needs a call, removed |
| `output/dashboard.html` | Tabs: **Available** (sortable table, multi-select filters, NEW bubble, green ▼ on price drops, original price, fuel/MPG, monthly cost) and **No longer available** (cars once shown that later sold/were removed: first seen, gone since, days listed, last price); light/dark |
| `output/dealers.html` | Dealer list page (`python -m tools.dealer_page`) |
| `site/` | Built for publishing (gitignored) |
| `tools/` | `dealer_locator.py`, `verify_dealer_sites.py`, `dealer_page.py`, `diagnose.py`, `build_site.py` |
| `functions/api/favs.js` | Cloudflare Pages Function: stores favorites (KV binding `FAVS`) so they sync between devices |
| `.github/workflows/publish.yml` | Publish to Cloudflare Pages (needs repo secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`) |
