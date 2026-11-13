"""Download daily adjusted close prices for SPY and the sector ETFs.

Saves a flat table (Date + one column per ticker) to data/prices.csv.
"""

import sys
import tempfile
import time
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "prices.csv"

TICKERS = [
    "SPY", "XLK", "XLF", "XLE", "XLV", "XLY",
    "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC",
]
START = "2018-01-01"
RETRY_WAITS = [30, 60, 120]  # seconds to wait before each retry
MAX_STALE_DAYS = 5           # the latest price must be within this many calendar days
MARKET_TIMEZONE = ZoneInfo("America/New_York")
CLOSE_CUTOFF = dt_time(16, 15)  # before this (US Eastern), today's bar isn't final


def use_temporary_yfinance_cache() -> tempfile.TemporaryDirectory:
    """Point yfinance's cache at a fresh temporary folder for this run.

    Nothing is shared with other runs or processes, which avoids "database is
    locked" errors from its SQLite cache. The folder is removed when the
    returned object is cleaned up or the script exits.
    """
    folder = tempfile.TemporaryDirectory(prefix="yfinance-cache-", ignore_cleanup_errors=True)
    yf.set_tz_cache_location(folder.name)
    return folder


def data_problem(closes: pd.DataFrame | None) -> str | None:
    """Describe what is wrong with a download, or return None if it is usable.

    Every ticker must have prices, and each one's latest price must be recent.
    """
    if closes is None or closes.empty:
        return "download came back empty"
    empty = [t for t in TICKERS if t not in closes.columns or closes[t].dropna().empty]
    if empty:
        return f"no data for {', '.join(empty)}"
    today = datetime.now(MARKET_TIMEZONE).date()
    stale = []
    for ticker in TICKERS:
        last = closes[ticker].dropna().index[-1].date()
        if (today - last).days > MAX_STALE_DAYS:
            stale.append(f"{ticker} (last {last})")
    if stale:
        return f"latest price is more than {MAX_STALE_DAYS} days old for {', '.join(stale)}"
    return None


def download_prices() -> pd.DataFrame:
    """Download closes for all tickers.

    Retries, with longer and longer waits, when the download fails, comes
    back empty, is missing a ticker, or is stale. Raises if it never passes.
    """
    # yfinance's `end` is exclusive, so ask for tomorrow to include today.
    end = (date.today() + timedelta(days=1)).isoformat()
    attempts = len(RETRY_WAITS) + 1
    problem = "unknown error"

    for attempt in range(1, attempts + 1):
        try:
            raw = yf.download(
                TICKERS,
                start=START,
                end=end,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            closes = raw["Close"] if raw is not None and not raw.empty else None
            problem = data_problem(closes)
            if problem is None:
                return closes
        except Exception as exc:  # yfinance raises a variety of error types
            problem = f"{type(exc).__name__}: {exc}"

        print(f"Attempt {attempt}/{attempts} failed: {problem}")
        if attempt < attempts:
            wait = RETRY_WAITS[attempt - 1]
            print(f"Waiting {wait} seconds before retrying.")
            time.sleep(wait)

    raise RuntimeError(
        f"ERROR: price download failed after {attempts} attempts: {problem}. "
        f"{OUTPUT_PATH.name} was not written."
    )


def flatten(closes: pd.DataFrame) -> pd.DataFrame:
    """Turn the yfinance result into Date + one plain column per ticker."""
    table = closes.dropna(how="all").copy()
    table = table.reindex(columns=TICKERS)
    table.columns.name = None
    table.index = pd.to_datetime(table.index).tz_localize(None).normalize()
    table.index.name = "Date"
    return table.sort_index().reset_index()


def drop_unfinished_day(prices: pd.DataFrame) -> pd.DataFrame:
    """Drop today's row if the US market hasn't closed yet, keeping completed closes only."""
    now = datetime.now(MARKET_TIMEZONE)
    if prices.empty or now.time() >= CLOSE_CUTOFF:
        return prices
    if prices["Date"].iloc[-1].date() != now.date():
        return prices
    print(
        f"Note: dropped today's row ({now.date()}); it is {now:%H:%M} US Eastern, "
        f"before the {CLOSE_CUTOFF:%H:%M} cutoff, so today's close isn't final."
    )
    return prices.iloc[:-1]


def main() -> int:
    cache = use_temporary_yfinance_cache()  # kept alive until the script ends
    try:
        prices = drop_unfinished_day(flatten(download_prices()))
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    # Write to a temporary file and swap it in, so a failure part-way through
    # can never leave an empty or half-written prices.csv behind.
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_PATH.with_suffix(".csv.tmp")
    prices.to_csv(temporary, index=False, date_format="%Y-%m-%d")
    temporary.replace(OUTPUT_PATH)

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
