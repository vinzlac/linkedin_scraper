# linkedin_scraper — task runner
# Requires: uv, just

# Default: list available recipes
default:
    @just --list

# Install all dependencies (including dev) and Playwright browsers
install:
    uv sync --group dev
    uv run playwright install chromium

# Run unit tests only (no LinkedIn session required)
test:
    uv run pytest -m "not integration and not slow"

# Run a single test file
test-file FILE:
    uv run pytest {{ FILE }} -m "not integration"

# Run a single test by name
test-one FILE TEST:
    uv run pytest {{ FILE }}::{{ TEST }}

# Run integration tests (requires linkedin_session.json)
test-integration:
    uv run pytest -m integration

# Run all tests with coverage report
test-cov:
    uv run pytest -m "not integration" --cov=linkedin_scraper --cov-report=term-missing

# Format code with black
fmt:
    uv run black linkedin_scraper tests samples

# Check formatting without modifying files
fmt-check:
    uv run black --check linkedin_scraper tests samples

# Lint with flake8
lint:
    uv run flake8 linkedin_scraper tests

# Type check with mypy
typecheck:
    uv run mypy linkedin_scraper

# Run all checks (fmt-check + lint + typecheck + test)
check: fmt-check lint test

# Create a LinkedIn session file (opens browser for manual login)
session:
    uv run python samples/create_session.py

# Scrape N posts from your LinkedIn feed (default: 10)
run-feed N="10":
    uv run python samples/scrape_feed.py {{ N }}

# Scrape N posts from feed using a virtual display (for Linux servers without a GUI)
# Requires: sudo apt install xvfb
run-feed-xvfb N="10":
    xvfb-run --server-args="-screen 0 1280x720x24" uv run python samples/scrape_feed.py {{ N }}

# Debug DOM structure of LinkedIn feed
debug-feed:
    uv run python samples/debug_feed.py

# Scrape a LinkedIn profile (URL or slug)
run-person PROFILE:
    uv run python samples/scrape_person.py {{ PROFILE }}

# Debug DOM selectors on a profile page (helps fix broken selectors)
debug-person PROFILE:
    uv run python samples/debug_person.py {{ PROFILE }}

# Run the company posts scraper sample
run-company URL="https://www.linkedin.com/company/microsoft/":
    uv run python samples/scrape_company_posts.py

# Build distribution packages
build:
    uv build

# Publish to PyPI (requires TWINE_USERNAME / TWINE_PASSWORD or ~/.pypirc)
publish:
    uv run twine upload dist/*
