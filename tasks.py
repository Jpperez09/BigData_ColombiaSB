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
def scrape_gmaps(c, city="medellin"):
    """Scrape Google Maps for a given city (placeholder — Week 1)."""
    print(f"TODO: implementar en Week 1 (city={city})")


@task
def scrape_instagram(c):
    """Scrape Instagram business profiles (placeholder — Week 1)."""
    print("TODO: implementar en Week 1")


@task
def scrape_directories(c):
    """Scrape public business directories (placeholder — Week 1)."""
    print("TODO: implementar en Week 1")


@task
def clean(c):
    """Remove intermediate and output files (placeholder — Week 2)."""
    print("TODO: implementar en Week 2")


@task
def score(c):
    """Run the AI Readiness scoring pipeline (placeholder — Week 3)."""
    print("TODO: implementar en Week 3")


@task
def dashboard(c):
    """Launch the Streamlit dashboard."""
    c.run("streamlit run dashboard/app.py")


@task
def load(c, source, path):
    """Load a Parquet file into Supabase (--source SOURCE --path PATH)."""
    c.run(f"python -m utils.load_to_supabase --source {source} --path {path}")
