# CPO SUV Scraper & Dashboard — Build Spec

Hand this file to Claude Code. Build a scraper + dashboard that finds certified pre-owned SUVs matching the criteria below, modeled on my job-search tracker (CSV data files + newsletter-style markdown digest, verification against primary sources instead of aggregators).

---

## 1. Goal

Every run ("refresh"), the tool should:

1. Scrape the **used/certified inventory of every franchise dealer** in the brand list within 50 miles of ZIP **90039** (Los Angeles).
2. Apply the hard filters (Section 3) and score the nice-to-haves (Section 4).
3. Verify each match (VIN decode, recalls, certification type, CARFAX status).
4. Diff against the previous run (new / price change / sold).
5. Output `listings.csv`, a markdown digest, and a simple local HTML dashboard.
6. Print a **coverage report**: which dealers were scraped successfully, which failed, and why.

Never fill gaps with aggregator data. Aggregators (Edmunds, Autotrader, KBB, CarGurus, Cars.com, Capital One, CARFAX listings, iSeeCars, Westlake, NetLook) may be used **only to discover leads**; every result shown must link to the dealer's own listing page.

---

## 2. Project structure (mirror the job dashboard)

```
car-search/
  data/
    dealers.csv          # one row per dealer (see Section 6)
    listings.csv         # every listing ever seen, with first_seen / last_seen / status
    price_history.csv    # vin, date, price
    exclusions.csv       # VINs manually excluded + reason
  scrapers/
    base.py              # shared fetch, caching, rate limiting, robots.txt
    dealer_inspire.py    # platform adapter
    dealer_com.py        # platform adapter
    dealeron.py          # platform adapter
    audi_network.py      # audiusa-style "vehicleId=" pages
    generic_jsonld.py    # fallback: schema.org Vehicle JSON-LD on any page
    playwright_fallback.py
  verify/
    vin_decode.py        # NHTSA vPIC
    recalls.py           # NHTSA recalls
    certification.py     # OEM CPO detection
    carfax_badge.py      # badge parsing only (see Section 8)
  output/
    digest_YYYY-MM-DD.md
    dashboard.html
  config.yaml            # criteria from Sections 3-5
  run.py                 # `python run.py refresh`
```

---

## 3. Hard filters (exclude if any fail)

| Field | Rule |
|---|---|
| Body | SUV, **2 rows only** (exclude any third-row configuration) |
| Drivetrain | AWD or 4WD only |
| Year | 2023 or newer |
| Mileage | under 40,000 |
| Certification | **Automaker's own CPO program only**, sold by that brand's franchise dealer. Exclude dealer programs (e.g. "Galpin Certified") and cross-brand certifications (e.g. a Genesis certified under Ford Blue Advantage at a Ford dealer). Exception: Ford Bronco under Ford Blue Advantage counts; record Gold vs. Blue. |
| Price (total incl. dealer fees, before tax) | Gas-only: **≤ $35,000**. Hybrid / plug-in hybrid: **≤ ~$40,000**. Fully electric: include only if flagged as an exceptional deal (≥15% below comparable listings); otherwise exclude. |
| Sunroof | Required (sunroof / moonroof / panoramic). Bronco removable roof panels count. |
| Exterior color | Black, gray (incl. silver-gray/graphite/"Thunder", "Makalu", "Mythos", "Vik", "Onyx", "Daytona", etc.), or **dark green** (British racing green-style, e.g. Subaru "Autumn Green"). Exclude white, beige, blue, red, matte paint. |
| Interior color | Black (incl. "Obsidian", "Charcoal", "Slate Black", "Black/Black"). Exclude beige, brown, white, red. |
| Distance | Dealer within 50 miles of 90039 |
| CARFAX | Exclude if an accident is reported. If CARFAX isn't available, **keep** and mark `carfax_status = not_verified`. |

---

## 4. Nice-to-haves (score, don't filter)

