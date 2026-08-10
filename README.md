# Atrium Portfolio Map + SEO Property Pages

Rebuilds the search footprint atriummanagement.com used to have — without
re-creating the problem that came with it.

## The problem

The old site kept a live page for every listing Atrium ever had, including
long-leased ones. Search loved it. Prospects kept applying to homes rented years
ago. meetatrium.com dropped the practice and lost the footprint with it.

## What this does

One page per property Atrium **actually manages**, showing that property's most
recent advertised listing. If the unit isn't available the page says **LEASED**,
has **no apply button anywhere in the DOM**, declares itself `SoldOut` in
structured data, and leads with what *is* available nearby. Search engines get a
real page; prospects get pointed at real inventory.

Plus a portfolio map widget for Squarespace — same chrome as the residential
listings widget, but showing everything managed, not just what's vacant.

## Where the data comes from

AppFolio **Data API v0** `listings` is the only place the archive exists. It
returns **6,262 listings back to 2016** with full marketing copy and ~19 photos
each, and every photo URL still resolves (spot-checked 2016 → 2026). The public
`/listings` feed only carries today's ~517.

| Signal | Source |
|---|---|
| Leased vs available | `PostedToWebsite` + `AcceptingApplications` |
| Churn (ex-clients) | `properties.ManagementEndDate` / `HiddenAt` |
| Unit counts | `units.PropertyId` |
| Coordinates | live feed → US Census batch geocoder → Nominatim |

**1,817 archived listings belong to properties Atrium no longer manages.** Those
are excluded — publishing them would be doing SEO for an ex-client's house.

## Page architecture

| Layer | Count | URL |
|---|---|---|
| Single-family homes | ~578 | `/homes/<street>-<city>/` |
| MF community pages | ~104 | `/communities/<name>-<city>/` |
| MF floor plans | ~528 | `/communities/<name>-<city>/<plan>/` |
| City hubs | ~34 | `/rentals/<city>-<state>/` |

**Not one page per unit.** 9,245 units would mean ~8,300 near-identical
apartment pages (same address, photos, copy, rent) — the doorway-page pattern
Google demotes, at a scale that can suppress the whole domain. Floor plans are
the honest granularity for multi-family.

## Fair Housing sanitizer

The archive spans ten years and many authors. A scan of all 6,262 descriptions
found:

| | Count |
|---|---|
| Phone numbers / staff emails in body text | 3,122 |
| `AVAILABLE NOW!!!` on long-leased units | 1,254 |
| School districts / "zoned for…" (steering risk) | 1,086 |
| Familial-status language ("perfect for family living") | 235 |

`compliance.py` runs on every description before it reaches a page.

- **HARD** (protected-class language) — sentence dropped, listing written to
  `review/flagged.csv` for a human.
- **SOFT** (dead phones, stale urgency) — whole sentence dropped when it's pure
  call-to-action, otherwise scrubbed inline.

Measured across the real corpus: **94% of text retained** (median), 3 of 5,738
descriptions reduced to unusable. Pages still build when something is flagged, so
one bad 2017 description can't block the site — but nothing ships unreviewed.

> `review/flagged.csv` needs a human pass before this goes public. That's the one
> task the pipeline can't do for you.

## Hosting — this is the decision that decides whether the SEO works

A Squarespace **iframe earns meetatrium.com nothing**. Google indexes iframe
content against the *source* URL. The ranking comes from these pages being
crawlable HTML, and from *where they live*:

- `portfolio.meetatrium.com/...` — works today, but Google treats a subdomain as
  substantially its own site. Starts from zero authority.
- `meetatrium.com/homes/...` — inherits every backlink the brand domain has.
  **This is the one that recovers the old site's ranking.**

`worker.js` is a Cloudflare Worker that serves our paths from the static origin
and passes everything else through to Squarespace untouched. Setup steps are in
its header comment. Then set `PORTFOLIO_BASE_URL=https://meetatrium.com` and
rebuild — canonicals, `og:url` and the sitemap all follow.

Nothing else changes: internal links are root-relative.

## Usage

```bash
python3 build.py              # incremental, uses cached API pulls
python3 build.py --refresh    # re-pull everything from AppFolio
python3 build.py --offline    # rebuild pages from cache, no network
python3 build.py --limit 50   # small slice while iterating
```

Output lands in `site/`: pages, `portfolio.json`, `sitemap.xml`, `robots.txt`.

Credentials are read from `atrium_chatbot/.env` / `atrium_intranet/.env`, or from
`DATABASE_CLIENT_ID` / `DATABASE_CLIENT_SECRET` / `DEVELOPER_ID` in the
environment (how the GitHub Action supplies them).

## Squarespace embed

Host `site/`, then paste everything between `WIDGET START` and `WIDGET END` in
`map.html` into a Code Block (Core plan or higher, "Display Source" off). Set
`DATA_URL` and `PAGE_BASE` in the CONFIG block first.

The map needs no API key — Leaflet + CARTO tiles, with dependency-free grid
clustering so ~980 pins stay responsive.

## Gotchas worth knowing

- **`X-AppFolio-Developer-ID` is case-sensitive at the gateway.** `urllib`
  lowercases custom headers and gets `Required header missing`. Use `requests`.
- **v0 list GETs 400 without a filter** — always pass `filters[LastUpdatedAtFrom]`.
- **`listings.PropertyId` is null on ~20% of rows** — fall back to matching on
  `Address1` + `Zip`.
- **Geocoding and rendering must walk the same ordered property list.** They
  didn't at first, and `--limit` silently geocoded a different 40 properties than
  it rendered — 3 pins on the map instead of 38. `select_pids()` is now the single
  source of that ordering.
- **A sticky map pane measures 0×0 until layout settles** — `invalidateSize()`
  before `fitBounds` or the pins render off-canvas.
- **The refresh Action needs `permissions: contents: write`** and repo
  `default_workflow_permissions=write`, or the build succeeds and the push is
  denied.
