"""Market environment signal: Risk-on, Caution, or Risk-off.

Reads data/prices.csv and data/regime.csv and, for every trading day from
2019 on, checks four warnings:

  1. SPY close below its 200-day simple moving average
  2. credit_spread up more than 0.15 points versus 21 trading days earlier
  3. VIX above 20
  4. VIX above vix3m (3-month volatility)

0 warnings = Risk-on, 1 = Caution, 2 or more = Risk-off. Each day uses the
most recent FRED value dated on or before that day, never a later one.

Saves output/environment_history.csv and output/environment_today.json.
"""

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = PROJECT_ROOT / "data" / "prices.csv"
REGIME_PATH = PROJECT_ROOT / "data" / "regime.csv"
HISTORY_PATH = PROJECT_ROOT / "output" / "environment_history.csv"
TODAY_PATH = PROJECT_ROOT / "output" / "environment_today.json"

START = "2019-01-01"
BENCHMARK = "SPY"
FRED_SERIES = ["credit_spread", "vix", "vix3m"]

SMA_DAYS = 200
SPREAD_LOOKBACK = 21        # trading days
SPREAD_RISE_LIMIT = 0.15    # points
VIX_LIMIT = 20
# Today's result is refused if a FRED series is older than this (calendar days).
MAX_STALE_DAYS = 10

LABELS = ["Risk-on", "Caution", "Risk-off"]
POSTURES = {
    "Risk-on": "Normal position size. Favor calls in leading sectors.",
    "Caution": "Reduce size. Only the strongest setups. Take profits faster.",
    "Risk-off": "Minimal new longs. Small size. Puts in lagging sectors or stay in cash.",
}
WARNING_COLUMNS = {
    "warn_spy_below_sma200": "SPY below its 200-day average",
    "warn_credit_widening": "Credit spread widening",
    "warn_vix_above_20": "VIX above 20",
    "warn_vix_above_vix3m": "VIX above 3-month VIX",
}
CHECK_DATES = [
    "2020-03-16", "2020-06-15", "2022-06-15", "2022-10-14", "2023-07-14", "2024-08-05",
]


def label_for(warnings: int) -> str:
    return LABELS[min(warnings, 2)]


def vol_band(vix: float) -> str:
    if vix < 15:
        return "Calm"
    if vix <= 20:
        return "Normal"
    if vix <= 30:
        return "Elevated"
    return "Stressed"


def load_inputs() -> tuple[pd.Series, pd.DataFrame]:
    for path, script in [(PRICES_PATH, "fetch_prices.py"), (REGIME_PATH, "fetch_regime.py")]:
        if not path.exists():
            raise RuntimeError(f"{path} not found. Run scripts/{script} first.")

    prices = pd.read_csv(PRICES_PATH, parse_dates=["Date"]).set_index("Date").sort_index()
    regime = pd.read_csv(REGIME_PATH, parse_dates=["Date"]).set_index("Date").sort_index()

    if BENCHMARK not in prices.columns:
        raise RuntimeError(f"{BENCHMARK} is missing from {PRICES_PATH.name}.")
    missing = [c for c in FRED_SERIES if c not in regime.columns]
    if missing:
        raise RuntimeError(
            f"Missing columns in {REGIME_PATH.name}: {missing}. Rerun scripts/fetch_regime.py."
        )
    return prices[BENCHMARK].dropna(), regime[FRED_SERIES]


def build_history(spy: pd.Series, regime: pd.DataFrame) -> pd.DataFrame:
    """One row per trading day from START, with values, warnings, and labels."""
    days = spy.index
    table = pd.DataFrame(index=days)
    table["spy"] = spy
    table["spy_sma200"] = spy.rolling(SMA_DAYS).mean()

    for name in FRED_SERIES:
        series = regime[name].dropna()
        # Forward-fill onto trading days: the latest value dated on or before
        # each day. Nothing from a later date can be picked up this way.
        table[name] = series.reindex(days, method="ffill")
        source_dates = pd.Series(series.index, index=series.index)
        table[f"{name}_asof"] = source_dates.reindex(days, method="ffill")

    table["credit_spread_21d_ago"] = table["credit_spread"].shift(SPREAD_LOOKBACK)
    # Rounded so float noise can't tip a change of exactly 0.15 over the limit.
    table["credit_spread_change"] = (
        table["credit_spread"] - table["credit_spread_21d_ago"]
    ).round(4)

    table = table.loc[START:]
    inputs = ["spy", "spy_sma200", *FRED_SERIES, "credit_spread_21d_ago"]
    incomplete = table[table[inputs].isna().any(axis=1)]
    if not incomplete.empty:
        raise RuntimeError(
            f"{len(incomplete)} days from {START} lack data for the warnings, "
            f"first on {incomplete.index[0].date()}."
        )

    table["warn_spy_below_sma200"] = table["spy"] < table["spy_sma200"]
    table["warn_credit_widening"] = table["credit_spread_change"] > SPREAD_RISE_LIMIT
    table["warn_vix_above_20"] = table["vix"] > VIX_LIMIT
    table["warn_vix_above_vix3m"] = table["vix"] > table["vix3m"]
    table["warnings"] = table[list(WARNING_COLUMNS)].sum(axis=1)
    table["label"] = table["warnings"].map(label_for)
    table["vol_band"] = table["vix"].map(vol_band)
    table.index.name = "Date"
    return table


