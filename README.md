# SMB Intel CO — Colombian SMB Market Intelligence

> **Big Data Final Project — Knox College**
> Juan Pablo Pérez Mejía & Leonardo Miani

A scraping and analytics pipeline that identifies Colombian small and medium businesses (SMBs) most likely to benefit from a WhatsApp-based AI sales agent. Data covers premium commercial zones in **Medellín** and **Bogotá**.

---

## Demo mode — no API keys required

The repo ships with a pre-built sample of **500 scored businesses** so you can run the dashboard immediately without any credentials.

```bash
git clone <repo-url> smb-intel-co
cd smb-intel-co

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
invoke dashboard
# → opens http://localhost:8501
```

The dashboard automatically detects `data/demo/sample_500.parquet` and loads it. No `.env` file, no Supabase account, no Google Maps key needed.

---

## What the pipeline produces

| Output | Location | Description |
|---|---|---|
| Raw business records | `data/raw/gmaps/`, `data/raw/instagram/` | One row per source per business |
| Deduplicated canonical entities | `data/clean/businesses_canonical.parquet` | 3,387 unique businesses after entity resolution |
| Scored dataset | `data/clean/scored.parquet` | Every canonical business with AI Readiness Score + feature breakdown |
| Top 500 leads | `data/clean/top_500.csv` | Sorted CSV export |
| Demo sample | `data/demo/sample_500.parquet` | Stratified 500-row sample committed to the repo |

**Final numbers (full run):**
- **5,286** raw records across Google Maps + Instagram
- **3,387** canonical businesses after deduplication (815 cross-source merges)
- Score range: **19 – 82** (mean 40.1)
- Cities: Medellín (1,529) · Bogotá (1,858)

---

## Project structure

```
smb-intel-co/
├── scrapers/
│   ├── gmaps/             # Google Maps Places API scraper (H3 grid)
│   ├── instagram/         # Instagram public profile scraper (instaloader)
│   └── directories/       # Scrapy spiders for Páginas Amarillas & Mercado Libre
│
├── scoring/
│   ├── entity_resolution.py   # Step 2: deduplicate + assign master_id
│   ├── features.py            # Step 3: compute AI Readiness Score
│   ├── weights.yaml           # Feature weights (editable)
│   ├── vertical_weights.yaml  # Per-category multipliers
│   └── geographic_weights.yaml # Per-neighbourhood multipliers
│
├── dashboard/
│   ├── app.py             # Overview page (entry point)
│   ├── lib/
│   │   ├── data.py        # Cached data loader (parquet → pandas)
│   │   └── filters.py     # Sidebar filter widgets
│   └── pages/
│       ├── 1_Business_Table.py
│       ├── 2_Map_View.py
│       └── 3_Top_500.py
│
├── utils/
│   ├── models.py          # Pydantic v2 schema (BusinessRaw, BusinessCanonical)
│   ├── load_to_supabase.py # CLI: Parquet → Supabase upsert
│   └── supabase_client.py
│
├── db/migrations/         # SQL migrations for Supabase / Postgres
├── docs/                  # scoring.md, schema.md, PROJECT_REPORT.md
├── tests/                 # Pytest suite
├── tasks.py               # Invoke task runner
├── .env.template          # Environment variable reference
└── data/
    └── demo/
        └── sample_500.parquet  # Pre-built demo dataset (committed)
```

---

## Full setup (to re-run the pipeline)

### 1. Prerequisites

- Python 3.11+
- A Google Maps API key with **Places API** enabled
- A Supabase project (free tier works)

### 2. Install

```bash
python -m venv .venv
# activate (see Demo section above)
pip install -r requirements.txt
pre-commit install
```

### 3. Configure environment variables

```bash
cp .env.template .env
```

Edit `.env`:

```env
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<service_role key>
GOOGLE_MAPS_API_KEY=<your key>

# Optional — leave blank to scrape Instagram anonymously
INSTAGRAM_USERNAME=
INSTAGRAM_PASSWORD=

LOG_LEVEL=INFO
```

### 4. Create Supabase tables

```bash
# Run the migration against your Supabase project
psql "$SUPABASE_URL" -f db/migrations/001_create_schema.sql
```

---

## Running the pipeline step by step

All tasks are defined in `tasks.py` and run via `invoke`. Run `invoke --list` to see every available command.

### Step 1 — Scrape Google Maps

