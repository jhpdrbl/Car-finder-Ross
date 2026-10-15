# CPO SUV Finder

Finds certified pre-owned SUVs at franchise dealers within 50 miles of 90039 that
match the criteria in `car-scraper-spec.md`, and produces a digest, CSVs and a
dashboard. Every result links to the dealer's own listing page and includes the VIN.

**Windows setup and phone access:** see [SETUP-WINDOWS.md](SETUP-WINDOWS.md).

The search runs on a home computer (dealer sites block cloud servers). After a run, the
results are pushed to GitHub, and `.github/workflows/publish.yml` publishes the dashboard
and digest to Cloudflare Pages (`tools/build_site.py` builds the site, leaving out the
buying-context lines).

```
python run.py refresh                 # the whole search
python run.py refresh --brands Audi   # some brands only
python run.py diagnose --brand Audi   # report on how dealer sites are built
python run.py dealers                 # rebuild data/dealers.csv from the brand locators
```

## How it finds cars

| Source | Used for |
|---|---|
| genesis.com and subaru.com certified-inventory searches | All Genesis and Subaru dealers (official brand sites; each car links to the dealer's own page) |
| Dealer sitemaps | Listing pages on any platform |
| Dealer.com search pages | Dealer.com sites |
| DealerOn search pages | DealerOn sites |
| `/llm/inventory` | Dealer Inspire sites |
| Audi dealer platform (sitemap → inventory pages → browser) | Audi dealers |
| Headless browser (Playwright, optional) | JavaScript-only sites |

Each listing page is parsed from schema.org JSON-LD plus the page text, then
verified with NHTSA's VIN decoder (year, model, drivetrain, body, hybrid/PHEV/EV)
and NHTSA recall campaigns.

## Rules it follows

- Never uses aggregator data (Cars.com, CarGurus, KBB, Edmunds, Autotrader, CARFAX
  listings...); those domains are blocked in `scrapers/base.py`.
- Never fetches carfax.com; CARFAX status comes from the dealer page's badge only.
- Respects robots.txt, waits 2–3 s between requests to each site, caches pages for
  6 hours, and identifies itself with a clear User-Agent.
- Doesn't try to get past bot protection; blocked sites are reported in the coverage report.

## Files

| Path | What |
|---|---|
| `config.yaml` | Criteria, price caps, colors, scoring weights, finance |
| `data/dealers.csv` | Dealers (brand locators + research), platform, distance |
| `data/listings.csv` | Every listing ever seen, status, first/last seen, fail reasons |
| `data/price_history.csv` | VIN, date, price |
| `data/exclusions.csv` | VINs you excluded by hand |
| `data/coverage.csv` | Last run: each dealer, success/failed/skipped and why |
| `output/digest_<date>.md` | Newsletter-style digest for Apple Notes |
| `output/dashboard.html` | Sortable/filterable dashboard |
