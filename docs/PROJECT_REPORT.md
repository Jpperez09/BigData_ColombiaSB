# SMB Intel CO — Final Project Report

> **Big Data — Knox College, DIS Spring 2026**
> **Team:** Juan Pablo Pérez Mejía & Leonardo Miani
> **Repository:** `Jpperez09/BigData_ColombiaSB`
> **Report date:** 2026-05-12

---

## 1. Executive Summary

`SMB Intel CO` is an end-to-end big-data pipeline that identifies the Colombian
small and medium businesses (SMBs) most likely to benefit from a **WhatsApp-based
AI sales agent**. The system scrapes business signals from public sources,
deduplicates them with entity resolution, scores them with a 7-feature AI
Readiness Score, persists everything to a cloud Postgres warehouse, and exposes
the results through an interactive Streamlit dashboard.

**Final numbers:**

| Metric | Value |
| --- | --- |
| Businesses scraped (raw) | **5,286** |
| Unique businesses after entity resolution | **3,387** |
| Businesses with full Instagram metrics | **387** |
| Top 500 lead score range | **46.7 – 82.0** |
| Google Maps API spend | **USD 92** (vs $4,830 if scraping whole cities) |
| Cost reduction vs naive baseline | **~98%** |

The repository contains **~10k lines** of Python across scrapers, scoring,
loaders, dashboard, and tests, with **CI** enforcing ruff + black + isort +
pytest on every PR. All work was merged through Pull Requests so both teammates
could review each other's code.

---

## 2. The Problem & Business Hypothesis

### Why this project

In Colombia, **WhatsApp is the dominant sales channel** for SMBs in retail,
beauty, food, and fashion. AI sales agents (chatbots that handle the full sales
conversation) can dramatically increase conversion for these businesses, but the
agents are a **premium product** — they only make sense for SMBs that:

1. Already use WhatsApp as a sales channel (proxy: published phone numbers).
2. Have an active online presence (proxy: Instagram engagement, website).
3. Operate in chat-driven verticals (clothing, food, beauty — not auto repair).
4. Are located in commercial corridors with paying customers (Poblado, Parque 93,
   not rural areas).

### What we built

A pipeline that ranks every SMB in Medellín + Bogotá's premium commercial zones
on a **0-100 AI Readiness Score**, so a sales team can call the top 500 leads
first instead of cold-calling a random list.

---

## 3. Pipeline Architecture

```
                  ┌────────────────────────────┐
  Step 1          │  SCRAPERS                  │
  ──────          │  ────────                  │
                  │  • Google Maps (H3 grid)   │
                  │  • Instagram (instaloader) │
  Raw data        │  • Páginas Amarillas       │ ◄── deferred
                  │  • Mercado Libre           │ ◄── deferred
                  └────────────┬───────────────┘
                               │ writes
                               ▼
                  data/raw/{source}/*.parquet
                               │
                               ▼
                  ┌────────────────────────────┐
  Step 2          │  ENTITY RESOLUTION         │
  ──────          │  ───────────────────       │
                  │  • Normalize names         │
  Dedupe          │  • Two-stage blocking      │
                  │  • Rapidfuzz WRatio >= 85  │
                  │  • Union-Find clustering   │
                  │  • Stable master_id        │
                  └────────────┬───────────────┘
                               │ writes
                               ▼
              data/clean/businesses_canonical.parquet
                               │
                               ▼
                  ┌────────────────────────────┐
  Step 3          │  AI READINESS SCORING      │
  ──────          │  ────────────────────      │
                  │  • 7 weighted features     │
  Score           │  • YAML-tunable weights    │
                  │  • Vertical/geo multipliers│
                  └────────────┬───────────────┘
                               │ writes
                               ▼
                  data/clean/scored.parquet
                  data/clean/top_500.csv
                               │
                               ▼
                  ┌────────────────────────────┐
  Step 4          │  DASHBOARD                 │
  ──────          │  ─────────                 │
                  │  • Overview KPIs           │
  Present         │  • Business Table          │
                  │  • Folium Map View         │
                  │  • Top 500 download        │
                  └────────────────────────────┘

  Persistence layer (parallel):
                  Supabase Postgres
                  ├── businesses_raw (5,286 rows)
                  └── businesses_canonical (3,387 rows)
```

Each step is wrapped in an `invoke` task (`tasks.py`), so the entire pipeline
runs with:

