# SMB Intel CO — Colombian SMB Market Intelligence via Web Scraping

> Big Data Final Project — Knox College

**Team:** Juan Pablo Pérez Mejía & Leonardo Miani

---

## Overview

`smb-intel-co` is a scraping and analytics pipeline that identifies Colombian
small and medium businesses (SMBs) most likely to benefit from a WhatsApp-based
AI sales agent. We collect business signals from Google Maps, Instagram, and
public business directories, deduplicate and enrich the records, and produce a
unified dataset, an **AI Readiness Score** per business, and a Streamlit
dashboard for exploration.

---

## Quick Start

Clone the repository:

```bash
git clone <repo-url> smb-intel-co
cd smb-intel-co
```

Create and activate a virtual environment.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\activate
```

**macOS / Linux:**

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies and pre-commit hooks:

```bash
pip install -r requirements.txt
pre-commit install
```

Configure environment variables:

```bash
cp .env.template .env
# then fill in the required keys (Supabase, Google Maps API, etc.)
```

---

## Project Structure

```text
smb-intel-co/
├── scrapers/            # Scrapy spiders & collectors
│   ├── gmaps/           # Google Maps Places scraper
│   ├── instagram/       # Instagram business profile scraper
│   └── directories/     # Public business directory scrapers
├── data/                # Local data lake (gitignored, .gitkeep tracked)
│   ├── raw/             # Untouched scraper output
│   ├── interim/         # Deduplicated / partially processed
│   └── clean/           # Final analysis-ready datasets
├── db/                  # Database layer
│   └── migrations/      # Supabase / Postgres migrations
├── notebooks/           # Exploratory analysis (Jupyter)
├── scoring/             # AI Readiness Score logic
├── dashboard/           # Streamlit app
├── docs/                # Project documentation
├── tests/               # Pytest suite
├── utils/               # Shared helpers (logging, config, IO)
└── .github/workflows/   # CI pipelines
```

---

## Workflow Tasks

Common tasks are defined as Invoke targets in `tasks.py`.
Run `invoke --list` to see the full menu, or use any of the tasks below:

| Task | Description |
| ---- | ----------- |
| `invoke install` | Install dependencies and pre-commit hooks |
| `invoke lint` | Check code style with ruff, black, and isort |
| `invoke fmt` | Auto-format source code with black, isort, and ruff --fix |
| `invoke test` | Run pytest with coverage for utils and scrapers |
| `invoke gmaps-dry-run` | Print the H3 grid + cost estimate (no API calls) |
| `invoke gmaps-estimate` | Detailed pre-flight cost estimate with budget guard |
| `invoke gmaps-smoke` | Cheap smoke run (single zone × category, capped hexes) |
| `invoke scrape-gmaps` | Full GMaps scrape — all cities, priority<=2 zones+categories |
| `invoke scrape-instagram` | Scrape Instagram business profiles (Week 1) |
| `invoke scrape-directories` | Scrape public business directories (Week 1) |
| `invoke clean` | Remove intermediate and output files (Week 2) |
| `invoke resolve` | Entity resolution: dedupe all raw sources → `businesses_canonical.parquet` |
| `invoke score` | AI Readiness scoring → `data/clean/top_500.csv` |
| `invoke dashboard` | Launch the Streamlit dashboard |
| `invoke load --source SOURCE --path PATH` | Load a Parquet file into Supabase |
| `invoke load-gmaps` | Load both gmaps city parquets into `businesses_raw` |
| `invoke load-canonical` | Load `businesses_canonical.parquet` into Supabase |
| `invoke pipeline` | End-to-end: load gmaps → resolve → load canonical → score |

---

## Google Maps Scraper — Target Commercial Zones

The GMaps scraper does **not** scrape entire municipalities. Doing so would
spend ~$5,000 USD against the Google Places API and bury us in low-value
rural / hillside data. Instead it scrapes inside small named **commercial
target zones** (Parque 93, Zona T, El Poblado / Provenza, Laureles,
Envigado Zona Viva, Unicentro / Cedritos, etc.). These are the corridors
where SMBs are most likely to (a) have customer volume, (b) use WhatsApp /
Instagram / websites, and (c) afford a premium AI sales agent.

Each zone is filled with H3 hexagonal cells at resolution 7 (~5 km², ~1.2 km
edge). Saturated cells are adaptively subdivided to resolution 8 or 9.

### Editing zones

Edit [`scrapers/gmaps/target_zones.py`](scrapers/gmaps/target_zones.py).
Each zone has a `priority` (1, 2, 3) and an `enabled` flag. Defaults run all
priority<=2 enabled zones.

### Workflow

```bash
# 1. See what the grid covers + a cost estimate (no API calls)
invoke gmaps-dry-run

# 2. Detailed pre-flight estimate, with budget guard
invoke gmaps-estimate

# 3. Cheap smoke run before committing to the full scrape
invoke gmaps-smoke

# 4. Full production scrape — defaults: --all-cities --priority-max 2 --budget-cap-usd 275
invoke scrape-gmaps
```

### Budget controls

- Default hard stop: **USD 275**.
- Warning logs at $150, $200, $225 (each fired once).
- Pre-flight estimate aborts if mid-cost > cap unless `--force-over-budget`.
- Cost log: `logs/gmaps_cost.log`.

### Outputs

- `data/raw/gmaps/{city}_{category}.parquet` — per category × city
- `data/raw/gmaps/{city}.parquet` — deduplicated city-level
- `data/interim/gmaps_websites.parquet` — handoff for the Instagram scraper
- `data/interim/gmaps_place_categories.parquet` — every (place_id, zone, category, h3_cell) tuple

---

## Entity Resolution & AI Readiness Score

Once raw parquets exist, the scoring layer dedupes them and ranks businesses
by their fit for a WhatsApp-based AI sales agent.

```bash
# 1. Merge all data/raw/**/*.parquet into deduplicated businesses_canonical.parquet
invoke resolve                  # threshold 85 (default)
invoke resolve --dry-run        # preview without writing

# 2. Score and export top 500 leads
invoke score                    # writes data/clean/top_500.csv
invoke score --city "Medellín"  # filter to one city
invoke score --min-score 40     # only high-quality leads

# OR run the full pipeline in one shot (after the scrape is done):
invoke pipeline                 # load_gmaps → resolve → load_canonical → score
```

**Entity resolution** uses two-stage blocking — exact `(city, phone_e164)`
plus exact `(city, first_significant_token)` (skipping generic Spanish
business words like *restaurante*, *salón*, *peluquería*) — followed by
rapidfuzz `WRatio >= 85` within each block. Clusters are merged with
Union-Find and assigned a stable `master_id = uuid5(DNS, "city|name")`.

**AI Readiness Score** is a 0–100 weighted sum:

| Signal | Max points |
| ------ | ---------- |
| Has website | 15 |
| Has phone | 10 |
| Has Instagram handle | 20 |
| Instagram followers (log-scaled, full at 10k) | 15 |
| Posted in last 90 days | 10 |
| Has Instagram catalog | 10 |
| Rating (linear, full at 5★) | 10 |
| Reviews count (log-scaled, full at 500) | 10 |

---

## Stack

- **Language:** Python 3.11
- **Scraping:** Scrapy
- **Data:** Polars / Pandas, PyArrow
- **Storage:** Supabase / Postgres
- **Dashboard:** Streamlit, Plotly, Folium

---

## License

MIT — see [LICENSE](LICENSE).
