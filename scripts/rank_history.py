"""Weekly history of sector ranks, plus an interactive heatmap.

For the last trading day of every week since 2019-01-01, scores each sector
exactly as rank_sectors.py does (average of the 21, 63, and 126 trading-day
returns relative to SPY) and ranks them 1 to 11.

Saves the ranks to output/rank_history.csv and the heatmap to
output/rank_heatmap.html.
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from rank_sectors import ROWS_NEEDED, SECTORS, load_prices, rank_sectors

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / "output" / "rank_history.csv"
HEATMAP_PATH = PROJECT_ROOT / "output" / "rank_heatmap.html"

HISTORY_START = "2019-01-01"

# Rank 1 (strongest) is green, the middle is a neutral gray, rank 11 is red.
COLORSCALE = [
    [0.0, "#1a7f37"],
    [0.25, "#7cc48d"],
    [0.5, "#ebebe6"],
    [0.75, "#eb8a80"],
    [1.0, "#c02b2b"],
]


def week_end_dates(prices: pd.DataFrame) -> list[pd.Timestamp]:
    """Last trading day of each week (Friday, or earlier if Friday is a holiday).

    The current week is included even if it isn't finished yet, so the final
    column always matches today's ranking.
    """
    days = prices.index.to_series()
    days = days[days >= HISTORY_START]
    return days.groupby(days.dt.to_period("W-FRI")).max().tolist()


def build_history(prices: pd.DataFrame) -> pd.DataFrame:
    """Ranks with week-end dates as rows and sectors as columns."""
    rows = {}
    for day in week_end_dates(prices):
        window = prices.loc[:day].tail(ROWS_NEEDED)
        # Skip any sector (in practice only XLC) without a full 126 days of history.
        sectors = [
            s for s in SECTORS
            if len(window) == ROWS_NEEDED and window[s].notna().all()
        ]
        if not sectors:
            continue
        ranked = rank_sectors(window, sectors)
        rows[day] = ranked.set_index("Sector")["Rank"]

    history = pd.DataFrame(rows).T.reindex(columns=SECTORS).astype("Int64")
    history.index.name = "Date"
    return history


def build_heatmap(history: pd.DataFrame) -> go.Figure:
    # Sectors top to bottom by their current rank.
    order = history.iloc[-1].sort_values().index.tolist()
    ranks = history[order].T.astype(float)
    n = len(SECTORS)

    fig = go.Figure(
        go.Heatmap(
            z=ranks.values,
            x=ranks.columns,
            y=ranks.index,
            zmin=1,
            zmax=n,
            colorscale=COLORSCALE,
            ygap=2,
            hoverongaps=False,
            hovertemplate=(
                "Week ending %{x|%a %b %-d, %Y}<br>"
                "Sector: %{y}<br>"
                "Rank: %{z:.0f}<extra></extra>"
            ),
            colorbar=dict(
                title=dict(text="Rank"),
                tickvals=[1, (n + 1) // 2, n],
                ticktext=["1 strongest", str((n + 1) // 2), f"{n} weakest"],
                outlinewidth=0,
                thickness=14,
                len=0.8,
            ),
        )
    )
    fig.update_layout(
        title=dict(
            text=(
                "Sector rank vs SPY, weekly"
                "<br><sup>Rank of the average 1, 3 and 6-month return relative to SPY. "
                f"Sectors ordered by rank on {history.index[-1].date()}.</sup>"
            ),
            x=0.01,
            xanchor="left",
        ),
        template="plotly_white",
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=13),
        height=560,
        margin=dict(l=70, r=30, t=90, b=50),
        xaxis=dict(showgrid=False, ticks="outside", tickcolor="#cccccc"),
        # First sector in `order` (current rank 1) goes at the top.
        yaxis=dict(autorange="reversed", showgrid=False, type="category"),
        hoverlabel=dict(bgcolor="white", font_size=13),
    )
    return fig


def main() -> int:
    try:
        prices = load_prices(complete_rows_only=False)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    history = build_history(prices)

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(CSV_PATH, date_format="%Y-%m-%d")
    build_heatmap(history).write_html(HEATMAP_PATH, include_plotlyjs="cdn")

    skipped = history.isna().sum()
    skipped = skipped[skipped > 0]

    print(
        f"{len(history)} weeks, {history.index[0].date()} to {history.index[-1].date()}"
    )
    if skipped.empty:
        print("No sector was skipped on any date.")
    else:
        print("Weeks skipped for lack of history:")
        print(skipped.to_string())
    print("\nLatest 5 weeks:")
    print(history.tail().to_string())
    print(f"\nSaved ranks to {CSV_PATH}")
    print(f"Saved heatmap to {HEATMAP_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
