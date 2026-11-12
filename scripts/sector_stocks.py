"""Rank the top holdings of one sector ETF against the ETF itself.

Usage:  python scripts/sector_stocks.py XLV

Takes the fund's 25 largest holdings (from the SPDR daily holdings file, or
data/holdings_fallback.json if that download fails), downloads about a year of
prices, and for each stock reports its 3-month return relative to the sector
ETF, three trend flags, its distance from the 20 and 50-day EMA, a setup
tag, and its next earnings date. Saves the table to output/stocks_<TICKER>.csv.
"""

import argparse
import io
import json
import sys
import time
import urllib.request
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FALLBACK_PATH = PROJECT_ROOT / "data" / "holdings_fallback.json"
OUTPUT_DIR = PROJECT_ROOT / "output"

HOLDINGS_URL = (
    "https://www.ssga.com/us/en/intermediary/library-content/products/"
    "fund-data/etfs/us/holdings-daily-us-en-{ticker}.xlsx"
)
SECTORS = [
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP",
    "XLI", "XLB", "XLU", "XLRE", "XLC",
]
TOP_N = 25
# Plain share tickers such as "LLY" or "BRK.B"; this leaves out the cash,
# futures, and placeholder rows in the holdings file.
STOCK_TICKER_PATTERN = r"[A-Z]+(\.[A-Z])?"

HISTORY_DAYS = 400       # calendar days of prices, a bit over one year
RETURN_WINDOW = 63       # trading days, about 3 months
FAST_EMA = 20
SLOW_EMA = 50

EVENT_MOVER_RETURN = 50   # relative 3-month return above this, in % points
EXTENDED_DISTANCE = 10    # % above the 50 EMA
PULLBACK_DISTANCE = 2     # % either side of the 20 EMA

MAX_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 5
TIMEOUT_SECONDS = 30

EARNINGS_PAUSE_SECONDS = 0.4   # pause between earnings lookups, to avoid rate limits
EARNINGS_SOON_DAYS = 14        # calendar days
MARKET_TIMEZONE = ZoneInfo("America/New_York")
CLOSE_CUTOFF = dt_time(16, 15)  # before this (US Eastern), today's bar isn't final


def download_holdings(sector: str) -> pd.DataFrame:
    """Top holdings from the SPDR daily holdings Excel file (Ticker, Weight)."""
    url = HOLDINGS_URL.format(ticker=sector.lower())
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
        content = response.read()

    raw = pd.read_excel(io.BytesIO(content), header=None)
    # The table starts a few rows down, under a row holding the column names.
    is_header = raw.apply(
        lambda row: {"Ticker", "Weight"} <= set(row.astype(str)), axis=1
    )
    if not is_header.any():
        raise ValueError("no Ticker/Weight header row in the holdings file")
    header_row = is_header.idxmax()

    table = raw.iloc[header_row + 1:].copy()
    table.columns = raw.iloc[header_row].astype(str)
    table = table[["Ticker", "Weight"]]
    table["Ticker"] = table["Ticker"].astype(str).str.strip()
    table["Weight"] = pd.to_numeric(table["Weight"], errors="coerce")
    table = table[table["Ticker"].str.fullmatch(STOCK_TICKER_PATTERN)]
    table = table.dropna(subset=["Weight"])
    if table.empty:
        raise ValueError("no stock holdings found in the holdings file")
    return table.nlargest(TOP_N, "Weight").reset_index(drop=True)


def fallback_holdings(sector: str) -> pd.DataFrame:
    """Top holdings from the hand-kept list in data/holdings_fallback.json."""
    with open(FALLBACK_PATH) as handle:
        entries = json.load(handle)["sectors"][sector]
    table = pd.DataFrame(entries).rename(columns={"ticker": "Ticker", "weight": "Weight"})
    return table.nlargest(TOP_N, "Weight").reset_index(drop=True)


def get_holdings(sector: str) -> tuple[pd.DataFrame, str]:
    """Return the holdings and a description of where they came from."""
    try:
        return download_holdings(sector), "SPDR daily holdings file"
    except Exception as exc:  # network, HTTP, and file-format errors alike
        print(f"SPDR holdings download failed: {type(exc).__name__}: {exc}")
    return fallback_holdings(sector), f"fallback list ({FALLBACK_PATH.name})"


