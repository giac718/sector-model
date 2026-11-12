"""Rank the sector ETFs by recent performance relative to SPY.

Reads data/prices.csv, computes each sector's return minus SPY's return over
the last 21, 63, and 126 trading days, averages the three into a score, and
saves the ranked table to output/ranks_today.csv.
"""

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = PROJECT_ROOT / "data" / "prices.csv"
OUTPUT_PATH = PROJECT_ROOT / "output" / "ranks_today.csv"

BENCHMARK = "SPY"
SECTORS = [
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP",
    "XLI", "XLB", "XLU", "XLRE", "XLC",
]
# Column label -> lookback in trading days
WINDOWS = {"1m": 21, "3m": 63, "6m": 126}


def load_prices() -> pd.DataFrame:
    if not PRICES_PATH.exists():
        raise RuntimeError(
            f"{PRICES_PATH} not found. Run scripts/fetch_prices.py first."
        )
    prices = pd.read_csv(PRICES_PATH, parse_dates=["Date"]).set_index("Date")
    prices = prices.sort_index()

    missing = [t for t in [BENCHMARK, *SECTORS] if t not in prices.columns]
    if missing:
        raise RuntimeError(f"Missing tickers in {PRICES_PATH.name}: {missing}")

    # Only keep days where every ticker has a price, so all returns are
    # measured between the same two dates.
    prices = prices[[BENCHMARK, *SECTORS]].dropna()

    needed = max(WINDOWS.values()) + 1
    if len(prices) < needed:
        raise RuntimeError(
            f"Need at least {needed} complete rows of prices, found {len(prices)}."
        )
    return prices


def rank_sectors(prices: pd.DataFrame) -> pd.DataFrame:
    """Return the ranked table, with relative returns and score in percent."""
    table = pd.DataFrame(index=pd.Index(SECTORS, name="Sector"))
    for label, days in WINDOWS.items():
        returns = prices.iloc[-1] / prices.iloc[-1 - days] - 1
        table[label] = (returns[SECTORS] - returns[BENCHMARK]) * 100

    table["Score"] = table[list(WINDOWS)].mean(axis=1)
    table["Rank"] = table["Score"].rank(ascending=False, method="first").astype(int)
    return table.sort_values("Rank").reset_index()


def main() -> int:
    try:
        prices = load_prices()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    table = rank_sectors(prices)

    # The CSV keeps full precision; rounding is only applied when printing.
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUTPUT_PATH, index=False)

    print(f"Sector returns relative to {BENCHMARK}, as of {prices.index[-1].date()}")
    print("(percentage points; Score = average of 1m, 3m, 6m)\n")
    print(
        table.to_string(
            index=False,
            formatters={
                **{w: "{:+.1f}".format for w in WINDOWS},
                "Score": "{:+.2f}".format,
            },
        )
    )
    print(f"\nSaved to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
