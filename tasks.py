from invoke import task


@task
def install(c):
    """Install dependencies and pre-commit hooks."""
    c.run("pip install -r requirements.txt")
    c.run("pre-commit install")


@task
def lint(c):
    """Check code style with ruff, black, and isort."""
    c.run("ruff check .")
    c.run("black --check .")
    c.run("isort --check-only .")


@task
def fmt(c):
    """Auto-format source code with black, isort, and ruff --fix."""
    c.run("black .")
    c.run("isort .")
    c.run("ruff check --fix .")


@task
def test(c):
    """Run pytest with coverage for utils and scrapers."""
    c.run("pytest -v --cov=utils --cov=scrapers")


@task
def gmaps_dry_run(c, priority_max=2):
    """Print the H3 grid + cost estimate without calling Google APIs."""
    c.run(
        f"python -m scrapers.gmaps.run --all-cities --all-categories "
        f"--dry-run-grid --priority-max {priority_max}"
    )


@task
def gmaps_estimate(c, priority_max=2, budget_cap_usd=275):
    """Print a detailed pre-flight cost estimate without calling Google APIs."""
    c.run(
        f"python -m scrapers.gmaps.run --all-cities --all-categories "
        f"--estimate-cost --priority-max {priority_max} --budget-cap-usd {budget_cap_usd}"
    )


@task
def gmaps_smoke(c, city="medellin", category="restaurants", limit_hexes=5):
    """Cheap smoke scrape (single city, single category, capped hexes)."""
    c.run(
        f"python -m scrapers.gmaps.run --city {city} --category {category} "
        f"--limit-hexes {limit_hexes} --budget-cap-usd 25"
    )


@task
def scrape_gmaps(c, city=None, category=None, priority_max=2, budget_cap_usd=275, force=False):
    """Run the GMaps scraper.

    Defaults: --all-cities, all priority<=2 categories, target-zone H3 grid.

    Examples::

        invoke scrape-gmaps                                # full production run
        invoke scrape-gmaps --city medellin                # single city
        invoke scrape-gmaps --priority-max 1               # priority-1 zones+cats only
        invoke scrape-gmaps --budget-cap-usd 200           # tighter cap
        invoke scrape-gmaps --force                        # bypass over-budget guard
    """
    parts = ["python -m scrapers.gmaps.run"]
    parts.append(f"--city {city}" if city else "--all-cities")
    if category:
        parts.append(f"--category {category}")
    else:
        parts.append("--all-categories")
    parts.append(f"--priority-max {priority_max}")
    parts.append(f"--budget-cap-usd {budget_cap_usd}")
    if force:
        parts.append("--force-over-budget")
    c.run(" ".join(parts))


@task
def scrape_instagram(c):
    """Scrape Instagram business profiles (placeholder — Week 1)."""
    print("TODO: implementar en Week 1")


@task
def scrape_directories(c):
    """Scrape public business directories (placeholder — Week 1)."""
    print("TODO: implementar en Week 1")


@task
def resolve(c, threshold=85, source=None, dry_run=False):
    """Run entity resolution: merge all raw sources into businesses_canonical.

    Examples::

        invoke resolve                        # full run, threshold 85
        invoke resolve --threshold 80         # looser fuzzy match
        invoke resolve --source gmaps         # gmaps only (before Leo's data)
        invoke resolve --dry-run              # preview without writing
    """
    cmd = f"python -m scoring.entity_resolution --threshold {threshold}"
    if source:
        cmd += f" --source {source}"
    if dry_run:
        cmd += " --dry-run"
    c.run(cmd)


@task
def clean(c):
    """Remove intermediate and output files (placeholder — Week 2)."""
    print("TODO: implementar en Week 2")


@task
def score(c, top_n=500, city=None, min_score=0, output="data/clean/top_500.csv"):
    """Compute AI Readiness scores and export top-N businesses.

    Requires entity resolution to have run first (invoke resolve).

    Examples::

        invoke score                          # top 500 across all cities
        invoke score --city Medellín          # single city
        invoke score --top-n 200              # smaller export
        invoke score --min-score 40           # only high-quality leads
    """
    cmd = f"python -m scoring.features --top-n {top_n} --output {output}"
    if city:
        cmd += f" --city \"{city}\""
    if min_score:
        cmd += f" --min-score {min_score}"
    c.run(cmd)


@task
def dashboard(c):
    """Launch the Streamlit dashboard."""
    c.run("streamlit run dashboard/app.py")


@task
def load(c, source, path):
    """Load a Parquet file into Supabase (--source SOURCE --path PATH)."""
    c.run(f"python -m utils.load_to_supabase --source {source} --path {path}")