def download_prices(tickers: list[str]) -> pd.DataFrame:
    """Adjusted closes, one column per ticker, retrying on failure or empty result."""
    start = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat()
    # yfinance's `end` is exclusive, so ask for tomorrow to include today.
    end = (date.today() + timedelta(days=1)).isoformat()
    last_error = "unknown error"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = yf.download(
                tickers, start=start, end=end, auto_adjust=True, progress=False
            )
            if raw is not None and not raw.empty:
                closes = raw["Close"]
                if not closes.dropna(how="all").empty:
                    return closes.dropna(how="all").sort_index()
            last_error = "download came back empty"
        except Exception as exc:  # yfinance raises a variety of error types
            last_error = f"{type(exc).__name__}: {exc}"

        print(f"Price download attempt {attempt}/{MAX_ATTEMPTS} failed: {last_error}")
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_WAIT_SECONDS)

    raise RuntimeError(
        f"Price download failed after {MAX_ATTEMPTS} attempts: {last_error}"
    )


def drop_unfinished_day(prices: pd.DataFrame) -> pd.DataFrame:
    """Drop today's row if the US market hasn't closed yet, keeping completed closes only."""
    now = datetime.now(MARKET_TIMEZONE)
    if prices.empty or now.time() >= CLOSE_CUTOFF:
        return prices
    if prices.index[-1].date() != now.date():
        return prices
    print(
        f"Note: dropped today's row ({now.date()}); it is {now:%H:%M} US Eastern, "
        f"before the {CLOSE_CUTOFF:%H:%M} cutoff, so today's close isn't final."
    )
    return prices.iloc[:-1]


def window_return(series: pd.Series) -> float:
    """Return over the last RETURN_WINDOW trading days, or NaN if too short."""
    if len(series) <= RETURN_WINDOW:
        return float("nan")
    return series.iloc[-1] / series.iloc[-1 - RETURN_WINDOW] - 1


def setup_tag(rel_return: float, dist_fast: float, dist_slow: float, fast_above_slow) -> str:
    """Setup label from the first rule that matches.

    Distances are the close's % distance from the 20 and 50 EMA. Missing
    values (too little history) fail every comparison and fall through to "Mixed".
    """
    if rel_return > EVENT_MOVER_RETURN:
        return "Event mover"
    if dist_slow < 0:
        return "Breaking down"
    if dist_slow > EXTENDED_DISTANCE and fast_above_slow:
        return "Extended"
    if dist_slow > 0 and fast_above_slow and abs(dist_fast) <= PULLBACK_DISTANCE:
        return "Pullback"
    if dist_fast > 0 and dist_slow > 0 and fast_above_slow:
        return "Trending"
    return "Mixed"


def analyse(holdings: pd.DataFrame, prices: pd.DataFrame, sector: str):
    """Build the ranked table. Returns (table, tickers skipped for lack of prices)."""
    sector_return = window_return(prices[sector].dropna())
    rows, skipped = [], []

    for holding in holdings.itertuples():
        yahoo_ticker = holding.Ticker.replace(".", "-")
        series = prices[yahoo_ticker].dropna() if yahoo_ticker in prices else pd.Series()
        if series.empty:
            skipped.append(holding.Ticker)
            continue

        price = series.iloc[-1]
        fast = series.ewm(span=FAST_EMA, adjust=False).mean().iloc[-1]
        slow = series.ewm(span=SLOW_EMA, adjust=False).mean().iloc[-1]
        has_fast = len(series) >= FAST_EMA
        has_slow = len(series) >= SLOW_EMA
        rel_return = (window_return(series) - sector_return) * 100
        dist_fast = (price / fast - 1) * 100 if has_fast else float("nan")
        dist_slow = (price / slow - 1) * 100 if has_slow else float("nan")
        fast_above_slow = bool(fast > slow) if has_slow else None
        rows.append({
            "Ticker": holding.Ticker,
            "Close": price,
            "Weight": holding.Weight,
            "RelReturn3m": rel_return,
            "AboveEMA20": bool(price > fast) if has_fast else None,
            "AboveEMA50": bool(price > slow) if has_slow else None,
            "EMA20AboveEMA50": fast_above_slow,
            "DistEMA20": dist_fast,
            "DistEMA50": dist_slow,
            "Setup": setup_tag(rel_return, dist_fast, dist_slow, fast_above_slow),
        })

    table = pd.DataFrame(rows).sort_values(
        "RelReturn3m", ascending=False, na_position="last"
    )
    table.insert(0, "Rank", range(1, len(table) + 1))
    return table.reset_index(drop=True), skipped


def upcoming(dates, today: date) -> date | None:
    """Earliest of the given dates that is today or later."""
    days = [d.date() if hasattr(d, "date") else d for d in dates]
    days = sorted(d for d in days if d >= today)
    return days[0] if days else None


