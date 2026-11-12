"""Sector status labels: Leading, Weakening, Improving, or Lagging.

For every trading day from 2019 on, takes each sector's score (the same one
rank_sectors.py computes: average 1, 3 and 6-month return relative to SPY)
and turns it into a relative score: the score minus the average score of all
sectors with data that day. The relative score, and its change versus 20
trading days earlier, give the label:

  Leading    relative score above 0 and change at or above 0
  Weakening  relative score above 0 and change below 0
  Improving  relative score at or below 0 and change above 0
  Lagging    relative score at or below 0 and change at or below 0

Saves output/sector_status_history.csv and output/sector_status_today.json.
"""

import json
import sys
from pathlib import Path

import pandas as pd

from rank_sectors import ROWS_NEEDED, SECTORS, load_prices, rank_sectors

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = PROJECT_ROOT / "output" / "sector_status_history.csv"
TODAY_PATH = PROJECT_ROOT / "output" / "sector_status_today.json"

START = "2019-01-01"
CHANGE_DAYS = 20  # trading days, about 4 weeks
LABELS = ["Leading", "Weakening", "Improving", "Lagging"]

SHARE_YEAR = 2022
CHECK_SECTORS = ["XLE", "XLK", "XLV"]
CHECK_DATES = ["2022-06-15", "2023-06-15"]


def label_for(rel_score: float, change: float) -> str | None:
    if pd.isna(rel_score) or pd.isna(change):
        return None
    if rel_score > 0:
        return "Leading" if change >= 0 else "Weakening"
    return "Improving" if change > 0 else "Lagging"


def daily_scores(prices: pd.DataFrame) -> pd.DataFrame:
    """Score per sector for every day it can be measured (dates x sectors)."""
    rows = {}
    for end in range(ROWS_NEEDED, len(prices) + 1):
        window = prices.iloc[end - ROWS_NEEDED:end]
        # Skip any sector (in practice only XLC, early on) without a full
        # 126 days of history, as rank_history.py does.
        sectors = [s for s in SECTORS if window[s].notna().all()]
        if not sectors:
            continue
        ranked = rank_sectors(window, sectors)
        rows[window.index[-1]] = ranked.set_index("Sector")["Score"]
    return pd.DataFrame(rows).T.reindex(columns=SECTORS)


def days_in_label(labels: pd.Series) -> pd.Series:
    """Consecutive trading days the current label has been held, counting today."""
    run_id = (labels != labels.shift()).cumsum()
    streak = labels.groupby(run_id).cumcount() + 1
    return streak.where(labels.notna())


def build_history(prices: pd.DataFrame) -> pd.DataFrame:
    """Long table: one row per day and sector, from START on."""
    scores = daily_scores(prices)
    # Relative score: each sector against the average of the sectors that
    # have a score that day (the mean skips sectors without data).
    rel_scores = scores.sub(scores.mean(axis=1), axis=0)
    changes = rel_scores - rel_scores.shift(CHANGE_DAYS)

    parts = []
    for sector in SECTORS:
        part = pd.DataFrame({
            "Sector": sector,
            "Score": scores[sector],
            "RelScore": rel_scores[sector],
            "Change": changes[sector],
        }).loc[START:]
        part["Label"] = [label_for(r, c) for r, c in zip(part["RelScore"], part["Change"])]
        # Streaks are counted from the first labelled day in the history.
        part["DaysInLabel"] = days_in_label(part["Label"]).astype("Int64")
        parts.append(part)

    history = pd.concat(parts)
    history.index.name = "Date"
    history = history.reset_index()
    order = {sector: i for i, sector in enumerate(SECTORS)}
    return history.sort_values(
        ["Date", "Sector"], key=lambda col: col.map(order) if col.name == "Sector" else col
    ).reset_index(drop=True)


def today_table(history: pd.DataFrame) -> pd.DataFrame:
    latest = history[history["Date"] == history["Date"].max()]
    if latest["Label"].isna().any():
        missing = latest.loc[latest["Label"].isna(), "Sector"].tolist()
        raise RuntimeError(f"No status for {missing} on the latest day.")
    return latest.sort_values("RelScore", ascending=False).reset_index(drop=True)


def print_today(today: pd.DataFrame) -> None:
    print(f"Sector status as of {today['Date'].iloc[0].date()}")
    print("(percentage points; Rel score = score minus the average sector score;")
    print(" 4wk change = change in Rel score versus 20 trading days earlier)\n")
    shown = today[["Sector", "Score", "RelScore", "Change", "Label", "DaysInLabel"]].rename(
        columns={"RelScore": "Rel score", "Change": "4wk change", "DaysInLabel": "Days in label"}
    )
    print(
        shown.to_string(
            index=False,
            formatters={
                "Score": "{:+.2f}".format,
                "Rel score": "{:+.2f}".format,
                "4wk change": "{:+.2f}".format,
            },
        )
    )


def print_year_shares(history: pd.DataFrame) -> None:
    year = history[history["Date"].dt.year == SHARE_YEAR]
    counts = pd.crosstab(year["Sector"], year["Label"]).reindex(
        index=SECTORS, columns=LABELS, fill_value=0
    )
    shares = counts.div(counts.sum(axis=1), axis=0) * 100
    shares.columns.name = None
    print(f"\nShare of {SHARE_YEAR} trading days in each label, %:")
    print(shares.to_string(float_format="{:.1f}".format))


def print_check_dates(history: pd.DataFrame) -> None:
    latest = str(history["Date"].max().date())
    print("\nLabel on selected dates:")
    for text in [*CHECK_DATES, latest]:
        earlier = history[history["Date"] <= text]
        if earlier.empty:
            print(f"  {text}  no data")
            continue
        day = earlier["Date"].max()
        rows = earlier[earlier["Date"] == day].set_index("Sector")
        note = "" if str(day.date()) == text else f" (using {day.date()})"
        cells = [
            f"{s} {rows.loc[s, 'Label']} "
            f"(rel score {rows.loc[s, 'RelScore']:+.1f}, change {rows.loc[s, 'Change']:+.1f}, "
            f"score {rows.loc[s, 'Score']:+.1f})"
            for s in CHECK_SECTORS
        ]
        print(f"  {text}{note}")
        for cell in cells:
            print(f"    {cell}")


def main() -> int:
    try:
        prices = load_prices(complete_rows_only=False)
        history = build_history(prices)
        today = today_table(history)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(HISTORY_PATH, index=False, date_format="%Y-%m-%d")

    result = {
        "date": str(today["Date"].iloc[0].date()),
        "change_days": CHANGE_DAYS,
        "sectors": [
            {
                "sector": r.Sector,
                "score": round(float(r.Score), 4),
                "rel_score": round(float(r.RelScore), 4),
                "change": round(float(r.Change), 4),
                "label": r.Label,
                "days_in_label": int(r.DaysInLabel),
            }
            for r in today.itertuples(index=False)
        ],
    }
    TODAY_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print_today(today)
    print_year_shares(history)
    print_check_dates(history)

    unlabelled = history[history["Label"].isna()]
    if not unlabelled.empty:
        summary = unlabelled.groupby("Sector")["Date"].agg(["count", "max"])
        print("\nDays without a label (not enough history yet):")
        for sector, row in summary.iterrows():
            print(f"  {sector}: {row['count']} days, through {row['max'].date()}")

    print(f"\nSaved history to {HISTORY_PATH}")
    print(f"Saved today's result to {TODAY_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