```bash
invoke pipeline   # load_gmaps → resolve → load_canonical → score
```

---

## 4. Plan vs Reality

The original 8-week working plan defined four "Steps" and divided ownership
between the two team members. Here is what shipped and what didn't.

### What we planned and **delivered** ✅

| Component | Owner | Plan | Result |
| --- | --- | --- | --- |
| Repo skeleton, schema, CI, Supabase migrations | Juanpa | Week 1 | ✅ Done — 1 schema, 4 tables, full CI |
| Google Maps scraper (H3 grid + budget guard) | Juanpa | Week 2 | ✅ 4,028 rows, USD 92 spend |
| Instagram scraper (instaloader) | Leo | Week 2 | ✅ 1,258 handles, 1,154 fully scraped |
| Entity resolution (dedup + master_id) | Juanpa | Week 3 | ✅ 5,286 → 3,387 unique |
| AI Readiness Score (7 features, YAML weights) | Juanpa | Week 3 | ✅ Range 19.0 – 82.0 |
| Supabase loader with Pydantic validation | Juanpa | Week 1 | ✅ Both tables, idempotent upserts |
| gmaps ↔ Instagram URL enrichment | Leo | Week 2-3 | ✅ 90% join rate via 3-pass crawl |
| Multi-page Streamlit dashboard | Juanpa | Week 4 | ✅ 4 pages (Overview, Table, Map, Top 500) |
| pytest coverage | Both | All weeks | ✅ 70+ tests, CI-enforced |

### What we planned and **did NOT deliver** ❌ (and why)

| Component | Why deferred |
| --- | --- |
| **Páginas Amarillas spider (live run)** | Built the spider, but the site started returning **302 redirects to homepage** for every search URL, blocking real scraping. Reverse-engineering the new URL structure was scoped out. |
| **Mercado Libre spider (live run)** | Built the spider with HTML-fixture tests passing. Live runs deferred along with Páginas Amarillas — we already had two strong sources (gmaps + IG) and adding more would have required Step 2 re-work without a corresponding accuracy gain. |
| **Step 2 supervised model** (predict Instagram followers from gmaps signals) | The enriched `ig_gmaps_merged.parquet` (1,129 joined rows) was prepared as the training set, but training the model itself was deferred. The hand-engineered AI Readiness Score covers the same role in a transparent, defensible way. |
| **Hand-label validation (Spearman ≥ 0.6 on 50 businesses)** | Time constraints. The score's qualitative validity is demonstrated by inspection — the top-ranked businesses (e.g., Sams Oficial @ 559k IG followers, B Y B L A clothing @ 57k) are exactly the kind that match the chat-AI thesis. |

### Why these omissions don't hurt the project

1. **Sample size is sufficient.** 3,387 canonical businesses across Medellín +
   Bogotá's premium zones is enough to populate a meaningful dashboard and
   identify a top-500 lead list. More sources would have added breadth, not
   depth.
2. **The two delivered sources are complementary.** Google Maps gives location,
   rating, reviews, phone. Instagram gives reach, recency, catalog signal.
   Together they cover all 7 score features.
3. **The score is interpretable**, which matters more for a sales presentation
   than a black-box ML score with marginally better correlation.

---

## 5. Data Sources Deep Dive

### 5.1 Google Maps Places API — 4,028 rows

**The expensive way (rejected):** scrape every Place in Medellín + Bogotá. ~$4,830
in Places API costs and ~50% of results would be rural mom-and-pop shops with
no Instagram and no website — useless for the AI agent thesis.

**The smart way (implemented):**

1. **Curated commercial zones** — 24 named target zones across the two cities:
   El Poblado / Provenza, Parque 93, Zona T, Laureles, Envigado Zona Viva,
   Usaquén, Cedritos, etc. ([`scrapers/gmaps/target_zones.py`](../scrapers/gmaps/target_zones.py))
2. **H3 hexagonal grid** — each zone is filled with H3 resolution-7 hexes
   (~5 km², ~1.2 km edge). Saturated hexes auto-subdivide to res-8 or res-9.
3. **Category × hex Nearby Search** — 15 verticals (restaurants, clothing,
   beauty, dental, gyms, etc.) scanned in each hex.
4. **Cross-category dedup** — a single `seen_place_ids: set[str]` prevents
   paying Place Details fees twice for the same business.