| Feature | Weight |
|---|---|
| Price closer to $30,000 | high |
| Plug-in hybrid | high |
| High mpg (gas or hybrid) | medium |
| Upgraded audio (Bang & Olufsen, Lexicon, harman/kardon, Burmester, Bowers & Wilkins, Mark Levinson) | medium |
| Real leather (not leatherette/MB-Tex/SensaTec/StarTex) | low |
| Ventilated front seats | low |
| Ground clearance ≥ 8 in | low |
| Spare tire (not just inflator kit) | low |

Also compute an **estimated monthly cost**: $8,000 down, 60 months, 5.34% APR, LA sales tax ~9.75% on price, plus ~$400 government fees.

---

## 5. Models

| Brand | Models | Notes |
|---|---|---|
| Audi | Q5 (40/45 TFSI), Q5 55 TFSI e (PHEV) | Premium Plus usually has panoramic roof + B&O. Exclude Sportback? Keep, flag as "Sportback". |
| Genesis | GV70 2.5T, GV70 3.5T Sport, Electrified GV70 (EV, exceptional only) | Base 2.5T has **no sunroof**; Select package or higher required. 2024 Select may lack ventilated seats; parse features. |
| Subaru | Forester (Limited/Touring/Wilderness), Forester Hybrid, Outback (Limited/Touring/Wilderness) | Confirm moonroof on each. |
| BMW | X3 xDrive30i | Exclude sDrive (RWD). |
| Mercedes-Benz | GLC 300 4MATIC | Exclude RWD GLC 300. |
| Volkswagen | Tiguan **2025+ only** | 2018–2024 AWD Tiguans have a third row. |
| Lexus | NX 350, NX 350h, NX 450h+ (PHEV) | |
| Volvo | XC60 B5/B6 AWD, XC60 Recharge T8 (PHEV) | Exclude XC90 (3 rows). |
| Toyota | 4Runner (2-row, sunroof trims), Land Cruiser 2024+ | No other Toyota models. Exclude 4Runners with third-row option. |
| Ford | Bronco 4-door | **Not** Bronco Sport. |

**Excluded brands/models:** Mazda, all 3-row SUVs, sedans, other Toyota models.

Use the VIN decode (Section 8) to confirm year, model, drivetrain, and body before trusting the listing text.

---

## 6. Dealers (seed for `data/dealers.csv`)

Columns: `brand, dealer_name, city, homepage, platform, inventory_url, status, last_scraped, notes`

