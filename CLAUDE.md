# CLAUDE.md: handoff notes for the CPO SUV Finder

Read this first. It is the state of the project and how to operate it. The user's own laptop
instructions are in `LAPTOP.md` (they run it themselves; `LAPTOP-HANDOVER.md` is the older Claude-runs-it route). `README.md` is the
technical reference, `SETUP-WINDOWS.md` is the user's step-by-step guide, and
`car-scraper-spec.md` is the original spec (criteria are now in `config.yaml`, which wins
where they differ; see "Decisions" below).

## The user

- Non-technical; mostly on an **iPad** (Safari + the Claude app). Has a **Windows laptop** at home.
- Wants plain language and numbered, tap-by-tap steps. When they send a screenshot, read it
  and tell them exactly what to tap next.
- Goal: find a certified pre-owned 2-row SUV around LA (AWD preferred: a nice-to-have since Oct 25 2026). Top brands: **Audi, Subaru, Genesis**.

## How the system works (the one thing to understand)

```
Laptop (home internet)                 GitHub                          Cloudflare Pages
refresh.bat ──► run.py refresh ──► git push data/ output/ ──► Actions "Publish dashboard" ──► cpo-suv-finder.pages.dev
   (full coverage)        share-results.bat     (on push touching output/**)        (public, noindex)
```

- **The search must run on the laptop.** About 80 of the ~200 dealer sites block cloud/datacenter IPs
  (Cloudflare and Akamai bot protection, and Audi's own dealer platform), including GitHub
  Actions runners and Claude's cloud sessions. From a home connection they normally load.
  **Do not try to get around bot protection** (no residential proxies, stealth browsers,
  CAPTCHA solving). Blocked sites are reported in the coverage report; that is the design.
- **The phone page is static.** It shows the last pushed run. It can't refresh itself.
- **GitHub Actions only publishes, it never scrapes.** `.github/workflows/publish.yml` builds
  `site/` with `tools/build_site.py` (dashboard + digest, buying-context lines removed,
  noindex) and deploys with wrangler. Triggers: a push that changes `output/**`, or
  **Run workflow** in the Actions tab.

## Two buyers: Ross and Jenna (Oct 16 2026)

**Jenna's tracker was removed Oct 18 2026 (user: "Jenna just bought a car so hers is no longer needed").** Her `profiles.jenna`
block, `data/jenna/`, `output/jenna/` and the "Whose search?" start page are gone (git history has them); with one buyer
`write_dashboard` skips the start page and the "← Ross or Jenna" link, and `build_site` puts Ross's page at `/` (and `/ross/`).
The multi-buyer code stays, so another buyer is just another `profiles:` block. What follows is how it worked with two.

The tracker serves two buyers ("profiles", `core/profiles.py`, config.yaml `profiles:`). **The dealer search runs
once**; every car found is checked against each buyer's rules separately (`criteria.use(cfg)` switches the rules;
each buyer evaluates a deep copy of the listing).
- **Ross** = the original top-level settings; results in `data/` and `output/` (paths unchanged); page `/`.
- **Jenna** = `profiles.jenna` merged over the top-level settings (`models`/`buying_context` replaced, not merged);
  results in `data/jenna/` (listings, price_history, exclusions.csv) and `output/jenna/`; page **`/jenna/`**.
  Her rules: CPO, SUV, **regular hybrid only** (no plug-ins; mild hybrids count as gas), AWD/4WD, < 40k miles,
  **< $40,000** incl. fees (no cushion), **no cloth seats** (leather or synthetic; `Listing.seats` from the page,
  else config `seat_material` by trim; unknown → Needs a call), **any exterior color but red/orange**, any interior,
  **sunroof nice-to-have** (scored, never excludes), **2-row only, 2023+**. Brands: Ross's + **Kia, Acura**, and (Oct 16 2026)
  **Mazda (CX-50 Hybrid) and Lincoln (Nautilus Hybrid)**. User said **no Honda or Hyundai** (don't suggest CR-V/Tucson/Santa Fe again).
  **No white interiors** (exclude-only `interior_colors`). Her **score** (Oct 16 2026) = her nice-to-haves in her order:
  exterior color 40 (black › gray › dark blue › brown › silver › gold › white › anything else; `criteria.color_family`,
  first color word named wins, "Silver Gray" = gray), mileage 30 (0 mi full, 40k none), sunroof 20, real leather 10
  (synthetic 40%). Price isn't in her score (she didn't list it). `scoring.weights` is replaced per buyer, not merged.
- **Scores** (`criteria.score_parts`/`score`): weight × 0..1 per item, scaled to 0-100; the page's "How the score works"
  box is generated from the buyer's weights (`outputs.score_help`). Ross's weights are the spec's (price 30, plug-in 25,
  mpg 12, audio 12, spare 6, leather/vented/clearance 5): a gas car can't get the plug-in 25, so his scores rarely pass 75.
- **Sticker when new** column (both pages): `Listing.msrp_new` from an explicit "original MSRP / window sticker" on the
  dealer page, else the trim's base MSRP when new (destination included, no options) from `data/msrp.json` (`verify/msrp.py`);
  shown with "~" when it's the trim base. `python run.py rescore` re-applies scores, color rules and sticker prices to
  the last results without a search.
- Search scope = union of both buyers (`profiles.could_want`, `min_year(brand)`, `model_tokens`; Ross's URL words stay in
  `listing.ROSS_TOKENS`). Reuse of last run's rows happens only when **every** buyer excluded the car for good
  (`prev_rows[key] = {profile: row}`).
- Each page has its own favorites / compare / checked marks: localStorage keys prefixed `jenna:`; KV keys
  `fav:jenna`, `checked:jenna` via `/api/favs?p=jenna` (Ross keeps `fav:default`). `tools/build_site.py` publishes
  `output/<id>/` to `site/<id>/`. The pill switch at the top links the pages.
