# CPO SUV Finder

Finds certified pre-owned, 2-row, AWD/4WD SUVs at franchise dealers near ZIP 90039 that match
the criteria in `config.yaml` (originally `car-scraper-spec.md`). It produces a newsletter-style
digest, CSVs and a dashboard, and publishes them to a private page for viewing on a phone.
Every result links to the dealer's own listing page and includes the VIN.

- **Handoff / current state for a new Claude session:** [CLAUDE.md](CLAUDE.md)
- **User's step-by-step setup (Windows laptop + phone page):** [SETUP-WINDOWS.md](SETUP-WINDOWS.md)

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
python run.py refresh                       # the whole search (~20-40 min from home)
python run.py refresh --brands Audi,Subaru  # some brands only
python run.py refresh --dealers McKenna     # dealers whose name contains the text
python run.py refresh --workers 8 --no-enrich
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
2. **Dealer sites** (`core/pipeline.py`, 8 in parallel, polite per-domain throttle):
   homepage check → discovery by platform → fetch each candidate listing page → parse.
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
   `data/price_history.csv`. A car is marked sold only if its dealer (or brand feed) was read
   successfully this run, so partial runs never mark blocked dealers' cars as sold.
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
| `config.yaml` | Criteria, price caps + cushion, colors, trims with standard sunroof, scoring, finance, publish options |
| `data/dealers.csv` | 204 dealers ≤ 60 mi: brand, homepage, platform, distance, source (brand locator / web research) |
| `data/dealers_manual.csv` | Researched dealers for brands whose locators block cloud IPs (Audi, BMW, Mercedes, Ford, Volvo) |
| `data/locator_raw/` | Raw brand-locator responses + geocode cache |
| `data/listings.csv` | Every listing ever seen: status (active/sold/excluded), first/last seen, all fields, MPG, fail reasons, needs_call |
| `data/price_history.csv` | VIN, date, price |
| `data/exclusions.csv` | VINs excluded by hand (VIN, reason) |
| `data/coverage.csv` | Last run: every source, success/failed/skipped and why |
| `output/digest_<date>.md` | Digest: coverage, matches, new, price changes, needs a call, removed |
| `output/dashboard.html` | Sortable table, multi-select filters, price sparklines, fuel/MPG, monthly cost, light/dark |
| `output/dealers.html` | Dealer list page (`python -m tools.dealer_page`) |
| `site/` | Built for publishing (gitignored) |
| `tools/` | `dealer_locator.py`, `verify_dealer_sites.py`, `dealer_page.py`, `diagnose.py`, `build_site.py` |
| `.github/workflows/publish.yml` | Publish to Cloudflare Pages (needs repo secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`) |
