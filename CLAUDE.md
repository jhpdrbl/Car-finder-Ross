# CLAUDE.md: handoff notes for the CPO SUV Finder

Read this first. It is the state of the project and how to operate it. The user's own laptop
instructions (and the prompts they'll paste) are in `LAPTOP-HANDOVER.md`. `README.md` is the
technical reference, `SETUP-WINDOWS.md` is the user's step-by-step guide, and
`car-scraper-spec.md` is the original spec (criteria are now in `config.yaml`, which wins
where they differ; see "Decisions" below).

## The user

- Non-technical; mostly on an **iPad** (Safari + the Claude app). Has a **Windows laptop** at home.
- Wants plain language and numbered, tap-by-tap steps. When they send a screenshot, read it
  and tell them exactly what to tap next.
- Goal: find a certified pre-owned 2-row AWD SUV around LA. Top brands: **Audi, Subaru, Genesis**.

## How the system works (the one thing to understand)

```
Laptop (home internet)                 GitHub                          Cloudflare Pages
refresh.bat ──► run.py refresh ──► git push data/ output/ ──► Actions "Publish dashboard" ──► cpo-suv-finder.pages.dev
   (full coverage)        share-results.bat     (on push touching output/**)        (public, noindex)
```

- **The search must run on the laptop.** About 80 of 204 dealer sites block cloud/datacenter IPs
  (Cloudflare and Akamai bot protection, and Audi's own dealer platform), including GitHub
  Actions runners and Claude's cloud sessions. From a home connection they normally load.
  **Do not try to get around bot protection** (no residential proxies, stealth browsers,
  CAPTCHA solving). Blocked sites are reported in the coverage report; that is the design.
- **The phone page is static.** It shows the last pushed run. It can't refresh itself.
- **GitHub Actions only publishes, it never scrapes.** `.github/workflows/publish.yml` builds
  `site/` with `tools/build_site.py` (dashboard + digest, buying-context lines removed,
  noindex) and deploys with wrangler. Triggers: a push that changes `output/**`, or
  **Run workflow** in the Actions tab.

## Where things are

- Repo `jhpdrbl/Car-finder-Ross`; working branch **`claude/la-cpo-suv-scraper-x0pl15`**, which is
  also the repo's **default branch** (no `main` yet; nothing merged; no PR).
- The laptop clone is `Documents\Car-finder-Ross` (per SETUP-WINDOWS.md), on that branch.
- **Favorites sync is live** (Oct 15 2026): Workers KV namespace `cpo-suv-favorites` is bound to the
  Pages project as `FAVS`; `GET https://cpo-suv-finder.pages.dev/api/favs` returns `{"fav": [VINs]}`.
  `wrangler pages deploy` picks up `functions/` from the repo root (the publish workflow runs from there).
- **Cloudflare is set up and working** (done from the iPad, Oct 2026): repo secrets
  `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` exist; Pages project `cpo-suv-finder`.
  Publishing works. **No Cloudflare Access: the user chose (Oct 2026) to keep the page public** (nothing
  sensitive; noindex; buying context stripped). Favorites are therefore one shared list under KV key
  `fav:default`; if Access is ever added, they carry over to the signed-in email on first load.

## Operating it

### If you are a Claude session ON THE LAPTOP (Windows): the main way this gets run

The user will **not** type commands; they ask you ("run the refresh and publish it") and approve
your tool calls. Run everything yourself. **Don't run `setup.bat` or `refresh.bat`**: they stop at
`choice`/`pause` prompts waiting for a keypress and will hang your shell. Use the commands below.
Your shell may be PowerShell or Git Bash; Bash forms are shown, and in PowerShell use
`.\.venv\Scripts\python` instead of `.venv/Scripts/python`.

**Every refresh:**

```bash
git pull                                              # latest code (Claude in the cloud may have changed it)
.venv/Scripts/python -m pip install -q -r requirements.txt   # cheap; picks up new dependencies
.venv/Scripts/python run.py refresh                   # 5-20 min: run it in the BACKGROUND, then wait for it
git pull --no-edit && git add data output && git commit -m "Results from laptop run" && git push
```

- The refresh outlasts a normal command timeout: start it as a background command and wait for it to
  finish (or pass a long timeout). Its last lines are the coverage report and RESULTS summary.
- The push triggers GitHub Actions "Publish dashboard"; when it's green (about 2 minutes), tell the
  user to refresh https://cpo-suv-finder.pages.dev. Summarize for them in plain words: how many
  matches / need a call, what's NEW, price drops, and which dealers failed and why.
- **Their favorites:** `curl -s https://cpo-suv-finder.pages.dev/api/favs` lists the VINs they saved (♥).
  Look those up in `data/listings.csv` and lead the summary with what changed for them: price drops,
  sold/removed (`status=sold`), or no longer matching (`status=excluded`, see `fail_reasons`).
- The dashboard the refresh writes locally (`output/dashboard.html`, opened from disk) can't sync
  favorites; if the user wants favorites on the laptop, have them open the online page instead.
- `data/trim_guide.json` and `data/warranty.json` are hand-researched reference data (Trim guide tab,
  Warranty column), not run output; a refresh doesn't change them, so `git add data` leaves them alone.
- `git push` may open a browser window for GitHub sign-in the first time; tell the user to sign in
  and click Authorize.

**First time on this laptop** (check: does `.venv/Scripts/python` exist?):

1. Needs Python 3.11+ and Git. If missing: `winget install -e --id Python.Python.3.13` /
   `winget install -e --id Git.Git` (the user approves; a new shell may be needed afterwards).
2. If the repo isn't cloned yet: `git clone -b claude/la-cpo-suv-scraper-x0pl15 https://github.com/jhpdrbl/Car-finder-Ross.git`
   into `Documents`, and work from that folder.
3. `py -3 -m venv .venv` (or `python -m venv .venv`), then `.venv/Scripts/python -m pip install -r requirements.txt`.
4. **Ask the user** before the browser add-on (~150 MB; needed for some JavaScript-only sites):
   `.venv/Scripts/python -m pip install "playwright>=1.48"` then `.venv/Scripts/python -m playwright install chromium`.
5. `git config user.name` / `user.email`: if unset, set them for this repo (e.g. "Car Finder Laptop" /
   "car-finder@localhost") so commits work.
6. Run `.venv/Scripts/python run.py diagnose --brand Audi`, read `output/diagnose_<date>.md`, and use it
   to fix `scrapers/audi_network.py` (open item 1 below) **before** the first full refresh. Commit
   code fixes too.

7. **Automatic daily search** (the user asked for it): ask what time they want (default 6:30 am), then
   `powershell -ExecutionPolicy Bypass -File setup-schedule.ps1 -Time 06:30`. It registers a Task Scheduler
   task that runs `scheduled-refresh.bat` (pull → pip → `run.py refresh` → pull -X ours → add data output →
   commit → push), wakes the laptop, catches up if it was off, and logs to `logs\refresh_<stamp>.log`.
   Tell the user to keep the laptop plugged in and, if Windows asks, allow wake timers
   (Control Panel → Power Options → Change plan settings → Advanced → Sleep → Allow wake timers → Enable).
   `-Remove` turns it off. Test once by running `scheduled-refresh.bat` and reading the log.
   Before a manual refresh, check for `logs\running.lock` (a scheduled run in progress, if < 3 h old).

**Things that make coverage worse on the laptop:** a VPN (looks like a datacenter again) or the
laptop sleeping mid-run. If a big share of dealers fail as "blocked", ask whether a VPN is on.

### Running from the iPad itself (a-Shell)

The user can also run the full search on the iPad with the a-Shell app (`IPAD.md`, user-facing steps):
`python ipad.py` downloads the branch zip (repo is public), runs `run.py refresh` in-process (iOS apps
can't fork/exec), and uploads `data/` + `output/` through the GitHub Git Data API with a fine-grained
token in `.github_token` (gitignored). `python ipad.py check` = dry run against GitHub. Limits: no
Playwright on iPad (browser-only dealer sites fail; matters for Audi), no `lxml` (falls back to
`html.parser`, same results in testing), a-Shell must stay in the foreground. **The SQLite page cache
deadlocks in a-Shell with many threads** (first iPad run, Oct 15 2026: every dealer thread stuck in
`requests_cache/backends/sqlite.py`), so `ipad.py` sets `CARFINDER_CACHE=memory` and `--workers 12`. The upload path was
tested on the user's first iPad run (Oct 15 2026): search 11.9 min, upload worked. Coverage from the
iPad was about the same as from the cloud (94 read / 85 failed): most blocking is bot detection of
non-browser clients, not IP-based, so expect similar from the laptop without Playwright.

### If you are a Claude session IN THE CLOUD (the user is on the iPad)

You can change code, rules, the dashboard and docs, and push them. You **cannot** do a full
refresh: about 80 dealers will fail as "blocked". What to do:

1. Make code/config changes, test what you can (`python run.py refresh --brands Genesis,Subaru`
   works from the cloud because those come from brand feeds), commit, push.
2. **Don't commit `data/` or `output/` from a cloud run unless the user asks.** The laptop's
   results are the source of truth; a cloud run would replace the dashboard with partial
   coverage, and parallel edits to the CSVs cause merge conflicts on the laptop's next
   `share-results.bat` (it does `git pull` first).
3. To show a dashboard/UI change on the phone **without** a new search: regenerate the page
   from the existing data, commit only `output/dashboard.html`, and push (that triggers the
   publish):
   ```python
   from core import outputs, history
   rows = history.read_csv(history.DATA / "listings.csv")
   outputs.write_dashboard(rows, history.read_csv(history.DATA / "price_history.csv"),
                           history.read_csv(history.DATA / "coverage.csv"), "<date of that run>")
   ```
4. Tell the user to run `update.bat` then `refresh.bat` on the laptop to apply rule changes to
   the full dealer set.

## Current state (as of 2026-10-15)

- **Ready for the first laptop run.** Everything since the last cloud search was dashboard/reference
  work plus one rule fix (Q5 sunroof). Because `config.yaml` and `criteria.py` changed, the first laptop
  run re-reads every listing page (rules fingerprint) and is slower than later runs; that's expected.
- Dashboard (Oct 15, cloud): phone card layout, Favorites (synced), Compare, Trim guide + warranty
  comparison, Warranty column with expected end dates. The page is public (user's choice).
- All runs so far were **from the cloud**; the laptop hasn't been set up yet (the user has the
  guide, `LAPTOP-HANDOVER.md`). Latest cloud run: 99 sources read, 80 failed, 27 covered by brand feeds;
  19 meet all criteria, 18 need a call (after adding the new models). `data/` and `output/` hold that run.
- **Blocked from the cloud** (expected to work from the laptop): 54 Cloudflare, 5 Akamai,
  12 Audi-platform ("site currently not available"). Audi: only McKenna Audi, Audi North
  Orange County and Audi South Coast load from the cloud; the other 16 Audi dealers don't.
- **Connection errors** (likely wrong homepage guesses in `data/dealers_manual.csv`, check
  from the laptop and fix the URL): Audi Sherman Oaks, BMW of Monrovia, Downey Ford, Corona
  Ford, Mission Viejo Ford, W.I. Simonson Mercedes-Benz, Walter's Mercedes-Benz,
  Mercedes-Benz of Laguna Niguel, Volvo Cars Valencia.

## Open items / next steps

1. **Audi adapter is untested** (`scrapers/audi_network.py`). Audi dealer sites and audiusa.com
   refuse cloud IPs, so it was written blind: sitemap → inventory pages → Playwright. First
   laptop task: `run.py diagnose --brand Audi`, read the report, tune the adapter.
2. **Dealer Inspire adapter is untested** (`scrapers/dealer_inspire.py`, `/llm/inventory`).
   Every DI site is behind Cloudflare. Check with `run.py diagnose --platform dealer_inspire`.
   Note the brand feeds already cover Genesis/Subaru DI dealers.
3. **Dealer list for Audi, BMW, Mercedes-Benz, Ford, Volvo is from web research**, not the brand
   locators (those block cloud IPs). Rows are `source=web research`, mostly `status=unverified`.
   The user may send screenshots of each brand's locator for ZIP 90039; add missing dealers to
   `data/dealers_manual.csv` and rebuild with `python run.py dealers --detect`.
   Known gaps: Shelly BMW (Buena Park) site not found; Volvo Cars Tustin / Thousand Oaks not found.
4. **Subaru moonroof**: the subaru.com feed doesn't list moonroofs. Since Oct 15 2026 `sunroof_standard`
   infers it where Subaru makes it standard (every Forester but Base; Outback Touring/XT; Outback Limited
   2025+). Still a call: 2023–24 Outback Limited and Outback Wilderness (optional package), unless the
   dealer page (`pipeline.enrich_from_dealer_page`, works from the laptop) or `data/confirmed.csv` says so.
5. CARFAX is almost always `not_verified` (dealer pages rarely say "no accidents" explicitly).
   That's per spec; don't loosen it without asking.
6. **Trim guide / warranty data** (`data/trim_guide.json`, `data/warranty.json`) were researched Oct 2026
   by sub-agents from manufacturer press sites, brand pages/booklets and fueleconomy.gov; Volvo/VW/Ford
   trims and some Lexus/Toyota details came from Car and Driver or search summaries because those
   makers' sites refused the requests. Items that couldn't be confirmed say "unknown" / "confirm on
   window sticker". 2027 model years are included only for some models (whatever was on sale). Update by
   editing the JSON (schema: model → years → trims with name, on_list, why_not, powertrain, builds_on,
   highlights, sunroof, premium_audio, seats, black_interior, spare, mpg) and regenerating the dashboard.
   Same rules as everything else: no aggregators, honest requests, never carfax.com.
8. **Facts the user checked by hand** go in `data/confirmed.csv` (vin, trim, sunroof yes/no, note). `run.py:apply_confirmed`
   applies them before the rules on every run, adds a "checked by you" note, and such VINs are never carried
   forward unread. Use it when the user says "I checked, it's a Select / it has the sunroof". (To rule a car
   out by hand, use `data/exclusions.csv`.)
9. **Brand-wide CPO searches** (user found them, Oct 15 2026; checked robots.txt + network calls). Feeds now: Genesis, Subaru,
   Volvo (browser only), Lexus (supplement), Volkswagen:
   Audi audiusa.com = 403 even from the iPad on home Wi-Fi (no Audi feed). Toyota toyotacertified.com =
   data under `/rest/*`, which its robots.txt disallows (no feed). Mercedes = `nafta-service.mbusa.com/api/inv/...`
   but that host's robots.txt returns 5xx, so off limits (RFC 9309). Volvo = Codeweavers API
   (`services.codeweavers.net`, robots allows) -> **feed built** (`brand_feeds.volvo`): opens the store page in
   Playwright, then queries the store's search from inside that page (it needs the store's own session, a
   plain request gets 401); certified (`IsFranchiseApproved`) XC40/XC60 within edge radius, listing URL =
   the dealer's own link. Needs Playwright: without it (iPad) the feed fails and Volvo dealer sites are
   read instead (`scrape_all(covered=...)` only skips brands whose feed succeeded this run). Lexus = **feed built** (`brand_feeds.lexus`,
   `lexus.com/rest/lexus/inventorySearch/cpo`, plain requests, works on the iPad too) but it has no link to the car's
   page, so it's a SUPPLEMENT feed (`SUPPLEMENT_FEEDS`): Lexus dealer sites are still read and their real links win in
   `dedupe` (which keeps the feed's proof of certification); cars at blocked dealers link to the dealer's certified
   inventory `?search=VIN` with `Listing.link_note` shown as a note. Enrichment only takes data from a page whose VIN
   matches. VW = **feed built** (`brand_feeds.vw`): plain GET to VW's inventory service
   (`https://v*.gsl.feature-app.io/bff/car/search`, t_cartype=U = certified, its robots.txt is 401 = no rules) with the
   public key + signed endpoint + data version read fresh each run from `www.vw.com/en.global-config.json`; each car has
   the dealer's own listing URL (`onlineSalesUrl`). Works on the iPad. Keeps 2025+ Tiguans. VW dealer sites are skipped
   when it succeeds. BMW bmwusa.com didn't connect from the cloud; try from the iPad.
7. Warranty column assumptions: in-service date ≈ April of the model year; mileage end at
   `config.yaml: warranty.miles_per_year` (12,000); CPO coverage that starts later with ≤ 30k miles counts
   those miles from its start (`additive()` in the template). Roadside/rust coverage isn't shown per car.

## Decisions the user made (don't revert)

| Topic | Decision |
|---|---|
| Radius | Include dealers up to **60 mi**; 50–60 mi get an **"edge" note** (`home.radius_miles: 50`, `edge_radius_miles: 60`) |
| Price | **$500 cushion** on every cap: gas ≤ $35,500, hybrid/PHEV ≤ $40,500 (incl. dealer fees, before tax). If only *estimated* fees push a car over, it goes to "Needs a call", not excluded |
| Interior | **Black only**; gray interiors excluded |
| Exterior | Black / gray / dark green. **Silver excluded** (names with gray/graphite, e.g. "Silver Gray", still count as gray) |
| Subaru trims | Limited / Touring / Wilderness (+ Forester Hybrid). **Onyx Edition excluded** |
| Models | Spec models **plus (Oct 2026): Audi Q3, Genesis GV80 (2-row), Lexus RX (not RX L), BMW X5 (xDrive40i/50e), Mercedes GLE (350/450/450e 4MATIC; no AMG/Coupe/580), Volvo XC40**. Rules in `core/criteria.py:model_check`, tokens in `scrapers/listing.py:MODEL_TOKENS`, notes in `config.yaml: brands` |
| Interior colors | Light interiors (Blond, Oyster, Parchment, Amber…) excluded; list in `config.yaml` |
| Certification | Only strong evidence counts (brand CPO feed, or URL/title/structured data says certified). Page text alone → "Needs a call" (every site has a "Certified Pre-Owned" menu) |
| Sunroof | Inferred from trim only where standard (Subaru: Forester all but Base, Outback Touring/XT, Outback Limited 2025+; Q5 Premium Plus/Prestige, 2025+ Sportback, all 2026+ (corrected Oct 2026: optional on 2023–25 Premium), GV70 Select+, XC60 Plus/Ultimate, Bronco 4-door); see `config.yaml: sunroof_standard` |
| Mild hybrids | Count as **gas** (fuel type from NHTSA vPIC ElectrificationLevel, not dealer wording) |
| Phone page | **Public** (user declined Cloudflare Access, Oct 2026: nothing sensitive), noindex; published digest omits buying context (`publish.include_buying_context: false`) |
| Dashboard | Columns include Year (sortable, newest first), Fuel and MPG (listing value, else EPA from fueleconomy.gov; PHEV = gas-only); multi-select filter pills (status, make, fuel) plus an "Only NEW" toggle; a **No longer available** tab listing every car that was ever on the dashboard and later sold/was removed (`status=sold`, `removed_on`); a one-time **opening animation** (compact SUV, Q5/GV70-like, drives across the top leaving tire marks that fade; skipped with Reduce Motion); **NEW** bubble (car first became available in the latest run: `new_run == max(seen_run)`); bold green **▼** when price < first recorded price, and an **Original price** column (replaced the price sparkline); the **table header row stays on screen** while scrolling (JS `stickHeads()`, because the table's sideways-scroll box defeats CSS sticky); on **phones (≤ 760 px) each car is a card** (no sideways scrolling; `@media` block in `outputs.TEMPLATE`, cells labelled via `data-l`) with a **Sort** menu instead of tappable headers; **Favorites** (♥ Save on any car; the ♥ tab = Available limited to favorites, sold favorites listed above; synced between devices by the Pages Function `functions/api/favs.js` (KV namespace bound as `FAVS` in the Pages project's Settings > Bindings; one shared list, since the page has no sign-in); without sync (local file / no binding) they stay in localStorage and "copy a link with your favorites" = `#fav=VIN,…` moves them); **Check yourself** tab (`outputs.check_list`: failed dealers of brands without a working brand feed, top brands then distance, plain-words reason, per-model links to the dealer's own **certified** inventory (`_cpo_base`: certified URL on file, else Dealer Inspire `/used-vehicles/certified-pre-owned-vehicles/` + `_dFR[model][0]` filter, Dealer.com `/certified-inventory/index.htm?search=`; unknown platforms incl. Audi's own: the site + the brand's certified search from `BRAND_CPO_SEARCH`; user asked for CPO-only links, Oct 2026), "Mark checked" dates synced via `functions/api/checked.js` (same FAVS KV, key `checked:default`), stale after 7 days); floating **↑ back-to-top** button (appears after scrolling 600 px); **Compare** tab (tap "+ Compare" on up to 6 cars; field-by-field, ★ = best; selection kept in the viewer's localStorage; a "Comparing N cars · View · Clear compare" bar above the filters, and Clear compare at the top of the tab); **Trim guide** tab (`data/trim_guide.json`: per model/year/trim what's included, seat material, year-by-year changes; hand-researched from manufacturer sources) with a **warranty comparison** (`data/warranty.json`: factory + CPO terms per brand); **Warranty** column per car = coverage left + expected end date (in-service assumed ~April of the model year; mileage end at `config.yaml: warranty.miles_per_year`), sortable |

## Hard rules (from the spec)

- Every result links to the **dealer's own listing page** and includes the **VIN**.
- **Never** use aggregator data (Cars.com, CarGurus, KBB, Edmunds, Autotrader, Capital One,
  CARFAX listings, iSeeCars, Westlake, NetLook). Blocked in `scrapers/base.py:is_blocked_host`.
  Official brand sites (genesis.com, subaru.com CPO searches) are allowed; they're not aggregators.
- **Never fetch carfax.com.** CARFAX status only from badges/text on the dealer page.
- Respect robots.txt (`base.Robots`, RFC 9309: `*`/`$` wildcards, most specific group, longest match;
  4xx = no file = allowed, **5xx/unreachable = whole site off limits**; replaced urllib.robotparser in Oct 2026,
  which ignored wildcards), 1 request / 2–3 s per domain, 6 h cache, honest User-Agent. (No 429s have ever been seen;
  all blocking so far is bot protection on the first request, which delays don't affect.)
- Ask before installing heavy things on the user's machines.

## Performance design (Oct 2026)

- 24 dealers in parallel; politeness is per domain (`base.Fetcher._throttle`), so more workers never
  hits one site faster. Up to 3 headless browsers at once (`playwright_fallback._lock`).
- Before reading listing pages: `pipeline.prefilter` drops URLs matching `listing.URL_SKIP` and
  batch-decodes VINs from URLs (`listing.url_vin`, which also reads Audi's `?vehicleId=`) to drop
  off-list models/years.
- Cars excluded last run for a **permanent** reason are reused without re-reading
  (`pipeline.carry_forward_ok`; price-only exclusions re-read every 2 days). Reuse is disabled
  automatically when the rules fingerprint changes (`run.py:_rules_fingerprint`, stored in the
  gitignored `data/run_state.json`), or with `--full`.
- Model rules are data, not code: `config.yaml: models:` (allow regex + rules with if/unless/then/min_year),
  interpreted by `criteria.model_check`. Add a model there plus a token in `listing.MODEL_TOKENS`.
- Coverage honesty: a dealer whose inventory couldn't be seen (browser blocked, no inventory pages)
  is **failed**, not "no matching models". Same when nothing was found and no browser is available (iPad): that
  dealer's cars must not be marked sold (first iPad run wrongly 'sold' 2 Galpin Volvo cars; restored).

## Gotchas

- Windows consoles are cp1252; `run.py` reconfigures stdout to UTF-8. Open files with `encoding="utf-8"`.
- `.bat` files must keep CRLF (`.gitattributes` enforces it).
- `requests-cache` caches only 200/301/302/404; blocked (403/503) responses are retried each run.
- vPIC `SeatRows` is model-level (4Runner says 3 rows); use `Seats` (≤5 → 2 rows).
- Junk prices: some JSON-LD has `"price": "37.0"`; prices < $3,000 are ignored.
- vPIC often returns no DriveType for Mercedes/VW/BMW. Then the listing decides: 2WD/RWD/FWD/4x2/sDrive in
  the name, title, URL or page data excludes the car (`criteria.NAME_2WD`); AWD/4MATIC/xDrive/quattro passes.
- Some sites answer bots with a "Client Challenge" page **with HTTP 200**. `generic_jsonld.CHALLENGE_PAGE`
  treats it as blocked, and a page with a VIN but no price/mileage/model/color is not a listing.
- `data/cache/` (vPIC, recalls, EPA) is gitignored and rebuilds itself; writes are atomic and the vPIC cache is shared under a lock (dealer threads decode in parallel).
- Commit trailers this project uses: `Co-Authored-By` / `Claude-Session` lines per session instructions.
