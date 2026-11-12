"""Download daily market-regime series from FRED (public CSV link, no API key).

Saves a merged table (Date + one column per series) to data/regime.csv.
Missing days are left blank; gaps are not filled.
"""

import io
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "regime.csv"

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
# FRED series id -> friendly column name
SERIES = {
    "BAA10Y": "credit_spread",     # Moody's Baa corporate yield minus 10-year Treasury
    "T10Y2Y": "curve_10y2y",       # 10-year minus 2-year Treasury yield
    "VIXCLS": "vix",               # VIX
    "DTWEXBGS": "dollar",          # broad US dollar index
}
START = "2018-01-01"
MAX_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 5
TIMEOUT_SECONDS = 30


def download_series(series_id: str, name: str) -> pd.Series:
    """Download one FRED series, retrying on failure or an empty result."""
    url = FRED_URL.format(series=series_id)
    last_error = "unknown error"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            # Use urllib's default User-Agent: FRED stalls requests that send
            # a browser-style or custom one.
            with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
                text = response.read().decode("utf-8")

            # First column is the date, second is the value; "." means missing.
            frame = pd.read_csv(io.StringIO(text), na_values=".")
            if frame.shape[1] == 2 and not frame.empty:
                dates = pd.to_datetime(frame.iloc[:, 0])
                values = pd.to_numeric(frame.iloc[:, 1])
                return pd.Series(values.values, index=dates, name=name)
            last_error = "download came back empty or in an unexpected format"
        except Exception as exc:  # network, HTTP, and parsing errors alike
            last_error = f"{type(exc).__name__}: {exc}"

        print(f"{series_id}: attempt {attempt}/{MAX_ATTEMPTS} failed: {last_error}")
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_WAIT_SECONDS)

    raise RuntimeError(
        f"Download of {series_id} failed after {MAX_ATTEMPTS} attempts: {last_error}"
    )


def main() -> int:
    try:
        columns = [download_series(sid, name) for sid, name in SERIES.items()]
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    # Outer join keeps every date that appears in any series; gaps stay blank.
    table = pd.concat(columns, axis=1, sort=True)
    table = table.loc[START:].dropna(how="all")
    table.index.name = "Date"
    table = table.reset_index()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUTPUT_PATH, index=False, date_format="%Y-%m-%d")

    names = list(SERIES.values())
    print("Last 5 rows:")
    print(table.tail().to_string(index=False))
    print(
        f"\nDate range: {table['Date'].min().date()} to "
        f"{table['Date'].max().date()} ({len(table)} rows)"
    )
    print("\nMissing values per column:")
    print(table[names].isna().sum().to_string())
    print(f"\nSaved to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