5. **Hard budget cap** — USD 275 ceiling with warnings at $150, $200, $225.
   Pre-flight cost estimate aborts if mid-cost exceeds cap.

**Result:** USD 92 actual spend, 4,028 high-quality Place records.

### 5.2 Instagram (Instaloader) — 1,258 handles, 1,154 scraped

**The discovery pipeline (3-pass) — owner: Leo**

Most Colombian SMBs don't publish their Instagram handle as structured data. So
we built a three-pass extraction:

1. **Pass 1** — gmaps spider already captured the handle from Place data when
   available (low yield).
2. **Pass 2** — regex over `website` URLs against `instagram.com/...` patterns.
3. **Pass 3** — for businesses with a website but no IG link yet, fetch the
   homepage and scrape `<a href>` tags for IG URLs.

**Result:** 1,258 handles discovered out of 4,028 gmaps businesses (31% — high
for a market where most SMBs live entirely on Instagram, not the open web).

**The scrape itself:**

- `instaloader` with session-cookie auth (more reliable than user/password).
- 5-second per-profile throttle, 15-min auto-sleep on rate-limit.
- Checkpoint every 50 profiles → no data loss on interrupt.
- 1,154 / 1,258 profiles scraped successfully; 104 stubs (private / deleted /
  errored) preserved with `quality_flags = ["SCRAPE_FAILED"]` so the row count
  doesn't lie.

**The gmaps↔IG join** — Leo embedded gmaps `rating`, `reviews_count`, `name`,
and `website` directly into the crawl checkpoint. Final join rate:
**1,129 / 1,258 = 90%**.

### 5.3 Páginas Amarillas (Yellow Pages) — built but not run

Full Scrapy spider implemented in
[`scrapers/directories/spiders/paginas_amarillas.py`](../scrapers/directories/spiders/paginas_amarillas.py):
15 verticals × 2 cities, CSS-selector parsing, MD5 `source_id`, WhatsApp/IG
extraction, fixture-based tests passing.

**Blocker:** the site started returning 302 redirects to the homepage for every
search URL we tried. We set `ROBOTSTXT_OBEY=False` and a browser User-Agent
header, but the redirect persisted. Reverse-engineering the new URL structure
was out of scope.

### 5.4 Mercado Libre — built but not run

Two-stage Scrapy spider (store listing → detail page) in
[`scrapers/directories/spiders/mercado_libre.py`](../scrapers/directories/spiders/mercado_libre.py),
6 verticals × 2 cities, 17 fixture-based tests passing.

**Why we didn't run it:** combined with Páginas Amarillas being blocked, we had
to choose between debugging a third source or delivering the scoring +
dashboard. We chose delivery.

---

## 6. Entity Resolution

The hard problem: the same business appears multiple times across sources, and
also multiple times within a single source. We need a single canonical record
per real-world entity.

### Algorithm — [`scoring/entity_resolution.py`](../scoring/entity_resolution.py)

**Step 1: name normalization**

- Unicode NFD decomposition → strip diacritics.
- Lowercase.
- Strip legal suffixes (`S.A.S.`, `Ltda.`, `& Cía`, etc.) — regex-based.
- Collapse residual punctuation and whitespace.

**Step 2: two-stage blocking**

Comparing all 5,286 rows pairwise would be O(n²) = 28M comparisons. Blocking
constrains comparisons to within small candidate groups:

- **Block A — exact `(city, phone_e164)`** — if two rows share a normalized
  phone number in the same city, they're almost certainly the same business.
- **Block B — exact `(city, first_significant_token)`** — first non-stopword
  token of the normalized name. Stopwords like *restaurante*, *salón*,
  *peluquería* are skipped because every business in that vertical would
  collide.

**Step 3: fuzzy similarity within blocks**

Within each block, `rapidfuzz.WRatio` is computed for every pair. WRatio is a
weighted combination of `ratio`, `partial_ratio`, `token_sort`, and `token_set`,
each token-frequency normalized — it's robust to word reordering, abbreviation,
and partial matches.

**Threshold: WRatio ≥ 85.**

**Step 4: Union-Find clustering**

Each match (i, j) calls `union(i, j)`. After all matches are processed, each
connected component is one entity. Union-Find with path compression keeps this
near-linear.

**Step 5: stable `master_id`**

```python
master_id = uuid5(NAMESPACE_DNS, f"{city}|{canonical_name}")
```