`status` = `confirmed` (seen during manual research) or `unverified` (believed to exist; confirm via the brand's official dealer locator using ZIP 90039 / 50 mi). **First task for Claude Code: run each brand's dealer locator and complete this list.** Do not invent URLs; leave blank until discovered.

### Audi
| Dealer | City | Homepage | Status |
|---|---|---|---|
| McKenna Audi | Norwalk | https://www.mckennaaudi.com (listings also on https://www.mckennacars.com) | confirmed |
| Audi Beverly Hills | Beverly Hills | https://www.audibeverlyhills.com (has `/llms.txt`) | confirmed |
| Audi Downtown LA | Los Angeles | https://www.audidtla.com | confirmed |
| Audi Calabasas | Calabasas | https://www.audicalabasas.com | confirmed |
| Audi Long Beach | Long Beach | | confirmed |
| Audi Mission Viejo | Mission Viejo (~55 mi, edge) | https://www.audimv.com | confirmed |
| Audi Pacific | Torrance | | unverified |
| Audi Santa Monica | Santa Monica | | unverified |
| Audi Valencia | Valencia | | unverified |
| Audi Pasadena | Pasadena | | unverified |
| Audi Fletcher Jones | Newport Beach | | unverified |
| Audi Brea | Brea | | unverified |
| Audi West Covina | West Covina | | unverified |
| Audi Thousand Oaks | Thousand Oaks | | unverified |

### Genesis
| Dealer | City | Homepage | Status |
|---|---|---|---|
| Norm Reeves Genesis of Cerritos | Cerritos | https://www.genesisofcerritos.com (machine-readable feed: https://www.genesisofcerritos.com/llm/inventory) | confirmed |
| Genesis of Santa Monica | Santa Monica | https://www.genesissantamonica.com | confirmed |
| Genesis of South Bay | Torrance | https://www.genesisofsouthbay.com | confirmed |
| Others | | via Genesis dealer locator | to discover |

### Subaru
| Dealer | City | Homepage | Status |
|---|---|---|---|
| Sierra Subaru | Monrovia | https://www.sierrasubaru.com | confirmed |
| DCH Subaru of Thousand Oaks | Thousand Oaks | (phone 805-372-1624) | confirmed |
| Puente Hills Subaru | City of Industry | | unverified |
| Others | | via Subaru dealer locator | to discover |

### BMW (xDrive only)
| Dealer | City | Homepage | Status |
|---|---|---|---|
| Pacific BMW | Glendale | | confirmed |
| BMW of Beverly Hills | Beverly Hills | https://www.bmwofbeverlyhills.com | confirmed |
| BMW Santa Monica | Santa Monica | https://www.bmwsantamonica.com | confirmed |
| BMW of Downtown LA | Los Angeles | | confirmed |
| Valencia BMW | Valencia | https://www.valenciabmw.com | confirmed |
| Bob Smith BMW | Calabasas | | confirmed |
| South Bay BMW | Torrance | | confirmed |
| Century West BMW | North Hollywood | | unverified |
| BMW of Sherman Oaks | Sherman Oaks | | unverified |
| Shelly BMW | Buena Park | | unverified |
| Long Beach BMW | Long Beach | | unverified |
| BMW of Monrovia | Monrovia | | unverified |

### Mercedes-Benz
| Dealer | City | Homepage | Status |
|---|---|---|---|
| Keyes Mercedes-Benz | Van Nuys | https://www.keyesmercedes.com | confirmed |
| Calstar Motors | Glendale | | confirmed |
| Mercedes-Benz of Beverly Hills | Beverly Hills | | confirmed |
| Mercedes-Benz of Ontario | Ontario | https://www.mbontario.com | confirmed |
| Mercedes-Benz of Pasadena | Pasadena | | unverified |
| Mercedes-Benz of Long Beach | Long Beach | | unverified |
| Mercedes-Benz of Valencia | Valencia | | unverified |

### Volkswagen (Tiguan 2025+ only)
| Dealer | City | Homepage | Status |
|---|---|---|---|
| McKenna Volkswagen | Cerritos | https://www.mckennacars.com | confirmed |
| Others | | via VW dealer locator | to discover |

### Lexus
| Dealer | City | Homepage | Status |
|---|---|---|---|
| Lexus of Glendale | Glendale | | confirmed |
| Lexus Santa Monica | Santa Monica | | confirmed |
| South Bay Lexus | Torrance | | confirmed |
| Longo Lexus | El Monte | | unverified |
| Lexus of Cerritos | Cerritos | | unverified |
| Lexus of Pasadena | Pasadena | | unverified |
| Lexus of Woodland Hills | Woodland Hills | | unverified |

### Volvo
| Dealer | City | Homepage | Status |
|---|---|---|---|
| Volvo Cars Culver City | Culver City | | confirmed |
| Volvo Cars Pasadena (Rusnak) | Pasadena | | confirmed |
| Volvo Cars Santa Monica | Santa Monica | | confirmed |
| Volvo Cars Thousand Oaks | Thousand Oaks | | confirmed |
| Rusnak Volvo Cars Westlake | Westlake Village | | confirmed |
| Volvo Cars South Bay | Torrance area | | confirmed |
| Volvo Cars City of Industry | City of Industry | | confirmed |
| Volvo Cars Ontario | Ontario | | confirmed |
| Volvo Cars Tustin | Tustin | | confirmed |

### Toyota (4Runner / Land Cruiser only)
| Dealer | City | Homepage | Status |
|---|---|---|---|
| Longo Toyota | El Monte | https://www.longotoyota.com | confirmed |
| Toyota of Glendale | Glendale | | unverified |
| Toyota of Hollywood | Los Angeles | | unverified |
| Toyota Santa Monica | Santa Monica | | unverified |
| Toyota of Downtown LA | Los Angeles | | unverified |
| Toyota of Sherman Oaks | Sherman Oaks | | unverified |

### Ford (Bronco only)
| Dealer | City | Homepage | Status |
|---|---|---|---|
| Galpin Ford | North Hills | https://www.galpinford.com | confirmed |
| AutoNation Ford Valencia | Valencia | | confirmed |
| Others | | via Ford dealer locator | to discover |

---

## 7. Scraping strategy

Most dealer sites run on a handful of platforms. Build one adapter per platform, detect the platform per dealer, and store it in `dealers.csv`.

1. **Machine-readable feeds first.** Check for `/llms.txt` and `/llm/inventory` (Dealer Inspire sites, e.g. Genesis of Cerritos, Audi Beverly Hills). Follow pagination (`?limit=100&page=N`) and filters (`bodytype=SUVs`, `year_min=2023`).
2. **Sitemaps.** Parse `/sitemap.xml` for vehicle detail page (VDP) URLs containing a VIN.
3. **JSON-LD.** Most VDPs embed `schema.org/Vehicle` (`vehicleIdentificationNumber`, `color`, `vehicleInteriorColor`, `driveWheelConfiguration`, `mileageFromOdometer`, `offers.price`). Prefer this over HTML scraping.
4. **Platform JSON endpoints** (Dealer.com, DealerOn, etc.) where the site loads inventory via XHR. Inspect network calls in Playwright once, then call the endpoint directly.
5. **Playwright fallback** for JavaScript-only sites.
6. **Listing state:** a VDP that redirects to the general inventory page = **sold/removed**. Record it.
7. Be polite: respect `robots.txt`, 1 request / 2–3 sec per domain, cache responses for 6 hours, identify with a clear User-Agent.

Parse from each VDP: VIN, stock #, year, make, model, trim, packages, price breakdown (price, doc fee, filing fee, smog/emissions fee, total), mileage, exterior and interior color, drivetrain, fuel type, mpg, features list (sunroof, audio, seats, spare tire), certification text, CARFAX badge type and link, dealer location (some groups list cars at a sister store).

---

## 8. Verification

| Check | Source | Rule |
|---|---|---|
| VIN decode | NHTSA vPIC: `https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{VIN}?format=json` | Confirm model year, make, model, drivetrain, body class. Flag mismatches with the listing. |
| Recalls | NHTSA recalls API: `https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&modelYear={year}` (VIN-specific check for the user: https://www.nhtsa.gov/recalls) | List recall campaigns for the model/year; flag "confirm completed" on each match. |
| Certification | Listing text + dealer franchise | Must match the brand's own CPO program and be sold by that brand's franchise dealer. Store the warranty terms quoted on the page. |
| CARFAX | Dealer page badge only | Do **not** scrape carfax.com. Parse badge images/text (e.g. `1own`, `1own_great`, "Clean CARFAX", "No Accidents"). Mark `clean` only if the listing explicitly says no accidents; mark `accident` if it says so; otherwise `not_verified`. |

---

## 9. Output

### `listings.csv` columns
`vin, status (active/sold/excluded), first_seen, last_seen, dealer, dealer_url, listing_url, year, make, model, trim, packages, fuel_type, price_total, price_history, mileage, ext_color, int_color, drivetrain, sunroof, audio, leather, ventilated_seats, ground_clearance_in, spare_tire, cpo_program, cpo_warranty_terms, carfax_status, recall_flags, est_monthly_cost, score, fail_reasons`

### Digest (`output/digest_YYYY-MM-DD.md`), formatted for pasting into Apple Notes
Sections, in order:
1. **Coverage report** — dealers scraped / failed / skipped, with reasons.
2. **✅ Meets all criteria** — sorted by score. Each line: linked title (dealer listing URL), VIN, price, miles, colors, key features, CARFAX status, est. monthly cost.
3. **🆕 New since last run**
4. **💲 Price changes**
5. **⚠️ Needs a call** — passes everything except fields the page didn't show (e.g. interior color, sunroof).
6. **❌ Removed / sold / newly excluded** — with reason.

### Dashboard (`output/dashboard.html`)
Single static HTML file: sortable/filterable table of active matches, price-history sparkline per VIN, links to dealer pages, coverage summary at the top. Light/dark mode.

---

## 10. Seed data (current state of the search)

### Current leaders
| Car | Dealer | VIN | Price | Miles | Link |
|---|---|---|---|---|---|
| 2023 Audi Q5 Premium Plus (gray/black, B&O, pano roof) | McKenna Audi | WA1BBAFY4P2169050 | $32,113 | 23,249 | https://www.mckennacars.com/viewdetails/cpo/wa1bbafy4p2169050/2023-audi-q5-sport-utility |
| 2024 Genesis GV70 2.5T Select (black/black, pano roof) | Genesis of Cerritos | 5NMMADTB7RH006751 | $35,179 | 25,874 | https://www.genesisofcerritos.com/inventory/certified-used-2024-genesis-gv70-2-5t-awd-sport-utility-5nmmadtb7rh006751/ |

### Needs verification
| Car | Dealer | VIN | Price | Open questions |
|---|---|---|---|---|
| 2026 Subaru Forester Limited Hybrid | Sierra Subaru | 4S4SLSR71T3062758 | $35,450 | ext/int color, CARFAX |
| 2025 Subaru Forester Limited (Autumn Green) | DCH Subaru of Thousand Oaks | not listed | $34,599 | VIN, interior, sunroof, miles |
| 2025 Subaru Outback Limited (Autumn Green / Slate Black leather) | DCH Subaru of Thousand Oaks | 4S4BTANC0S3127191 | $34,564 | may be sold |
| 2024 Audi Q5 55 TFSI e Premium Plus | McKenna Audi | WA1E2AFY4R2018984 | $40,076 | ext color |

### Exclusions (`exclusions.csv`)
| VIN | Reason |
|---|---|
| KMUMADTB8PU138629 | 2023 GV70 at Galpin — dealer certification only ("Galpin Certified") |
| 5NMMADTB9RH000756 | 2024 GV70 base at Genesis of Cerritos — no sunroof |
| 5NMMCET16PH001030 | 2023 Electrified GV70 at Genesis of Cerritos — sold |
| WA1G2AFY3R2069532 | 2024 Q5 TFSI e at Audi Mission Viejo — white with beige interior |
| WA1BBAFY9P2155239 | 2023 Q5 at Audi Calabasas — white with beige interior |
| 1V2BR2CA7RC502755 | 2024 VW Atlas at McKenna VW — third row |

---

## 11. Buying context (for the digest header)

- $8,000 down; Bank of America pre-approval at 5.34% APR (30-day validity)
- Earliest pickup: November 14
- Insurance: AAA (bundled with renters)
- Gas-only cars capped at $35,000

---

## 12. First tasks for Claude Code

1. Scaffold the project structure in Section 2 and `config.yaml` from Sections 3–5.
2. Complete `dealers.csv` using each brand's official dealer locator (ZIP 90039, 50 mi). Record homepage and detect platform.
3. Build the Dealer Inspire adapter first (test on https://www.genesisofcerritos.com/llm/inventory), then the JSON-LD fallback, then Playwright.
4. Implement verification (Section 8) and the digest (Section 9).
5. Run once, then show me the coverage report before building the dashboard.

**Acceptance criteria:** every result links to a dealer page, includes a VIN, shows CARFAX status, and the coverage report lists every dealer in `dealers.csv` with a success/failure reason.