- Facts the user confirms (`data/confirmed.csv`) apply to both buyers; ruling a car out (`exclusions.csv`) is per buyer
  (Jenna's: `data/jenna/exclusions.csv`). When the user reports something about a car, ask whose list if unclear.
- Jenna's trim guide: `data/jenna/trim_guide.json` (config `trim_guide:`); warranty table filtered to her brands.
- **Website:** `/` = start page "Whose search?" (`outputs.write_chooser` → `output/index.html`); `/ross/` and `/jenna/`
  are the trackers, each in its own color (config `theme:`: Ross British Racing Green #004225, Jenna Cobalt Blue #0047ab;
  `outputs.theme_vars`). The user wants them kept apart (no mixed views); the header has only a "← Ross or Jenna" link.
  `build_site` keeps Ross's page at `/` too until every buyer's dashboard exists in `output/`.
- Jenna's rules were updated Oct 16 2026: **2023+ and no third row** (so no Highlander/Grand Highlander/Sorento/TX/
  Explorer/RX L/MDX); **mixed seats (leatherette with cloth/fabric/suede inserts, e.g. RAV4 XSE, Corolla Cross XSE) count as cloth**
  (user, Oct 16 2026: "No cloth allowed"), so the Corolla Cross has no qualifying trim; the Lexus UX counts as an SUV (`filters.also_suv`; vPIC says "Wagon"). Acura has no 2-row regular
  hybrid SUV, so Acura has no models yet.

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

