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
| `invoke scrape-gmaps --city medellin` | Scrape Google Maps for a given city (Week 1) |
| `invoke scrape-instagram` | Scrape Instagram business profiles (Week 1) |
| `invoke scrape-directories` | Scrape public business directories (Week 1) |
| `invoke clean` | Remove intermediate and output files (Week 2) |
| `invoke score` | Run the AI Readiness scoring pipeline (Week 3) |
| `invoke dashboard` | Launch the Streamlit dashboard |
| `invoke load --source SOURCE --path PATH` | Load a Parquet file into Supabase |

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