Deterministic — same business gets the same UUID across runs, even if rows are
inserted/deleted. This is what makes the canonical table re-runnable without
breaking dashboards or downstream joins.

**Step 6: canonical representative selection**

For each cluster, pick the row with the **most non-null fields** (phone,
website, instagram, rating, reviews, address, coords). Tie-break on name length
(longer = more specific). The Instagram-origin row often beats the gmaps row
because it carries more Instagram metadata, while the gmaps row carries rating
and reviews — so the canonical row inherits the union of both via the JOIN in
the scoring step.

### Results

| Metric | Count |
| --- | --- |
| Raw rows in | 5,286 |
| Unique businesses out | 3,387 |
| Duplicates merged | 1,899 |
| gmaps↔Instagram merges (cross-source) | 815 |
| Instagram-only entities | 443 |

**Cross-source merge rate: 815 / 1,258 = 65%.** The remaining 443 Instagram
businesses are real SMBs that don't have a Google Maps presence.

### Regression tests

[`tests/test_entity_resolution.py`](../tests/test_entity_resolution.py) — 14
tests including the "Restaurante X vs Restaurante Y false merge" regression that
locks in the stopword-aware blocking. The first version of the algorithm used
plain `first_token`, which collapsed all restaurants into one cluster — a fix
we shipped during development.

---

## 7. AI Readiness Score

A 0–100 weighted sum of seven features, each in [0.0, 1.0]. Weights are
externalized to YAML for tuning without code changes.

### The features

[`scoring/features.py`](../scoring/features.py)

| Feature | Weight | Formula | Reasoning |
| --- | ---:| --- | --- |
| `vertical_weight` | **0.20** | YAML lookup by category | Chat-AI fit varies dramatically by vertical (food/clothing 1.0; auto repair 0.5) |
| `whatsapp_signal` | **0.20** | 1.0 if WhatsApp-flagged; 0.5 if phone-only; 0.0 else | WhatsApp is the channel the agent will use |
| `instagram_reach` | **0.15** | `log1p(followers) / log1p(50,000)` | Audience size, cap at 50k to prevent influencer-account dominance |
| `instagram_activity` | **0.15** | 1.0 if posted ≤7 days; linear decay to 0.0 at ≥180 days | A dead account can't be sold to |
| `catalog_signal` | **0.10** | 1.0 if Instagram product catalog enabled | Strong proof of intent to sell online |
| `review_volume` | **0.10** | `log1p(reviews) / log1p(1,000)` | Active customer base = LTV |
| `geographic_weight` | **0.10** | YAML lookup by (city, neighborhood) | Premium zones = paying customers |

**Final score formula:**

```
weighted_sum = Σ (feature_i × weight_i)
score        = (weighted_sum / Σ weights) × 100
```

### Vertical weights — `scoring/vertical_weights.yaml`

| Tier | Weight | Verticals |
| --- | ---:| --- |
| Strong chat-driven | 1.0 | restaurants, beauty_salons, clothing_stores, bakeries, jewelry_stores |
| Moderate | 0.8 | gyms, dental_clinics, optical_stores, veterinarians, photographers |
| Low fit | 0.5 – 0.7 | real_estate, auto_repair, cleaning_services, language_schools |

### Geographic weights — `scoring/geographic_weights.yaml`

| Tier | Weight | Examples |
| --- | ---:| --- |
| Premium | 1.0 | El Poblado / Provenza, Parque 93, Zona T, Rosales, Ciudad del Río, Envigado Zona Viva |
| Strong commercial | 0.85 – 0.95 | Usaquén Santa Bárbara, Laureles, Unicentro, Chapinero Alto, Sabaneta |
| Working-class commercial | 0.7 – 0.8 | Itagüí, Fontibón, Belén Rosales, Modelia |

### Evidence enrichment

A business in Google Maps often comes back with a compound `category_raw` like
`"establishment, point of interest"` — useless for `vertical_weight` lookup. To
fix this, the scoring layer JOINs against
`data/interim/gmaps_place_categories.parquet`, which preserves the **search
query that found the business** (e.g., `"restaurant"`, `"jewelry_store"`) as a
canonical slug, plus the H3 zone the business sits in. This `category_slug` and
zone-derived `neighborhood` override the compound category in scoring. 2,900
canonical rows were enriched this way.

### Unit tests

[`tests/test_scoring_features.py`](../tests/test_scoring_features.py) — 26
tests covering edge cases: zero followers, future-dated posts, missing
categories, default fallbacks, etc.

