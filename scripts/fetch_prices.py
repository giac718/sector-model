"""Download daily adjusted close prices for SPY and the sector ETFs.

Saves a flat table (Date + one column per ticker) to data/prices.csv.
"""

import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "prices.csv"

TICKERS = [
    "SPY", "XLK", "XLF", "XLE", "XLV", "XLY",
    "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC",
]
START = "2018-01-01"
MAX_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 5


def download_prices() -> pd.DataFrame:
    """Download closes for all tickers, retrying on failure or empty result."""
    # yfinance's `end` is exclusive, so ask for tomorrow to include today.
    end = (date.today() + timedelta(days=1)).isoformat()
    last_error = "unknown error"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = yf.download(
                TICKERS,
                start=START,
                end=end,
                auto_adjust=True,
                progress=False,
            )
            if raw is not None and not raw.empty:
                closes = raw["Close"]
                if not closes.dropna(how="all").empty:
                    return closes
            last_error = "download came back empty"
        except Exception as exc:  # yfinance raises a variety of error types
            last_error = f"{type(exc).__name__}: {exc}"

        print(f"Attempt {attempt}/{MAX_ATTEMPTS} failed: {last_error}")
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_WAIT_SECONDS)

    raise RuntimeError(
        f"Price download failed after {MAX_ATTEMPTS} attempts: {last_error}"
    )


def flatten(closes: pd.DataFrame) -> pd.DataFrame:
    """Turn the yfinance result into Date + one plain column per ticker."""
    table = closes.dropna(how="all").copy()
    table = table.reindex(columns=TICKERS)
    table.columns.name = None
    table.index = pd.to_datetime(table.index).tz_localize(None).normalize()
    table.index.name = "Date"
    return table.sort_index().reset_index()


def main() -> int:
    try:
        prices = flatten(download_prices())
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    prices.to_csv(OUTPUT_PATH, index=False, date_format="%Y-%m-%d")

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", None)

    print("First 5 rows:")
    print(prices.head().to_string(index=False))
    print("\nLast 5 rows:")
    print(prices.tail().to_string(index=False))
    print(
        f"\nDate range: {prices['Date'].min().date()} to "
        f"{prices['Date'].max().date()} ({len(prices)} trading days)"
    )
    print("\nMissing values per ticker:")
    print(prices[TICKERS].isna().sum().to_string())
    print(f"\nSaved to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