```bash
invoke gmaps-dry-run          # preview H3 grid + cost estimate (free)
invoke gmaps-estimate         # detailed cost breakdown (free)
invoke gmaps-smoke            # cheap smoke test: 1 city × 1 category × 5 hexes
invoke scrape-gmaps           # full run — all cities, priority ≤ 2 zones
```

The scraper targets **named commercial zones only** (not entire cities) to cap Google Places API spend. Default hard stop: **USD 275**. Actual cost for our full run: **USD 92**.

Outputs:
- `data/raw/gmaps/{city}_{category}.parquet` — per-category files
- `data/raw/gmaps/{city}.parquet` — deduplicated city-level file
- `data/interim/gmaps_websites.parquet` — Instagram handle handoff

### Step 2 — Scrape Instagram

```bash
invoke scrape-instagram       # reads handles from gmaps_websites.parquet
invoke scrape-instagram --dry-run   # just count seeds, don't scrape
invoke scrape-instagram --seed seeds.csv   # manual CSV with columns: handle, city
```

Throttled to 5 seconds/request with automatic 15-minute backoff on rate limits. Checkpoint at `data/interim/ig_checkpoint.json` — safe to interrupt and resume.

Output: `data/raw/instagram/profiles.parquet`

### Step 3 — Entity resolution

```bash
invoke resolve                # merge all sources → businesses_canonical.parquet
invoke resolve --threshold 80 # looser fuzzy match
invoke resolve --dry-run      # preview cluster stats without writing
```

Output: `data/clean/businesses_canonical.parquet`

### Step 4 — Score

```bash
invoke score                  # top 500 all cities
invoke score --city "Medellín"
invoke score --min-score 40   # only high-affinity businesses
invoke score --top-n 200
```

Outputs: `data/clean/scored.parquet` + `data/clean/top_500.csv`

### Step 5 — Load to Supabase

```bash
invoke load-gmaps             # load raw gmaps records
invoke load-canonical         # load canonical entities
```

### One-shot pipeline (after scraping is done)

```bash
invoke pipeline               # load gmaps → resolve → load canonical → score
invoke pipeline --dry-run     # validate everything, no DB writes
```

---

## Dashboard

```bash
invoke dashboard
# → http://localhost:8501
```

The dashboard reads data in this priority order:

1. `data/clean/scored.parquet` — full pipeline output (richest: has per-feature scores)
2. `data/demo/sample_500.parquet` — committed demo sample (no setup required)
3. Supabase live query — if `.env` credentials are present
4. Empty frame with error message

### Pages

#### Overview
KPI cards: total businesses, average AI Readiness Score, top vertical, top neighbourhood. Score distribution histogram, businesses-by-vertical bar chart, average score by vertical.

#### Business Table
Searchable, sortable table of all businesses matching the current sidebar filters. One-click **CSV export** of the visible rows.

#### Map View
Interactive Folium/Leaflet map with score-coloured circle markers:
- Red → high score (≥ 60)
- Orange → medium (40–60)
- Blue → low (< 40)

Markers are clustered for performance (MarkerCluster). Click any marker for name, score, category, neighbourhood, phone, and Instagram link.

#### Top 500
Pre-sorted ranking table. One-click download of the full top-500 as CSV.

### Sidebar filters (shared across all pages)

| Filter | Type |
|---|---|
| City | Multi-select |
| Vertical / category | Multi-select |
| AI Readiness Score range | Slider |
| Has WhatsApp number | Checkbox |
| Has Instagram | Checkbox |
| Has website | Checkbox |
| Neighbourhood | Multi-select |
| Free-text search | Text input (name, address, bio) |

---

## AI Readiness Score

A single **0–100** number per business estimating fit for a WhatsApp-based AI sales agent. It is **not** a quality rating — a great restaurant with no digital presence scores lower than a mid-tier clothing store with 50k Instagram followers.

### Features and weights

| Feature | Signal | Weight | Max pts |
|---|---|---|---|
| `whatsapp_signal` | Explicit wa.me link = 1.0 · any phone = 0.5 · none = 0 | 20% | 20 |
| `vertical_weight` | Category lookup (clothing/beauty/restaurant = 1.0, auto repair = 0.5) | 20% | 20 |
| `instagram_reach` | `log1p(followers) / log1p(50,000)`, capped at 1.0 | 15% | 15 |
| `instagram_activity` | 1.0 if posted in last 7 days, linear decay to 0 at 180 days | 15% | 15 |
| `catalog_signal` | Instagram catalog / tienda / linktree detected in bio | 10% | 10 |
| `review_volume` | `log1p(reviews) / log1p(1,000)`, capped at 1.0 | 10% | 10 |
| `geographic_weight` | Neighbourhood lookup (Parque 93, El Poblado = 1.0; others 0.6–0.95) | 10% | 10 |

