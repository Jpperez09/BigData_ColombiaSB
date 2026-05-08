# AI Readiness Score — Methodology

> Step 3 deliverable. Owner: Juanpa.
> Working plan: see Section 7.1 of `SMB_Intel_CO_Working_Plan.docx.md`.

## What we're measuring

A single 0–100 number per business that estimates how well that business
would benefit from a WhatsApp-based AI sales agent. Higher is better.

The score is **not** a quality measure of the business itself. A bad
restaurant with active Instagram + a WhatsApp number can score higher than
an excellent corporate firm that doesn't sell via chat.

## Pipeline

```
data/clean/businesses_canonical.parquet
        │
        ▼
  scoring.features.compute_scores()
        │
        ├── enrich from data/interim/gmaps_place_categories.parquet
        │     (overrides compound `category_raw` with the canonical slug,
        │      fills missing `neighborhood` with the H3 zone name)
        │
        ├── 7 feature functions (each returns a value in [0, 1])
        │
        ├── linear weighted sum, weights from scoring/weights.yaml
        │
        └── normalised to 0–100
                │
                ├── data/clean/scored.parquet  (full)
                └── data/clean/top_500.csv     (ranked, exported)
```

## Features

| Feature | Source field(s) | Range | Notes |
| ------- | --------------- | ----- | ----- |
| `whatsapp_signal` | `whatsapp_flag`, `phone_e164` | 0 / 0.5 / 1 | 1 if explicitly flagged WhatsApp, 0.5 if any phone is present, else 0 |
| `instagram_reach` | `instagram_followers` | 0–1 | `log1p(followers) / log1p(50_000)`, capped at 1 |
| `instagram_activity` | `instagram_last_post_at` | 0–1 | 1 if posted within 7 days, linearly decays to 0 at 180 days |
| `catalog_signal` | `instagram_has_catalog` | 0 / 1 | Binary |
| `review_volume` | `reviews_count` | 0–1 | `log1p(reviews) / log1p(1_000)`, capped at 1 |
| `vertical_weight` | `category_raw` (enriched to slug) | 0.5–1.0 | Lookup in `scoring/vertical_weights.yaml`. Restaurants/beauty/clothing = 1.0, auto repair = 0.5 |
| `geographic_weight` | `(city, neighborhood)` | 0.6–1.0 | Lookup in `scoring/geographic_weights.yaml`. Premium zones (Poblado, Parque 93) = 1.0 |

## Weights

Default weights (in `scoring/weights.yaml`) sum to 1.0:

| Feature | Default weight |
| ------- | -------------- |
| `whatsapp_signal` | 0.20 |
| `vertical_weight` | 0.20 |
| `instagram_reach` | 0.15 |
| `instagram_activity` | 0.15 |
| `catalog_signal` | 0.10 |
| `review_volume` | 0.10 |
| `geographic_weight` | 0.10 |

The score is `(Σ feature_i × weight_i) / Σ weight_i × 100`, so a "perfect"
business hits exactly 100.

Each weight change must be committed with a one-line rationale and a note
of the new Spearman correlation against the hand-label set (see Validation).

## Validation (TODO)

Per the working plan we need Spearman rank correlation **≥ 0.6** against a
50-row hand-label set:

- [ ] Pick 50 businesses spanning high/mid/low predicted scores
- [ ] Juanpa labels each as `good_fit / not_a_fit / unsure` blind to score
- [ ] Mónica (Hilitos) repeats the labelling independently
- [ ] Compute Spearman correlation: target ≥ 0.6
- [ ] If < 0.6, iterate on weights and document each iteration below

### Iteration log

| Date | Change | Rationale | Spearman ρ | Top-500 churn |
| ---- | ------ | --------- | ---------- | ------------- |
| 2026-05-08 | Initial weights from working plan | First implementation | — | — |

## Known limitations (current snapshot)

- **Instagram fields all null until Leo's scraper merges.** Until then, the
  Instagram features (`reach`, `activity`, `catalog_signal`) return 0 for
  every business. This caps achievable scores at ~60 even for premium SMBs.
- **`whatsapp_flag` not populated by GMaps scraper.** Phones are detected
  but the WhatsApp flag isn't set automatically; needs Leo's number-format
  signal (e.g. wa.me redirect detection) to lift the half-credit signal.
- **Neighborhood enrichment is gmaps-specific.** Once Leo's scrapers land,
  rows from `paginas_amarillas` and `mercado_libre` will fall back to the
  city-level default geographic weight. Worth a small follow-up once we see
  what neighborhood data those sources expose.
- **Compound categories.** The Google Places API returns `category_raw` as
  comma-separated types ("cafe, restaurant"). We override with the canonical
  search-keyword slug from the evidence file. For non-gmaps sources, this
  override is unavailable — currently they fall back to the literal raw
  string, which won't match any vertical-weight key and will use the
  default weight.

## How to re-run

```bash
# After data lands in data/clean/businesses_canonical.parquet:
invoke score                       # top 500 across all cities
invoke score --city "Medellín"     # single city
invoke score --min-score 40        # only high-fit businesses
```