**How the user runs it (decided Oct 19 2026): by themselves, the same way on the laptop as on the iPad.**
`LAPTOP.md`: Python from python.org, the project downloaded as a zip to `$HOME\Car-finder-Ross` (no git clone, no
`.venv`), `pip install -r requirements.txt` + Playwright, then `python search.py` (own GitHub token in `.github_token`).
On Windows `search.py` (`LAPTOP = os.name == "nt"`) uses 24 workers (page cache in memory on every machine since Oct 24 2026: the SQLite cache failed with "DatabaseError: another row available" once feeds and dealers ran side by side), pip-installs requirements
after updating, and commits "Results from laptop run". `scheduled-refresh.bat` runs `search.py` when the folder has no
`.git` (one line, so a self-update can't corrupt the running .bat; `ipad.update` skips unchanged files). The Claude-on-
the-laptop route below still works for a git clone, but the user no longer needs Claude to run the refresh.

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
`python search.py` downloads the branch zip (repo is public), runs `run.py refresh` in-process (iOS apps
can't fork/exec), and uploads `data/` + `output/` through the GitHub Git Data API with a fine-grained
token in `.github_token` (gitignored). `python search.py check` = dry run against GitHub. Limits: no
Playwright on iPad (browser-only dealer sites fail; matters for Audi), no `lxml` (falls back to
`html.parser`, same results in testing), a-Shell must stay in the foreground. **The SQLite page cache
deadlocks in a-Shell with many threads** (first iPad run, Oct 15 2026: every dealer thread stuck in
`requests_cache/backends/sqlite.py`), so `search.py` uses `--workers 12` there (the cache is in memory everywhere now; `scrapers/base.py`). The upload path was
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

## Current state (as of 2026-10-20)

- **First laptop run done** (Oct 20 2026, `python search.py` with Playwright, home Wi-Fi): 97 read / 92 failed /
  79 covered by brand feeds; 98 meet all criteria, 31 need a call. **The laptop barely improved coverage over the iPad**:
  only the Volvo feed (needs the browser: 50 cars), Galpin Ford and Penske Toyota newly worked. Still failing:
  60 dealers HTTP 403 and 16 Cloudflare/Akamai (bot detection of non-browser requests, not IP-based), and **14 Audi
  dealers whose robots.txt answers HTTP 500** (Audi's platform), which our robots rule treats as off limits.
  So "the laptop will fix Audi" was wrong; Audi stays manual (Check yourself tab, `manual_listings.csv`).
  The Mazda feed dropped from 209 to 152 cars (20 matching 2026 Mazdas went "sold").


- (Before the laptop run, Oct 19:) The laptop isn't set up
  yet; the user has `LAPTOP-HANDOVER.md`. All searches so far ran from the cloud or the iPad (latest: iPad,
  Oct 18 2026, then rescored for later rule changes: 101 meet all criteria, 57 need a call, 95 sources read,
  84 failed, 68 covered by brand feeds). `data/` and `output/` hold that run.
- **Much changed since that search** (Oct 17-19): electric SUVs, performance versions, plug-in/electric sedans and
  40+ mpg hybrid sedans, Ford Bronco Sport, Acura and Alfa Romeo (new brands, never searched in full; 15 Acura +
  6 Alfa dealers), black two-tone interiors allowed, light greens excluded. So the first laptop run re-reads
  every listing page (rules fingerprint) and is slower than later runs; that's expected. Expect many more cars.
- `dealers.csv` has 269 rows; Lincoln's 8 were Jenna's and aren't searched (Ross has no Lincoln models).
- A cloud smoke test on Oct 19 (`--brands Genesis,Subaru,Acura,"Alfa Romeo"`) ran clean; results not committed.
  It found one Acura match (2024 ZDX A-Spec, Cosmic Black, Weir Canyon Acura); most Alfa/Acura dealer sites
  blocked the cloud.
- Dashboard (Oct 19): filters for status, make, fuel, model year, body (SUV/Sedan), sunroof, upgraded sound,
  price and mileage sliders; tabs Cars, ♥, Compare, Trims, Check yourself (with "Clear all checks"), Sold.
  The page is public (user's choice).
- **Blocked from the cloud** (expected to work from the laptop): 54 Cloudflare, 5 Akamai,
  12 Audi-platform ("site currently not available"). Audi: only McKenna Audi, Audi North
  Orange County and Audi South Coast load from the cloud; the other 16 Audi dealers don't.
- **Connection errors fixed (Oct 16 2026)** from search results: Audi Sherman Oaks is really Audi Van Nuys
  (audivannuys.com, renamed), W.I. Simonson and BMW of Monrovia are `.net`, Walter's = waltersmercedesbenzofriverside.com,
  MB Laguna Niguel = mblaguna.com. Removed 4 dealers that don't exist (research errors): Downey Ford (closed 2009),
  Corona Ford, Mission Viejo Ford, Volvo Cars Valencia. 29 dealers got their certified-inventory page as
  `inventory_url` (notes say seen/inferred from search results); the Audi adapter starts from it on the laptop.
- **Parked domains fixed (Oct 16 2026)**: 15 researched homepages (most Mercedes dealers, Mission BMW, Thousand Oaks Ford)
  were GoDaddy "for sale" pages (JS redirect to `/lander`, one-URL sitemap) and had been counted as *success, no matching
  models*. Real sites found for 11 (+ Volvo Cars Orange County = volvo-oc.com); removed Mission BMW, MB of Tustin (don't
  exist), MB of Glendale (= Calstar), MB of Pasadena (= Rusnak Arcadia), MB of Riverside (= Walter's); added MB of Foothill
  Ranch. `pipeline.PARKED_PAGE` now fails such homepages ("wrong website address") and a sitemap under `TINY_SITEMAP`
  (20) URLs with no candidates is failed too, so this can't hide as "no cars" again.
- Partial runs (`--brands` / `--dealers`) now keep the previous coverage rows for dealers they didn't re-read.

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
   highlights, sunroof, premium_audio, seats, black_interior, spare, mpg; optional per model `match: {model, fuel}` so a car
   listed under a base name finds its entry, e.g. a `GLC` with fuel `phev` → the separate "GLC 350e" entry) and regenerating the dashboard.
   Same rules as everything else: no aggregators, honest requests, never carfax.com.
10. **Cars added by hand** (Oct 19 2026): `data/manual_listings.csv` (vin, dealer's own listing_url, dealer, year/make/model/trim,
   price + doc/other fees, mileage, colors, sunroof, cert_text, added_on). For dealers that block the search when the user sends
   the listing (first: 7 Q4 e-trons at Audi Beverly Hills). `pipeline.load_manual()` adds them to every refresh (same rules,
   note "added by you"); `python run.py add-manual` puts them on the page without a search. They never go "sold" on their
   own (the dealer can't be read): delete the row when the user says it's gone. **Added by you tab** (Oct 27 2026, user: "filter on ones I added myself so that I can check if they are still available"): lists them with Open the dealer's page / ✓ Still available (date; stale after 7 days, tab count = unchecked) / ✕ No longer available (moves the car to the Sold tab at once, client-side `goneAll()`; Undo); **$ Update price** (user, Oct 27 2026: "update the price for the ones I check myself": prompt for the dealer's advertised price before fees; the page shows it at once with the fees on file added, a ▼ when it's $200+ lower, and counts it as a check; `applyMinePrices()`), synced via `functions/api/mine.js` (FAVS KV key `mine:default`, `{seen, gone, price: {VIN: {p, d}}}`); a **Found by** filter (Added by you / The search). Every `refresh` / `rescore` / `add-manual` starts with `run.sync_manual_gone()`: reads `gone` and `price` from `publish.site_url` + `/api/mine` (`pipeline.manual_marks`), deletes those rows from manual_listings.csv and marks the cars sold, and writes updated prices into manual_listings.csv's `price` (`rescore` doesn't re-read manual cars, so a price shows in the data after the next `refresh` or `add-manual`) (removed_on = the date marked); when the site can't be read nothing changes. In a cloud session, `curl -s https://cpo-suv-finder.pages.dev/api/mine` shows the marks.
8. **Facts the user checked by hand** go in `data/confirmed.csv` (vin, trim, sunroof yes/no, ext_color, audio = system name or `none`, msrp_new = window-sticker total, seats = leather/synthetic/cloth, listed_price + fees = the fee total the user saw for that price (0 = price already includes fees; ignored once the price changes), note; sticker = yes when the user sent the car's ORIGINAL window sticker (not a dealer/CPO card): the dashboard shows a white check in a green circle at the top right of that car (`.stickerok`, Oct 24 2026, user asked; hovering or tapping it shows "Features verified by window sticker"); `rescore` applies them too). `run.py:apply_confirmed`
   applies them before the rules on every run, adds a "checked by you" note, and such VINs are never carried
   forward unread. Use it when the user says "I checked, it's a Select / it has the sunroof". (To rule a car
   out by hand, use `data/exclusions.csv`.)
9. **Brand-wide CPO searches** (user found them, Oct 15 2026; checked robots.txt + network calls). Feeds now: Genesis, Subaru,
   Volvo (browser only), Lexus (supplement), Volkswagen, Kia (supplement), Mazda (`brand_feeds.FEEDS`):
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
11. **More brand feeds (Oct 25 2026, user said yes to Jaguar/Acura/BMW)**: **Jaguar** certified search works from the cloud
   (NetDirector GraphQL `production-api-oregon.search-api.netdirector.auto/api/vehicle-search`, `isFranchiseApproved: true`, needs the
   site's public `authorization` header read from inventory.jaguarusa.com in a browser; its robots.txt answers 403 = allowed) but
   **not built**: of 188 certified Jaguars nationwide only 4 were within 60 mi (Galpin Van Nuys F-Pace + 2 F-Types, Jaguar Anaheim
   Hills F-Pace P400; Anaheim Hills isn't in dealers.csv), all gas, so none pass while gas is off (I-Pace roof never opens).
   **Acura / BMW**: `tools/probe_feeds.py` (run on the laptop: `python search.py update` then `python tools/probe_feeds.py`)
   checks robots.txt and lists the data requests the brand's certified search page makes; from the cloud both refuse
   (acura.com 403, bmwusa.com robots.txt timeout). **Laptop result (Oct 25 2026): the same from home** (acura.com and
   acuracertified.com answer 403 Access Denied, bmwusa.com's robots.txt times out), so no Acura or BMW feed; don't retry
   unless something changes on their side.
7. Warranty column assumptions: in-service date ≈ April of the model year; mileage end at
   `config.yaml: warranty.miles_per_year` (12,000); CPO coverage that starts later with ≤ 30k miles counts
   those miles from its start (`additive()` in the template). Roadside/rust coverage isn't shown per car.

## Decisions the user made (don't revert)

| Topic | Decision |
|---|---|
| Radius | Include dealers up to **60 mi**; 50–60 mi get an **"edge" note** (`home.radius_miles: 50`, `edge_radius_miles: 60`) |
| Price | **$500 cushion** on every cap: gas ≤ $35,500, hybrid/PHEV ≤ $40,500 (incl. dealer fees, before tax). If only *estimated* fees push a car over, it goes to "Needs a call", not excluded |
| Interior | **Black only**; gray interiors excluded |
| Exterior | Black / gray / dark green / **silver** (silver allowed since Oct 21 2026, user: "start allowing silver"; was excluded before; "Glacier Silver" passes, "Silver Blue" and matte silvers still fail; Mazda Platinum Quartz is still a call). **No matte paint** (user, Oct 16 2026: "matte", BMW "Frozen", Mercedes "magno", "satin"; Ross only). **Light greens excluded** (user, Oct 19 2026: "Sage green is not dark green"): sage/mint/lime/seafoam/pistachio fail; other unlisted greens are still a call. **Mercedes Emerald Green passes** (user, Oct 25 2026: "4JGGM1CB9PA033049 is a great green"; `criteria.DARK_GREENS` + config include) |
| Subaru trims | Limited / Touring / Wilderness (+ Forester Hybrid). **Onyx Edition excluded** |
| Models | Spec models **plus (Oct 2026): Audi Q3, Genesis GV80 (2-row), Lexus RX (not RX L), BMW X5 (xDrive40i/50e), Mercedes GLE (350/450/450e 4MATIC; no Coupe; AMG/580 allowed since Oct 19 2026), Volvo XC40**; **GLC 350e 4MATIC** added Oct 16 2026 (user: "I love that model"; plug-in hybrid cap applies). **Mazda (CX-5, CX-50 incl. Hybrid, CX-70 incl. PHEV) and Kia Sportage (gas/hybrid/plug-in)** added Oct 16 2026 (user asked; models picked to fit his rules: no CX-30 = too small, no CX-90/Sorento/Telluride = 3 rows, no Niro = FWD); trim rules for sunroof/black interior in config `models: Mazda/Kia`. **Ford Bronco Sport** added Oct 17 2026 (user asked; was excluded before; every one is a 2-row 4x4; the Bronco's "removable roof panels" sunroof inference doesn't apply to it: `sunroof_standard` row `not_model`). **Electric** added Oct 18 2026 (user: "Add electric"; before, EVs counted only as an "exceptional deal"): `price_caps.ev: 40000` (+ $500 cushion, same as hybrid/plug-in), EVs get the plug-in score; models Audi Q4/Q6/Q8 e-tron (not e-tron GT/SQ/RS), Genesis GV60 (+ Electrified GV70), BMW iX (not M60), Mercedes EQB/EQE SUV/EQS SUV, VW ID.4 AWD, Lexus RZ, (Volvo XC40 Recharge/EX40/C40 Recharge, removed Oct 19), Toyota bZ4X/bZ, Subaru Solterra, Ford Mustang Mach-E, Kia EV6 (not EV9: 3 rows); brand feeds pick them up (Genesis `gv60`, VW via `could_want`, Kia `feed_models` EV6, Volvo store models `C40 Recharge`/`EX40`); trim rules (sunroof/AWD/interior per trim), `sunroof_standard` rows (fixed glass roofs count), sticker prices and Trim guide entries for all of them were researched Oct 18 2026 (model rules may use `from_year`/`to_year`). **Performance versions allowed** (user, Oct 19 2026: "I like performance cars and it's fine to add them if they meet all the other requirements"): Audi SQ5/SQ6/SQ8 e-tron/e-tron S/RS Q8, BMW M40i/M50/X3 M/M50i/M60i/X5 M/iX M60/M70, Mercedes AMG and GLE 580 now pass (still excluded: Coupes, Maybach, e-tron GT sedan); EPA lookup gives them their own rating (`fuel_economy._pick_model`). **Plug-in hybrid / electric sedans** (user, Oct 19 2026: 3 Series / A5 to 5 Series size, AWD, all other rules): `filters.sedans` (fuels phev/ev; `models` regex for cars without a VIN body) lets `criteria.evaluate` accept a Sedan/Hatchback body only with those fuels; models BMW 330e/530e/550e xDrive, i4, i5; Mercedes EQE sedan, AMG E 53 HYBRID (2025+), AMG C 63 S E PERFORMANCE (forced phev in `run.py`, vPIC omits it); Audi e-tron GT, A6/S6 Sportback e-tron; Volvo S60/S90 T8; Lexus ES 500e. **Full-size plug-in / electric sedans allowed too** (user, Oct 21 2026: "Let's include full size sedans as long as they meet the other requirements"): Mercedes EQS sedan (4MATIC; the RWD "450+" fails) and S 580e 4MATIC, BMW i7 (xDrive60 / M70; eDrive50 = RWD fails) and 750e xDrive (gas 7 Series fails); gas full-size sedans still fail the sedan fuel rule. Still not: Electrified G80 (no sunroof in the US), ES90 (not sold in US), A8 (no US plug-in since 2021), LS 500h (under 40 mpg). **Regular hybrid sedans** too if they average **40+ mpg** (user, Oct 19 2026; `filters.sedans.hybrid_min_mpg`, EPA combined filled early in `run.py`): Lexus ES 350h AWD 2026+. **No Toyota, Kia or Mazda sedans** (user, Oct 19 2026; `filters.sedans.exclude_makes`), so the Camry/Crown are out. **Volvo XC40 / EX40 / C40 / EC40 removed** Oct 19 2026 (user: "The xc40 is too small"); **XC40 and EX40 (= XC40 Recharge renamed) added back** Oct 21 2026 (user: "you can add back the xc40"); C40 / EC40 still off (Volvo = XC60, XC40/EX40, S60/S90 T8; `run.py rescore` drops models no longer in `allow`). **Acura and Alfa Romeo** added Oct 19 2026 (user: "Add them"): Acura ZDX (2024+; the A-Spec RWD fails on drive; B&O audio and glass roof standard) and RDX (SH-AWD only, FWD fails; roof standard); Alfa Tonale (2024+) and Stelvio (Sprint RWD fails; Tributo 2025 sunroof standard, otherwise sunroof optional = Needs a call); 6 Alfa dealers (`data/dealers_manual.csv`), Alfa colors (grigio/nero/verde fangio/verde montreal pass; rosso/giallo/bianco/tiger eye fail), sticker prices, Trim guide and warranty (Alfa CPO 5 yr/100k) researched Oct 19 2026. **Cadillac** added Oct 24 2026 (user: "You can add Cadillac", then "You don't need to add the gas only ones"): **Lyriq** (incl. 2026 Lyriq-V) and **Optiq** (2025+, incl. Optiq-V), electric only (no XT4/XT5/XT6, no gas CT4/CT5 sedans, Celestiq aside no electric sedan); every one has a fixed panoramic glass roof (`sunroof_standard`); every Lyriq and the 2026 Optiq also come RWD, which fails; black interior = "Noir ..." (`noir` in the interior include list); Inteluxe = synthetic; AKG audio recognised; colors: Stellar Black / Black Raven / Celestial / Argent Silver / Emerald Lake / Satin Steel (gloss: excepted from the 'satin' matte rule) pass, Nimbus (blue) and Magnus Metal Frost (matte) fail; 18 dealers from the cadillac.com dealer locator (7 Dealer Inspire sites block, the rest read); sticker prices (2025 not found), clearance, range, Trim guide and warranty (4 yr/50k + 8 yr/100k battery; CPO +1 yr/unlimited) researched Oct 24 2026. Cadillac's brand-wide certified search (`cadillac.com/cadillac/shopping/api/aec-cp-discovery-api/p/v1/vehicles/search`, robots allows) answers 'Access Denied' (Akamai) to our honest requests from the cloud, even in a browser: no feed (could be tried from the laptop's browser like Volvo's). **Jaguar** added Oct 21 2026 (user: "Add jaguar"): I-Pace (electric, 2023-24), F-Pace (gas; P400 = mild hybrid = gas; no US P400e), E-Pace (2023-24); every one AWD; sunroof optional except the 2024 E-Pace (fixed panoramic roof standard) and unconfirmed on the I-Pace, so most are a call unless the listing says; DuoLeather/Luxtec count as synthetic; satin (matte) greys fail; amethyst/purple excluded; 12 retailers from jaguar.com's SoCal list (`data/dealers_manual.csv`; Pasadena may have dropped Jaguar; Ventura uses landroverventura.com, the shared store's site); sticker prices, clearance, I-Pace range, Trim guide and warranty (5 yr/60k factory; Approved CPO 1 yr/unlimited or 2 yr/100k after it, which cars get which isn't stated) researched Oct 21 2026; a possible Jaguar certified feed (inventory.jaguarusa.com/used-certified/search, isFranchiseApproved, robots 404) is untested. **Body** filter (SUV / Sedan) on the dashboard from `criteria.body_kind` (column `body`; old rows count as SUV) Rules in `core/criteria.py:model_check`, tokens in `scrapers/listing.py:MODEL_TOKENS`, notes in `config.yaml: brands` |
| Interior colors | Light interiors (Blond, Oyster, Parchment, Amber…) excluded; list in `config.yaml`. **Two-tone interiors that include black are OK** (user, Oct 19 2026), e.g. Mercedes "Black/Space Grey", Lexus "Dapple Gray/Black", Ford "Ebony/Roast" (Bronco Sport Outer Banks/Badlands no longer excluded by trim); `interior_ok` checks the black words first |
| Certification | Only strong evidence counts (brand CPO feed, or URL/title/structured data says certified). **Page text alone → excluded** (user, Oct 16 2026: "if certified isn't mentioned anywhere on the listing it's not CPO"; all 9 such cars they checked weren't certified; every site has a "Certified Pre-Owned" menu). Was "Needs a call" before. Such cars are re-read each run (`CHANGEABLE` matches "certif") |
| Sunroof | **Must open** (user, Oct 24 2026: "If the sunroofs don't open then don't include them"; before, fixed glass roofs counted): config `fixed_roofs` (`criteria.fixed_roof`): `never` = fails even when the page says "sunroof" (iX, i7/750e, GV60, ID.4, C40/EC40, RZ, bZ4X/bZ, Solterra, Mach-E, e-tron GT, A6/S6 e-tron, Optiq, 2023 Lyriq, I-Pace, 2024 E-Pace, 2025+ X3); `optional` = passes only when the listing says tilt/slide/opening (`criteria.OPENS`, page note keeps "(tilt/slide)"), else a call (2024+ Lyriq, F-Pace, 2023 E-Pace, Q6 e-tron (sources disagree), ES 500e); researched Oct 24 2026 (Mercedes EQ 413 Panorama roof, Q4 e-tron, Electrified GV70, EV6 GT-Line/GT, XC40 Recharge/EX40, i4 open). Inferred from trim only where standard (Subaru: Forester all but Base, Outback Touring/XT, Outback Limited 2025+; Q5 Premium Plus/Prestige, 2025+ Sportback, all 2026+ (corrected Oct 2026: optional on 2023–25 Premium), GV70 Select+, XC60 Plus/Ultimate, Bronco 4-door); see `config.yaml: sunroof_standard` |
| Drivetrain | **AWD is a nice-to-have, not a requirement** (user, Oct 25 2026: "Change it so that awd is a nice to have but not a requirement. Make it so that the filter you can pick between awd, rwd, and fwd"): `filters.awd_required: false` (true brings the old rule back), scored with `scoring.weights.awd: 10` (unknown 30%); the model rules that only failed RWD/FWD versions were removed (Q4 40/45, A6 e-tron RWD, sDrive, 330e/530e, i4/i5/i7 eDrive, EQB 250, EQE/EQS +, RZ 300e/350e, ES 350e, ES 300h, single-motor XC40/EX40); `listing.URL_SKIP` no longer skips 2wd/fwd/sdrive URLs; Check yourself links no longer filter Dealer Inspire to AWD; Trim guide trims that were off only for drive are on the list. A '2WD' VIN gets its axle from `criteria.two_wd_axle` (BMW/Mercedes/Cadillac/Genesis RWD; Kia/Acura/VW/Toyota/Lexus/Mazda/EQB FWD). Dashboard: **Drive** filter (AWD incl. 4WD / RWD / FWD) and a Drive column. `rescore` re-checks cars of the latest search that were ruled out only for drive (`run.revive_drive_only`; 47 came back Oct 25). Added with it: **Tiguan S** fails (no sunroof offered), and a front-wheel-drive NX is the **NX 250** (vPIC can call it '350') |
| Fuel | **No gas cars for now** (user, Oct 25 2026: "for now you can remove gas cars (still keep hybrid, previous [plug-in], and ev). But make it easy to get back if I change my mind"): `filters.fuels: [hybrid, phev, ev]` (mild hybrids = gas, so they're out too). **To bring gas back**: add `gas` to that list (or delete the line), then `python run.py rescore` (cars of the latest search come back at once via `run.revive_drive_only` / `_lifted`; tested: 91 of 92 returned) or just the next search. `criteria.fuel_fail` writes 'gas (only hybrid / plug-in hybrid / electric for now)'; `profiles.could_want` then skips gas VINs before reading their pages |
| Mild hybrids | Count as **gas** (fuel type from NHTSA vPIC ElectrificationLevel, not dealer wording) |
| Phone page | **Public** (user declined Cloudflare Access, Oct 2026: nothing sensitive), noindex; published digest omits buying context (`publish.include_buying_context: false`) |
| Dashboard | Columns include Year (sortable, newest first), Fuel and MPG (listing value, else EPA from fueleconomy.gov; PHEV = gas-only); filters (Oct 20 2026: on desktop ≥ 1100 px a sticky left sidebar `aside.filters` in collapsible sections, list in `.content`; phones unchanged) with multi-select pills (status, make, fuel, year, body, **Sunroof** and **Upgraded sound**: Yes / No / Not sure, **Seats**: Leather / Synthetic leather / Cloth / Not sure (page, else Trim guide `seats`, `seatOf`), own columns since Oct 19 2026; sound = the system named on the dealer page, else the Trim guide's `premium_audio` for the matched trim (`soundOf`/`soundCall` in the template: Yes only when a named premium system is standard; a short dealer trim name like "Premium Plus" uses every guide trim containing it, if they agree)) plus an "Only NEW" toggle; a **count line** above each list (Oct 23 2026, user asked: "Showing 80 of 160 cars" + Clear filters; `#shown-a`/`#shown-g`, and `#shown-f` next to Clear filters in the filter panel); **Dislike** button (Oct 20 2026: car stays on the page, greyed; synced via `functions/api/dislikes.js`, KV key `dis:default`) and a **Your marks** filter (Favorite / Disliked / No mark); price / miles / **Ground clearance** / **Electric range** sliders are one track with two handles each (Oct 23 2026, user: "one line instead of two": two stacked range inputs in `.track`, only the handles take touches, `fillTrack()` shades between them and keeps the low handle on top past the middle; the From–To values sit on the label line); **Ground clearance** and **Electric range** columns + sliders (`data/specs.json` via `verify/specs.py`: researched from maker spec sheets / fueleconomy.gov, first match wins, trim-specific entries first; **clearance is one figure per year/model/trim** (user, Oct 21 2026): `specs.best_clearance` = maker's figure (US, else the maker's non-US data) → dealers' spec data (parsed from the dealer page, `generic_jsonld.ground_clearance`, most common per year/make/model) → the rough config `ground_clearance_in` table, labelled 'approximate' (it's no longer stored on the listing; it used to be, and matched CX-50 as CX-5); range only for phev/ev, moving that slider hides gas cars); a **No longer available** tab listing every car that was ever on the dashboard and later sold/was removed (`status=sold`, `removed_on`); a one-time **opening animation** (compact SUV, Q5/GV70-like, drives across the top leaving tire marks that fade; skipped with Reduce Motion); **NEW** bubble (car first became available in the latest run: `new_run == max(seen_run)`); bold green **▼** when price is **$200+** below the first recorded price (`CUT_MIN`; smaller moves are estimated fees changing or real fees replacing the estimate, e.g. the $185 fee corrections of Oct 21 2026), with the latest cut and its date under the price ("▼ $1,150 on Oct 23"); a **Price cut** filter pill + a **price cuts** tile at the top (Oct 23 2026, user: "a way for me to view price cuts easily") that filter to cut cars and sort **Biggest price cut** first (`sortK = "cut"`, also in the phone Sort menu), and **Most recent price cut** (user, Oct 27 2026: `cut_on` = latest cut's date + amount; the Sort menu now shows on desktop too and follows the column headers; the sort is remembered per viewer (localStorage `sort`) and the menu is reset to the sort really in use on load: Safari restored 'Lowest price' in the menu over a list sorted by score, Oct 28 2026), and an **Original price** column (replaced the price sparkline); the **table header row stays on screen** while scrolling (JS `stickHeads()`, because the table's sideways-scroll box defeats CSS sticky); on **phones (≤ 760 px) each car is a card** (no sideways scrolling; `@media` block in `outputs.TEMPLATE`, cells labelled via `data-l`) with a **Sort** menu instead of tappable headers; **Favorites** (♥ Save on any car; the ♥ tab = Available limited to favorites, sold favorites listed above; synced between devices by the Pages Function `functions/api/favs.js` (KV namespace bound as `FAVS` in the Pages project's Settings > Bindings; one shared list, since the page has no sign-in); without sync (local file / no binding) they stay in localStorage and "copy a link with your favorites" = `#fav=VIN,…` moves them); **Check yourself** tab (`outputs.check_list`: failed dealers of brands without a working brand feed, top brands then distance, plain-words reason, per-model links to the dealer's own **certified** inventory (`_cpo_base`: certified URL on file, else Dealer Inspire `/used-vehicles/certified-pre-owned-vehicles/` + `_dFR` filters for model, year (min per model), drivetrain (spelled-out values, several spellings: user found `AWD` alone doesn't match) and `ext_color_generic` Black/Gray/Green (model + year + drivetrain + color together verified by the user on a real DI site, Oct 16 2026), Dealer.com `/certified-inventory/index.htm?search=`; otherwise just the dealer's website; **no links to brand-wide certified searches** (user asked: only each dealer's own CPO inventory); user asked for CPO-only links, Oct 2026), "Mark checked" dates synced via `functions/api/checked.js` (same FAVS KV, key `checked:default`), stale after 7 days); **map** (Oct 25 2026, user: "visualize on a map where the various cars are located to facilitate going to test drive ones close to each other": "Show on a map" button above the Cars/♥ list; Leaflet 1.9.4 from cdnjs + OpenStreetMap tiles, loaded only when opened, no API key; one pin per dealer for the cars the current filters show, number = cars, green = all match, amber = some need a call, dashed = no street address on file (city center; `outputs._places` from data/dealers.csv), ♥ = has a favorite; popup lists the cars, dealers within 8 mi, + Add to trip; the trip (viewer's localStorage `trip`) opens as a Google Maps driving route from the home ZIP; addresses + lat/lon of 10 dealers came from their own sites' JSON-LD on Oct 25 2026, 5 still approximate (Audi Beverly Hills, Audi Van Nuys, Keyes European, MB of LA, MB of Beverly Hills: sites block us)); floating **↑ back-to-top** button (appears after scrolling 600 px); **Compare** tab (tap "+ Compare" on up to 6 cars; field-by-field, ★ = best; rebuilt Oct 27 2026 (user: "more comprehensive, it's missing a lot of metrics") into sections Price & value / Match & score / The car / Features / Warranty & history / Dealer & listing (`FIELDS` entries with only a label = section heading): fees, price cut + history, % below sticker, score breakdown bars (`criteria.score_breakdown(row)` → car `score_parts`), your mark, sticker seen, engine and 'what this trim adds' from the Trim guide, MPG city/hwy, miles per year, cooled seats, spare tire, CARFAX badges, model recalls, days on the tracker; a **Performance, range & charging** section (Oct 27 2026, user: "Horsepower, clearance, electric range, charge time, ventilated seats plus anything else"): horsepower (+ Boost), torque, 0-60, electric range, battery kWh, DC fast-charge time (with its % window) and peak kW, home Level 2 kW + hours empty to full (battery / kW × 1.1), ground clearance, cargo behind the rear seats, towing, and where the specs came from; figures from `data/specs.json` `perf` (per make/model/year, `trim_regex` matched against trim + body + drive + fuel so a Q4 40 / Lyriq RWD / EQE 350+ get their own row; researched Oct 27 2026 from maker pages / press releases as quoted by spec sites; fill gaps there), horsepower falls back to the Trim guide's engine line; a row nobody has data for is hidden; 'Cooled seats' renamed 'Ventilated (cooled) seats'; each compared car has its own colour (A blue, B orange, C green, D purple, E pink, F teal: `.k0`-`.k5`) on its header and, on phones, every value line shows the car's coloured letter + short name ("B · GV70 '23") with a coloured left bar (Oct 27 2026, user: "hard to tell which is a and which is b"); selection kept in the viewer's localStorage; a "Comparing N cars · View · Clear compare" bar above the filters, and Clear compare at the top of the tab); **$ What to offer** button on every car + a Compare row (Oct 27 2026, user: "figure out what I could realistically negotiate for based on the same year/model/trim on my sold tab"): the Sold tab alone is too thin (45 cars in 2 weeks, last asking price ≠ sale price), so `outputs._market` ships every **certified** car of the same make + model family (first word) + fuel + body seen in the last 45 days whatever the rules said (`D.market`, `market_key`), listed or gone; JS `negotiate(c)`: same year + same trim (word overlap ≥ 0.5) if 3+, else same year, else ±1 year at ~6 %/year; price per mile from the cars' own prices when 5+ spread 8k+ mi (clamped 5-35¢), else 15¢; Open at = min(25th percentile, 5 % under asking), Aim for = min(median, 3 % under), never more than 12 % / 8 % under asking; talking points (cheapest comparable, cars gone and after how long, days listed, cuts, fees, EV depreciation) and the comparable list in a `<dialog id="neg">`; **Trim guide** tab (`data/trim_guide.json`: per model/year/trim what's included, seat material, year-by-year changes; hand-researched from manufacturer sources) with a **warranty comparison** (`data/warranty.json`: factory + CPO terms per brand); **Warranty** column per car = coverage left + expected end date (in-service assumed ~April of the model year; mileage end at `config.yaml: warranty.miles_per_year`), sortable |

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

- **Reading steps overlap** (Oct 23 2026, user: "this took 45 mins ... speed it up"; that run = feeds 12 min one after
  another, Mazda 9 of them; dealer sites 24 min, the last 8 on Mercedes-Benz of Encino alone; feed-car pages 6 min after).
  `run.py refresh` step 1/4 now: all brand feeds at once (`pipeline.run_brand_feeds`, one thread per feed); meanwhile a
  `pipeline.DealerPool` reads the dealer sites of every brand whose feed can't replace them (non-feed brands + Lexus/Kia
  supplement feeds), **biggest first** (`dealer_jobs` sorts by last run's "N listings read" from coverage.csv); when the
  feeds finish, dealers of brands whose feed failed are added to the same pool, and the feed cars' dealer pages are read
  alongside. **Mazda detail records are cached** 14 days (`data/cache/mazda_detail.json`; one request per car at 2-3 s was
  the 9 minutes). **URL -> VIN memory** (`data/cache/url_vins.json`): a car listed under two URLs (dealer.com `/certified/`
  and `/used/` with no VIN in the address) gets carried forward by either URL; carried rows are de-duplicated by VIN.
  Mazda's search sometimes answers "A system error has occurred" with HTTP 200 (the page cache kept it): it's
  forgotten and retried once after 10 s, else the feed fails and Mazda dealer sites are read instead.
- **Parsing is the real limit** (Oct 24 2026: a full re-read = ~2,100 listing pages; Python threads share one CPU core, and `generic_jsonld.parse_vdp` took ~1.2 s a page, so ~40 min of the 45). It now parses each page once (CARFAX badges collected before the menus are cut) and drops menus/footers with a plain tag pass (`_chrome`) instead of a soupsieve CSS selector: ~0.4 s a page, same output on 28 real pages. Runs whose rules didn't change reuse most rows and read far fewer pages.
- robots.txt is retried twice (after 5 s and 20 s) when the connection breaks (`base.Fetcher._load_robots`): on Oct 24 2026 the laptop's connection broke for ~5 min and ~30 dealers (Lexus, Kia, Audi, Alfa Glendale) were written off as 'robots.txt unreachable (SSLError)'.
- **A car whose page failed to load is not marked sold** (`run.py` `unread` -> `history.update`): on Oct 24 2026 two EQEs (Calstar W1KEG1CB4RF046886, West Covina 4JGGM1CB2PA013306) went 'sold' while still listed; restored by hand.
- **A brand feed that returns under 70% of last run's cars** (and last run had 20+) is treated as partly read: its dealers don't count as read, so its missing cars aren't marked sold (`run.py` `last_feed`; Oct 26 2026 the Volvo feed gave 50 instead of 101 and the Penske S60 7JRH60FL7RG282985, still for sale, went 'sold'; restored by hand).
- Brand feeds (Genesis, Subaru, Volvo, VW) increasingly give dealer.com redirect links (`/catcher.esl?vehicleId=`); they work, and `enrich_from_dealer_page` swaps in the page they lead to when it reads it.
- **Filling the '?' / 'Not sure' gaps (Oct 24 2026, user asked)**: makes are canonicalised to the config `models:` spelling (`run.canon_make`; 'CADILLAC' made the brand filter list Cadillac twice). **MPG**: fueleconomy.gov resets requests for `/robots.txt` (other paths answer), so under our robots rule the site is off limits and ~140 of 160 cars had no MPG on every laptop run. Its answers are now kept in the committed `data/fueleconomy.json` (any machine that gets through fills it for all), `rescore` fills missing MPG from it, and the dashboard falls back to the Trim guide's EPA `mpg` for the trim (`mpgFromGuide`, labelled 'trim guide'); EVs show '— electric'. Don't bypass the robots rule for it. **Sticker/range**: `msrp.fill` and `specs` use the VIN body type, so an 'EQE350 4MATIC' that is an SUV gets the EQE SUV row. Homepage checks retry once on a broken connection (`pipeline.homepage_status`): during the Oct 24 drop, feed dealers looked 'blocked' and their cars lost sunroof/sound/seat details from the dealer page.
- **At most 12 requests open at once** across all threads (`base._NET`, config `scrape.max_open_requests`) and every GET/POST is retried after 5 s and 15 s when the connection breaks (Oct 25 2026: on the laptop, Lexus/Subaru/Mazda/Kia/Genesis feeds and vPIC all failed with 'SSL: UNEXPECTED_EOF_WHILE_READING' within a minute, i.e. the home connection choking on many connections at once).
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
- **Bug sweep (Oct 28 2026, user asked)**: Best MPG sort put 'Not sure' first (`mpgFromGuide` wrote 'Not sure' when trims disagreed; the sorter now treats any non-number on a number column as blank, `TEXT_KEYS`); the What to offer helper wrote each car's adjusted prices onto shared `D.market` objects (now copies; `negCache` is cleared when you update a price); the top counts / tab counts now leave out cars you marked no longer available (`updateCounts`). Checked clean: every filter pill, sort, tab, Compare with 6 cars, all 122 offer dialogs, map, Mine buttons (phone + desktop, no JS errors), data (no duplicate VINs, active cars all pass the hard rules, price history matches), a cloud `refresh --brands Genesis,Subaru` (only those brands changed; data not committed).

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
