"""Append today's signals to log/signals.csv.

One row per item, each carrying the price date, run date, and the market
environment label and warning count:

  - a "sector" row for every sector: its status label and relative score
  - a "stock" row for every name in the three setup lists, plus the names
    held back for earnings (list "held back"), with its stop and risk %

Rows already logged for the same price date are replaced, so rerunning on
the same day never duplicates anything. Reads the files the other scripts
write to output/, so run those (through sector_stocks.py) first.
"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from build_site import (
    ENVIRONMENT_PATH,
    MARKET_TIMEZONE,
    drill_sectors,
    load_status,
    setup_lists,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = PROJECT_ROOT / "log" / "signals.csv"

COLUMNS = [
    "price_date", "run_date", "env_label", "env_warnings", "item",
    "sector", "sector_label", "rel_score",
    "ticker", "list", "setup", "close", "rel_3m", "dist_ema20", "next_earnings",
    "stop", "risk_pct",
]
# Columns added after the log was started; older files may lack them.
ADDED_COLUMNS = ["stop", "risk_pct"]
HELD_BACK = "held back"


def number(value, decimals: int = 4) -> str:
    """Fixed formatting, so the same data always writes the same text."""
    return "" if pd.isna(value) else f"{float(value):.{decimals}f}"


def stock_row(common: dict, stock, list_name: str) -> dict:
    return {
        **common,
        "item": "stock",
        "sector": stock.Sector,
        "sector_label": stock.SectorLabel,
        "ticker": stock.Ticker,
        "list": list_name,
        "setup": stock.Setup,
        "close": number(stock.Close),
        "rel_3m": number(stock.RelReturn3m),
        "dist_ema20": number(stock.DistEMA20),
        "next_earnings": "" if pd.isna(stock.next_earnings) else str(stock.next_earnings),
        "stop": number(stock.Stop),
        "risk_pct": number(stock.RiskPct),
    }


def todays_rows() -> list[dict]:
    if not ENVIRONMENT_PATH.exists():
        raise RuntimeError(f"{ENVIRONMENT_PATH} not found. Run scripts/environment.py first.")
    environment = json.loads(ENVIRONMENT_PATH.read_text(encoding="utf-8"))
    status = load_status()
    if environment["date"] != status["date"]:
        raise RuntimeError(
            f"Environment is as of {environment['date']} but sector status is as of "
            f"{status['date']}. Rerun the earlier scripts so they agree."
        )

    common = {
        "price_date": status["date"],
        "run_date": datetime.now(MARKET_TIMEZONE).date().isoformat(),
        "env_label": environment["label"],
        "env_warnings": str(environment["warnings_on"]),
    }
    rows = [
        {
            **common,
            "item": "sector",
            "sector": s["sector"],
            "sector_label": s["label"],
            "rel_score": number(s["rel_score"]),
        }
        for s in status["sectors"]
    ]

    for result in setup_lists(drill_sectors(status)):
        for frame, list_name in [
            (result["picks"], result["title"].lower()),
            (result["held_back"], HELD_BACK),
        ]:
            if "Close" not in frame.columns:
                raise RuntimeError(
                    "The stock tables have no Close column. Rerun scripts/sector_stocks.py."
                )
            rows += [stock_row(common, stock, list_name) for stock in frame.itertuples(index=False)]

    return [{column: row.get(column, "") for column in COLUMNS} for row in rows]


def read_log() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    with open(LOG_PATH, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        older = [c for c in COLUMNS if c not in ADDED_COLUMNS]
        if reader.fieldnames not in (COLUMNS, older):
            raise RuntimeError(
                f"{LOG_PATH} has unexpected columns; not touching it. "
                f"Expected: {', '.join(COLUMNS)}"
            )
        # Rows written before a column existed get a blank for it.
        return [{column: row.get(column) or "" for column in COLUMNS} for row in reader]


def main() -> int:
    try:
        new_rows = todays_rows()
        existing = read_log()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    price_date = new_rows[0]["price_date"]
    kept = [row for row in existing if row["price_date"] != price_date]
    replaced = len(existing) - len(kept)
    # Stable sort: dates in order, rows within a date in the order written.
    rows = sorted(kept + new_rows, key=lambda row: row["price_date"])

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    sectors = sum(row["item"] == "sector" for row in new_rows)
    held = sum(row["list"] == HELD_BACK for row in new_rows)
    print(f"Signals for {price_date}: {len(new_rows)} rows "
          f"({sectors} sectors, {len(new_rows) - sectors - held} listed stocks, {held} held back).")
    if replaced:
        print(f"Replaced {replaced} rows already logged for {price_date}.")
    else:
        print(f"No earlier rows for {price_date}; appended.")
    print(f"{LOG_PATH} now has {len(rows)} rows covering "
          f"{len({row['price_date'] for row in rows})} price date(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