---

## 8. Final Results

### Score distribution

| Bucket | Count | % |
| --- | ---:| ---:|
| 70 – 100 (hot leads) | 10 | 0.3% |
| 60 – 70 | 36 | 1.1% |
| 50 – 60 | 131 | 3.9% |
| 40 – 50 | ~1,500 | 44% |
| < 40 | ~1,710 | 50% |

- **Minimum:** 19.0
- **Median:** 40.6
- **Mean:** 40.1
- **Maximum:** 82.0

The compressed distribution (most businesses 30–50) reflects that **most SMBs
don't have a strong Instagram presence**. The thin top tail (only 46 businesses
≥ 60) is exactly the sales target — those are the businesses where the
WhatsApp AI agent makes economic sense.

### Top 10 highest-scoring businesses

| Score | Business | IG Followers | Why it scored high |
| ---:| --- | ---:| --- |
| 82.0 | **Sams Oficial** | 559,232 | Massive audience, active, premium zone |
| 82.0 | **B Y B L A** | 57,248 | Clothing, premium zone, high engagement |
| 79.4 | **gurú Colombia** | 18,291 | Strong activity + reach + catalog |
| 78.3 | **ecometri** | 3,444 | Catalog + activity + premium neighborhood |
| 72.0 | **Fashion Lab** | 427,012 | Clothing vertical, massive reach |
| 72.0 | **ChronosFantasy** | 62,624 | Jewelry vertical, high activity |
| ... | ... | ... | ... |

These are real Colombian SMBs that match the AI agent thesis precisely:
chat-driven verticals, big Instagram audiences, located in zones where premium
products sell.

### Geographic split

- **Bogotá:** 1,858 canonical businesses (55%)
- **Medellín:** 1,529 canonical businesses (45%)

### Vertical mix (top 10)

| Vertical | Businesses |
| --- | ---:|
| Generic POI | 555 |
| Health establishment | 332 |
| Restaurant | 289 |
| Clothing store | 286 |
| Real estate agency | 262 |
| Jewelry store | 242 |
| Gym | 209 |
| Veterinary care | 197 |
| Car repair | 183 |
| Beauty salon | 175 |

### Data completeness

| Field | Coverage |
| --- | ---:|
| Phone number (E.164) | 2,463 / 3,387 = 73% |
| Website | 2,010 / 3,387 = 59% |
| Instagram handle | 747 / 3,387 = 22% |
| Instagram followers (live) | 387 / 3,387 = 11% |
| Google Maps rating | 2,777 / 3,387 = 82% |

---

## 9. Persistence — Supabase

PostgreSQL 17 hosted on Supabase, sa-east-1.

### Schema — [`db/migrations/001_create_schema.sql`](../db/migrations/001_create_schema.sql)

Two tables mirror the in-memory pipeline:

- **`businesses_raw`** — one row per (source, source_id) pair. 5,286 rows.
- **`businesses_canonical`** — one row per `master_id`. 3,387 rows.

Key design choices:

- `source` is a foreign-key to a lookup table (`gmaps`, `instagram`,
  `paginas_amarillas`, `mercado_libre`), so adding a new scraper is one INSERT.
- `UNIQUE(source, source_id)` on raw enables safe idempotent re-runs.
- `master_id` is `UNIQUE` on canonical for the same reason.
- Phone numbers are `CHECK`-constrained to `^\+57[0-9]{10}$` (Colombian E.164).
- City is `CHECK`-constrained to `{'Medellín', 'Bogotá'}`.
- `quality_flags` is JSONB so we can attach issue tags
  (`SCRAPE_FAILED`, `INACTIVE_INSTAGRAM`, etc.) without schema changes.
- A trigram GIN index on `name_normalized` accelerates fuzzy lookups from the
  dashboard.
- `updated_at` is maintained by a Postgres trigger.

### Loader — [`utils/load_to_supabase.py`](../utils/load_to_supabase.py)

- **Pydantic validation** before upsert — bad rows are written to an error CSV
  and never hit the DB.
- **Tenacity retry** with exponential back-off (3 tries, 2–8s) on transient
  network failures.
- **Per-table on-conflict keys** — `(source, source_id)` for raw,
  `master_id` for canonical.
- **Batched** at 500 rows.
- **Idempotent** — same parquet can be loaded any number of times.

---