def compare(value: float, other: float) -> str:
    return "above" if value > other else "below" if value < other else "at"


def today_result(history: pd.DataFrame) -> dict:
    """The latest day's result, with the values behind each warning."""
    day = history.index[-1]
    row = history.iloc[-1]

    for name in FRED_SERIES:
        age = (day - row[f"{name}_asof"]).days
        if age > MAX_STALE_DAYS:
            raise RuntimeError(
                f"{name} was last updated {row[f'{name}_asof'].date()}, {age} days "
                f"before {day.date()}. Too stale for today's signal."
            )

    change = row["credit_spread_change"]
    direction = "up" if change > 0 else "down" if change < 0 else "unchanged,"
    warnings = [
        {
            "id": "spy_below_sma200",
            "name": WARNING_COLUMNS["warn_spy_below_sma200"],
            "on": bool(row["warn_spy_below_sma200"]),
            "text": (
                f"SPY {row['spy']:.2f}, {compare(row['spy'], row['spy_sma200'])} "
                f"its 200-day average of {row['spy_sma200']:.2f}"
            ),
            "values": {"spy": row["spy"], "spy_sma200": row["spy_sma200"]},
        },
        {
            "id": "credit_widening",
            "name": WARNING_COLUMNS["warn_credit_widening"],
            "on": bool(row["warn_credit_widening"]),
            "text": (
                f"Credit spread {row['credit_spread']:.2f}, {direction} "
                f"{abs(change):.2f} from {row['credit_spread_21d_ago']:.2f} "
                f"{SPREAD_LOOKBACK} trading days ago (warning above +{SPREAD_RISE_LIMIT:.2f})"
            ),
            "values": {
                "credit_spread": row["credit_spread"],
                "credit_spread_21d_ago": row["credit_spread_21d_ago"],
                "change": change,
            },
        },
        {
            "id": "vix_above_20",
            "name": WARNING_COLUMNS["warn_vix_above_20"],
            "on": bool(row["warn_vix_above_20"]),
            "text": f"VIX {row['vix']:.1f}, {compare(row['vix'], VIX_LIMIT)} {VIX_LIMIT}",
            "values": {"vix": row["vix"]},
        },
        {
            "id": "vix_above_vix3m",
            "name": WARNING_COLUMNS["warn_vix_above_vix3m"],
            "on": bool(row["warn_vix_above_vix3m"]),
            "text": (
                f"VIX {row['vix']:.1f}, {compare(row['vix'], row['vix3m'])} "
                f"3-month VIX {row['vix3m']:.1f}"
            ),
            "values": {"vix": row["vix"], "vix3m": row["vix3m"]},
        },
    ]
    for warning in warnings:
        warning["values"] = {k: round(float(v), 4) for k, v in warning["values"].items()}

    return {
        "date": str(day.date()),
        "label": row["label"],
        "warnings_on": int(row["warnings"]),
        "volatility_band": row["vol_band"],
        "posture": POSTURES[row["label"]],
        "warnings": warnings,
        "series_as_of": {
            "spy": str(day.date()),
            **{name: str(row[f"{name}_asof"].date()) for name in FRED_SERIES},
        },
    }


def print_today(result: dict) -> None:
    print(f"Market environment as of {result['date']}")
    print(f"  Label:      {result['label']} ({result['warnings_on']} of 4 warnings on)")
    print(f"  Volatility: {result['volatility_band']}")
    print(f"  Posture:    {result['posture']}")
    print("  Warnings:")
    for warning in result["warnings"]:
        state = "ON " if warning["on"] else "off"
        print(f"    [{state}] {warning['text']}")
    as_of = ", ".join(f"{name} {day}" for name, day in result["series_as_of"].items())
    print(f"  Data as of: {as_of}")


def print_yearly_shares(history: pd.DataFrame) -> None:
    counts = pd.crosstab(history.index.year, history["label"]).reindex(
        columns=LABELS, fill_value=0
    )
    shares = counts.div(counts.sum(axis=1), axis=0) * 100
    shares.insert(0, "Days", counts.sum(axis=1))
    shares.index.name = "Year"
    print("\nShare of trading days by label, % (2026 is year to date):")
    print(shares.to_string(formatters={label: "{:.1f}".format for label in LABELS}))


def print_check_dates(history: pd.DataFrame) -> None:
    print("\nLabel on selected dates:")
    for text in [*CHECK_DATES, str(history.index[-1].date())]:
        earlier = history.loc[:text]
        if earlier.empty:
            print(f"  {text}  no data")
            continue
        row = earlier.iloc[-1]
        day = earlier.index[-1].date()
        note = "" if str(day) == text else f" (using {day}, the last trading day before)"
        on = [name for column, name in WARNING_COLUMNS.items() if row[column]]
        detail = "; ".join(on) if on else "no warnings"
        print(f"  {text}  {row['label']:<8}  {row['vol_band']:<8}  {detail}{note}")


def main() -> int:
    try:
        spy, regime = load_inputs()
        history = build_history(spy, regime)
        result = today_result(history)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(HISTORY_PATH, date_format="%Y-%m-%d")
    TODAY_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print_today(result)
    print_yearly_shares(history)
    print_check_dates(history)
    print(f"\nSaved history to {HISTORY_PATH}")
    print(f"Saved today's result to {TODAY_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
