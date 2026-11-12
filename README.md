# Sector Rotation Tool

Analyzes rotation among the SPDR sector ETFs relative to SPY.

## Layout

- `scripts/` — Python code, one script per step
- `data/` — downloaded data
- `output/` — charts and result tables

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Steps

1. Fetch prices — downloads daily adjusted closes (2018-01-01 to today) for SPY and the 11 sector ETFs into `data/prices.csv`:

```bash
.venv/bin/python scripts/fetch_prices.py
```

## Daily run

`.github/workflows/daily.yml` runs every script Monday to Friday at 22:30 UTC
(and on demand from the Actions tab), then publishes the `output/` folder to
GitHub Pages. `scripts/build_site.py` builds the landing page, `output/index.html`.
Generated files are not committed back to the repository.