**Formula:** `score = (Σ feature_i × weight_i) × 100`

Weights are in [`scoring/weights.yaml`](scoring/weights.yaml) and can be edited without touching code.

### Score interpretation

| Range | Interpretation |
|---|---|
| 70–100 | Strong fit — Instagram-native brand, active posting, chat-driven vertical |
| 50–69 | Good fit — solid digital presence, reachable |
| 35–49 | Average — typical GMaps-only business |
| < 35 | Weak fit — minimal digital signals |

### Note on Instagram-only businesses

487 businesses were discovered via Instagram but never appeared in Google Maps. These have `rating=None`, `neighborhood=None`, `phone=None` — but can still score 70+ if their Instagram signals are strong. They require **Instagram DM outreach** rather than direct WhatsApp contact.

---

## Data sources

| Source | Records | Status |
|---|---|---|
| Google Maps Places API | 4,799 raw → 2,900 canonical reps | Done |
| Instagram (public profiles) | 487 canonical entities | Done |
| Páginas Amarillas | — | Deferred — anti-scraping blocks |
| Mercado Libre | — | Deferred — product listings, not business profiles |

---

## Entity resolution

The deduplication algorithm runs in two stages:

**Blocking** — group candidates by:
1. Exact `(city, phone_e164)` match
2. Exact `(city, first_significant_token)` — skipping generic Spanish words (*restaurante*, *salón*, *peluquería*, etc.)

**Fuzzy matching** — within each block, compute `rapidfuzz.WRatio` on `name_normalized`. Pairs scoring ≥ 85 are merged.

**Clustering** — Union-Find on matched pairs. Each cluster gets a stable `master_id = uuid5(DNS, "city|canonical_name")`.

Results from our run:
- 5,286 raw records → 3,387 canonical entities
- 815 cross-source merges (gmaps ↔ Instagram)
- 65% join rate on handles that appeared in both sources

---

## Target commercial zones

The GMaps scraper does **not** scrape entire cities. It uses 27 named commercial zones across Medellín and Bogotá, filled with H3 hexagonal cells at resolution 7 (~5 km²). This cut estimated API spend from **USD 4,830 → USD 92** (98% reduction).

**Medellín zones:** El Poblado/Provenza/Lleras, Ciudad del Río, Laureles, Estadio/Los Colores, Envigado Zona Viva, Sabaneta/Parque Mayorca, Belén Rosales, Itagüí Commercial, Rionegro/Llanogrande

**Bogotá zones:** Parque 93/Chico/Virrey, Zona T/Andino/El Retiro, Rosales/Nogal, Usaquén/Santa Bárbara, Unicentro/Cedritos, Chapinero Alto/Zona G, Quinta Camacho/Chapinero Central, Salitre/Ciudad Empresarial, La Castellana/Pasadena, Colina Campestre/Parque La Colina, Modelia Commercial, Fontibón Commercial, Teusaquillo/Parkway

---

## Running tests

```bash
invoke test
# or directly:
pytest -v --cov=utils --cov=scrapers
```

The test suite covers Pydantic model validation, entity resolution logic, scraper normalisation, and the Supabase loader.

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Scraping | instaloader, googlemaps, Scrapy |
| Data processing | Polars, Pandas, PyArrow |
| Fuzzy matching | rapidfuzz |
| Validation | Pydantic v2 |
| Storage | Supabase (Postgres) |
| Dashboard | Streamlit, Plotly, Folium |
| Task runner | Invoke |
| CI | GitHub Actions (ruff, black, isort, pytest) |

---

## Streamlit Cloud deployment

Copy `.streamlit/secrets.toml.template` → `.streamlit/secrets.toml`:

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_KEY = "your-service-role-key"
```

The `secrets.toml` file is gitignored. The dashboard falls back to the demo dataset if no credentials are present, so Streamlit Cloud deployment works without a Supabase connection.

---

## Full project report

See [`docs/PROJECT_REPORT.md`](docs/PROJECT_REPORT.md) for a detailed analysis including plan vs. reality comparison, entity resolution results, score distribution analysis, limitations, and lessons learned.

---

## License

MIT — see [LICENSE](LICENSE).