## 10. Dashboard

[`dashboard/`](../dashboard/) — multi-page Streamlit app.

### Pages

1. **Overview** (`app.py`)
   - 4 KPI cards: total businesses, average score, top vertical, top
     neighborhood.
   - Plotly histogram of score distribution (color-split by city when both
     present in the filtered view).
   - Two side-by-side bar charts: businesses-per-vertical and avg-score-per-vertical.

2. **Business Table** (`pages/1_Business_Table.py`)
   - Sortable, searchable table with all filtered businesses.
   - `st.column_config.LinkColumn` makes website cells clickable.
   - One-click CSV export of the current filter view.

3. **Map View** (`pages/2_Map_View.py`)
   - Folium + Leaflet map with `MarkerCluster` for performance (caps at 1,500
     markers; if filters return more, we show the top-scored 1,500).
   - 5-band quintile colouring: red = score ≥ 60, orange = 50–60, light blue =
     40–50, mid blue = 30–40, dark blue < 30.
   - HTML popup on each marker with name, score, rating, website, and IG link.
   - Floating legend overlay.

4. **Top 500** (`pages/3_Top_500.py`)
   - User-controlled slider (10 – 500).
   - Summary metrics: score range, median, with-phone %.
   - Ranked table with stable `rank` index, downloadable as CSV.

### Shared infrastructure

- [`dashboard/lib/data.py`](../dashboard/lib/data.py) — single `load_businesses()`
  function with priority fallback: `data/clean/scored.parquet` → Supabase →
  empty frame. `@st.cache_data(ttl=3600)` so a session doesn't re-read the
  parquet every interaction.
- [`dashboard/lib/filters.py`](../dashboard/lib/filters.py) — the sidebar
  filter widget that all 4 pages share. City multiselect, vertical multiselect,
  score slider, channel-signal checkboxes (has-website / has-IG / has-WhatsApp),
  neighborhood expander, free-text name search. State persisted in
  `st.session_state` so filters survive page navigation.

---

## 11. Tech Stack

| Layer | Tools |
| --- | --- |
| Language | Python 3.11 / 3.12 |
| Scraping | Scrapy 2.15, Instaloader 4.15, googlemaps 4.10 |
| Data | Polars 1.40, Pandas 3.0, PyArrow 24.0 |
| Geo | H3 v4 (hexagonal grid), Folium 0.20 |
| Validation | Pydantic v2, pydantic-settings |
| Fuzzy match | RapidFuzz 3.14 |
| Phones | phonenumbers 9.0 |
| Storage | Supabase (Postgres 17) |
| Dashboard | Streamlit 1.57, Plotly 6.7, streamlit-folium 0.27 |
| Logging | Loguru |
| Task runner | Invoke 3.0 |
| Resilience | Tenacity 9.1 |
| Config | PyYAML 6.0 |
| Testing | pytest 9.0, pytest-cov 7.1 |
| Linting | ruff 0.15, black 26, isort 8.0 |
| CI | GitHub Actions (lint-and-test on every PR) |

---

## 12. Development Process

### Repository governance

- All work landed via Pull Requests — **7 merged PRs** total.
- Both team members reviewed each other's PRs before merge.
- CI enforced lint + tests on every push; no PR could merge with a red CI.
- All commits use Conventional Commits prefixes (`feat:`, `fix:`, `refactor:`,
  etc.) for clear history.

### Test coverage

| Test file | Tests | Subject |
| --- | ---:| --- |
| `test_models.py` | n | Pydantic schema |
| `test_load_to_supabase.py` | n | Validation + error CSV + idempotency |
| `test_gmaps_*.py` | n | Spider, target zones, H3 grid, dedup |
| `test_gmaps_instagram_extraction.py` | 21 | Instagram URL → handle |
| `test_instagram_normalize.py` | 25 | Profile → BusinessRaw (mocked) |
| `test_directories.py` | 17 | PA + ML spiders, fixture-based |
| `test_entity_resolution.py` | 14 | Blocking, fuzzy, Union-Find, stopwords |
| `test_scoring_features.py` | 26 | All 7 features + edge cases |

**~70+ tests total**, all CI-enforced.

### Cost control

The single biggest engineering decision was **not** scraping all of Medellín +
Bogotá from Google Maps. The H3 + named-zones approach cut the API bill from
$4,830 to **$92** — a 98% reduction — without losing relevant signal. This
constraint forced us to think about the *target customer profile* up front
rather than scraping first and filtering later, which improved the final score
quality.