def next_earnings_date(ticker: str, today: date) -> tuple[date | None, str]:
    """Next earnings date from Yahoo, and where it came from.

    Returns (date, source) or (None, reason it is missing). Never raises:
    earnings data is a nice-to-have and must not stop the script.
    """
    stock = yf.Ticker(ticker.replace(".", "-"))
    reason = "no date listed"
    try:
        calendar = stock.calendar
        dates = calendar.get("Earnings Date") if isinstance(calendar, dict) else None
        if dates:
            if not isinstance(dates, (list, tuple)):
                dates = [dates]
            day = upcoming(dates, today)
            if day:
                return day, "calendar"
            reason = "only past dates listed"
    except Exception as exc:  # network errors, rate limits, format changes
        reason = f"lookup failed ({type(exc).__name__})"

    # Right after a report Yahoo's calendar still shows the old date. Its
    # earnings history table usually already has the next (projected) one.
    try:
        time.sleep(EARNINGS_PAUSE_SECONDS)
        history = stock.get_earnings_dates(limit=8)
        if history is not None and not history.empty:
            day = upcoming(history.index, today)
            if day:
                return day, "earnings history"
    except Exception as exc:
        reason = f"lookup failed ({type(exc).__name__})"
    return None, reason


def add_earnings(table: pd.DataFrame) -> pd.DataFrame:
    """Add next_earnings and earnings_soon columns, and print the coverage."""
    today = datetime.now(MARKET_TIMEZONE).date()
    found, sources, reasons = [], {}, {}
    for i, ticker in enumerate(table["Ticker"]):
        if i:
            time.sleep(EARNINGS_PAUSE_SECONDS)
        day, detail = next_earnings_date(ticker, today)
        found.append(day)
        if day is None:
            reasons.setdefault(detail, []).append(ticker)
        else:
            sources[detail] = sources.get(detail, 0) + 1

    table = table.copy()
    table["next_earnings"] = [d.isoformat() if d else None for d in found]
    table["earnings_soon"] = [
        d is not None and (d - today).days <= EARNINGS_SOON_DAYS for d in found
    ]

    blank = sum(d is None for d in found)
    print(f"\nEarnings dates: {len(found) - blank} of {len(found)} stocks have a date, {blank} blank.")
    for source, count in sources.items():
        print(f"  {count} from Yahoo's {source}")
    for reason, tickers in reasons.items():
        print(f"  Blank, {reason}: {', '.join(tickers)}")
    return table


def print_table(table: pd.DataFrame) -> None:
    def flag(value):
        return "n/a" if value is None or pd.isna(value) else ("yes" if value else "no")

    shown = table.rename(columns={
        "Weight": "Weight %",
        "RelReturn3m": "Rel 3m %",
        "AboveEMA20": ">EMA20",
        "AboveEMA50": ">EMA50",
        "EMA20AboveEMA50": "EMA20>EMA50",
        "DistEMA20": "vs EMA20 %",
        "DistEMA50": "vs EMA50 %",
        "next_earnings": "Next earnings",
        "earnings_soon": "Soon",
    })

    def signed(value):
        return "n/a" if pd.isna(value) else f"{value:+.1f}"

    print(
        shown.to_string(
            index=False,
            na_rep="n/a",
            formatters={
                "Weight %": "{:.1f}".format,
                "Close": "{:.2f}".format,
                "Rel 3m %": signed,
                "vs EMA20 %": signed,
                "vs EMA50 %": signed,
                ">EMA20": flag,
                ">EMA50": flag,
                "EMA20>EMA50": flag,
                "Next earnings": lambda v: "unknown" if pd.isna(v) else str(v),
                "Soon": lambda v: "yes" if v else "",
            },
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("sector", help="sector ETF ticker, one of: " + ", ".join(SECTORS))
    sector = parser.parse_args().sector.upper()
    if sector not in SECTORS:
        parser.error(f"unknown sector '{sector}'. Choose one of: {', '.join(SECTORS)}")

    try:
        holdings, source = get_holdings(sector)
        print(f"Holdings source: {source}")
        yahoo_tickers = [t.replace(".", "-") for t in holdings["Ticker"]]
        prices = drop_unfinished_day(download_prices([sector, *yahoo_tickers]))
        if sector not in prices or prices[sector].dropna().empty:
            raise RuntimeError(f"No price data for {sector} itself.")
    except (RuntimeError, OSError, KeyError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    table, skipped = analyse(holdings, prices, sector)
    if table.empty:
        print("No holdings had price data.", file=sys.stderr)
        return 1
    table = add_earnings(table)

    output_path = OUTPUT_DIR / f"stocks_{sector}.csv"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(output_path, index=False)

    print(
        f"\n{sector}: top {len(holdings)} holdings by weight, ranked by 3-month "
        f"return relative to {sector}, as of {prices.index[-1].date()}\n"
    )
    print_table(table)
    if skipped:
        print(f"\nSkipped (no price data): {', '.join(skipped)}")
    else:
        print("\nNo tickers were skipped.")
    print(f"Saved to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