---

## 13. Lessons & Trade-offs

### What we'd do differently

1. **Páginas Amarillas / Mercado Libre** — should have probed the live sites
   *before* writing the spiders. The 302-redirect block was discoverable in 10
   minutes with `curl` and would have saved a day of spider development.
2. **Hand-label validation** — should have allocated a half-day for two team
   members to blind-rate 50 businesses on a 0-100 scale and computed Spearman
   correlation vs the model. Without this, the score's validity is qualitative,
   not quantitative.
3. **Smaller, more frequent PRs** — Leo's onboarding PR was 800 lines and took
   a long review cycle; Juanpa's scoring PR was 700 lines and same. Splitting
   into 200-line PRs would have shortened review feedback loops.

### What worked surprisingly well

1. **YAML-externalized weights.** Being able to tune `vertical_weights.yaml`
   without touching code meant every score-tuning experiment was a one-line
   diff, not a code change. If this project continued, A/B-testing different
   weight schemes would be trivial.
2. **The 90% gmaps↔IG join rate** via Leo's 3-pass discovery (column → URL
   regex → website crawl) was way higher than expected. Most Instagram-IG-only
   businesses we found are real, not noise.
3. **Stable `master_id` via uuid5**. Re-running the entire pipeline produces
   identical UUIDs for the same business, so downstream consumers (Supabase
   joins, dashboards, exports) never break.

### Open follow-ups (for a hypothetical next semester)

- Páginas Amarillas — reverse-engineer the new URL structure or pivot to
  another directory (`computrabajo.com`, `eldescuento.com.co`).
- Supervised regression: predict `instagram_followers` from gmaps
  `rating + reviews + city + category` to fill in the 60% of businesses with no
  IG handle.
- Streamlit Cloud deployment + Supabase secrets, so non-technical stakeholders
  can browse the dashboard without setting up Python.
- Hand-label 50 businesses → Spearman ≥ 0.6 validation.

---

## 14. Repository Map

```
smb-intel-co/
├── scrapers/
│   ├── gmaps/                  Google Maps scraper, H3 grid, target zones
│   ├── instagram/              Instaloader-based scraper + normalizer
│   └── directories/            PA + ML Scrapy spiders (built, not run live)
├── scoring/
│   ├── entity_resolution.py    5,286 → 3,387 dedup
│   ├── features.py             7-feature AI Readiness Score
│   ├── weights.yaml            Global feature weights
│   ├── vertical_weights.yaml   Category multipliers
│   └── geographic_weights.yaml Neighborhood multipliers
├── dashboard/
│   ├── app.py                  Overview page
│   ├── pages/                  Table, Map, Top 500
│   └── lib/                    Data + filter helpers
├── utils/
│   ├── load_to_supabase.py     Pydantic-validated upsert
│   ├── models.py               BusinessRaw, BusinessCanonical
│   ├── fetch_gmaps_websites.py 3-pass IG handle discovery
│   └── merge_gmaps_instagram.py Cross-source join for the ML training set
├── db/
│   └── migrations/             001_create_schema.sql
├── docs/
│   ├── schema.md               Schema contract
│   └── PROJECT_REPORT.md       (this file)
├── tests/                      70+ pytest tests
├── tasks.py                    Invoke task runner
└── requirements.txt
```

---

## 15. How to Reproduce

```bash
# 1. Clone + install
git clone https://github.com/Jpperez09/BigData_ColombiaSB.git smb-intel-co
cd smb-intel-co
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
cp .env.template .env             # then fill in SUPABASE_URL, SUPABASE_SERVICE_KEY,
                                   #                 GMAPS_API_KEY, IG_USERNAME, IG_PASSWORD

# 2. Database
# Run db/migrations/001_create_schema.sql against your Supabase project

# 3. Pipeline
invoke gmaps-dry-run              # preview cost
invoke gmaps-smoke                # cheap smoke test
invoke scrape-gmaps               # ~$92, ~30 min
invoke scrape-instagram           # ~1.5h with throttling
invoke pipeline                   # load → resolve → load-canonical → score
invoke dashboard                  # http://localhost:8501
```

---

**Authors:** Juan Pablo Pérez Mejía & Leonardo Miani
**Course:** Big Data, Spring 2026
**Institution:** Knox College, DIS Copenhagen
