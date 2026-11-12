"""Build the landing page for the published site: output/index.html.

Shows the run date, the market environment, sector status, today's setups,
the sector ranking, a link to the dashboard, and the stock tables for the
scanned sectors (the strongest Leading and weakest Lagging ones). Reads the
files the other scripts write to output/, so run those first.
"""

import argparse
import json
import sys
from datetime import date, datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
RANKS_PATH = OUTPUT_DIR / "ranks_today.csv"
ENVIRONMENT_PATH = OUTPUT_DIR / "environment_today.json"
STATUS_PATH = OUTPUT_DIR / "sector_status_today.json"
PRICES_PATH = PROJECT_ROOT / "data" / "prices.csv"
DASHBOARD_NAME = "dashboard.html"
INDEX_PATH = OUTPUT_DIR / "index.html"

LEADING_SECTORS = 3      # strongest Leading sectors to scan for stocks
LAGGING_SECTORS = 2      # weakest Lagging sectors to scan for stocks
BORDERLINE_SCORE = 1     # relative score within this many points of zero
BORDERLINE_DAYS = 5      # or label held for fewer than this many days
WAIT_LIST_LIMIT = 10     # names shown under "Wait for pullback"
PUT_LIST_LIMIT = 10      # names shown under "Put ideas"
EARNINGS_SOON_DAYS = 14  # highlight earnings within this many calendar days
EARNINGS_HOLD_DAYS = 7   # hold back Long ideas with earnings this close
# Second share class -> the class to keep when both are in a setup list
DUPLICATE_SHARE_CLASSES = {"GOOG": "GOOGL", "NWS": "NWSA", "FOX": "FOXA"}
MARKET_TIMEZONE = ZoneInfo("America/New_York")

SECTOR_NAMES = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}

# Status label -> guidance line, in display order
STATUS_GUIDANCE = {
    "Leading": "Look for longs here",
    "Improving": "Early rotation, watch for entries",
    "Weakening": "Tighten stops, no new longs",
    "Lagging": "Avoid longs, puts candidates",
}

STYLE = """
:root { color-scheme: light dark; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.45;
  max-width: 46rem;
  margin: 0 auto;
  padding: 1rem;
}
h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.2rem; margin-top: 2rem; }
.meta, .note { color: GrayText; font-size: 0.9rem; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
th, td { padding: 0.35rem 0.3rem; text-align: right; white-space: nowrap; }
th:nth-child(-n+2), td:nth-child(-n+2), td.name, th.name { text-align: left; }
th { border-bottom: 2px solid GrayText; }
td { border-bottom: 1px solid color-mix(in srgb, GrayText 30%, transparent); }
td.name { white-space: normal; }
.env {
  border: 1px solid GrayText;
  border-left: 0.5rem solid var(--env-color);
  border-radius: 0.4rem;
  padding: 0.75rem 1rem;
  margin-bottom: 1.5rem;
}
.env-risk-on { --env-color: #1a7f37; --env-text: #ffffff; }
.env-caution { --env-color: #f0a500; --env-text: #1a1a1a; }
.env-risk-off { --env-color: #c02b2b; --env-text: #ffffff; }
.env-heading { margin: 0 0 0.4rem; font-size: 0.9rem; color: GrayText; }
.env-label {
  display: inline-block;
  padding: 0.15rem 0.7rem;
  border-radius: 0.3rem;
  background: var(--env-color);
  color: var(--env-text);
  font-size: 1.4rem;
  font-weight: 700;
}
.env-band { margin-left: 0.5rem; white-space: nowrap; }
.env-posture { margin: 0.6rem 0; font-weight: 600; }
.env ul { list-style: none; margin: 0.6rem 0 0.4rem; padding: 0; }
.env li { display: flex; gap: 0.6rem; align-items: baseline; padding: 0.2rem 0; }
.env .state {
  flex: none;
  width: 2.4rem;
  text-align: center;
  border: 1px solid GrayText;
  border-radius: 0.3rem;
  font-size: 0.8rem;
  font-weight: 700;
}
.env .state.on { background: #c02b2b; border-color: #c02b2b; color: #ffffff; }
.env .note { margin: 0.4rem 0 0; }
.status h3, .setups h3 { font-size: 1.05rem; margin: 1.2rem 0 0; }
.setups h3 + .note { margin: 0.1rem 0 0.3rem; }
.setups .table-wrap + .note { margin: 0.3rem 0 0; }
.earn-soon {
  padding: 0 0.3rem;
  border-radius: 0.3rem;
  background: #f0a500;
  color: #1a1a1a;
  font-weight: 600;
}
.tag {
  display: inline-block;
  margin-left: 0.3rem;
  padding: 0 0.35rem;
  border: 1px solid GrayText;
  border-radius: 0.3rem;
  font-size: 0.75rem;
  white-space: nowrap;
}
.status .guidance { margin: 0.1rem 0 0.3rem; font-weight: 600; }
.button {
  display: inline-block;
  margin: 0.5rem 0;
  padding: 0.6rem 1rem;
  border: 1px solid GrayText;
  border-radius: 0.4rem;
  text-decoration: none;
  font-weight: 600;
}
"""


def signed(value: float, decimals: int = 1) -> str:
    return "n/a" if pd.isna(value) else f"{value:+.{decimals}f}"


def days_to_earnings(value) -> int | None:
    """Calendar days from today (US Eastern) to an earnings date; None if blank."""
    if pd.isna(value):
        return None
    today = datetime.now(MARKET_TIMEZONE).date()
    return (date.fromisoformat(str(value)) - today).days


def earnings_cell(value) -> str:
    """Earnings date with days away, e.g. "Jan 20 (69d)"; amber when close."""
    days = days_to_earnings(value)
    if days is None:
        return "unknown"
    day = date.fromisoformat(str(value))
    when = "today" if days == 0 else f"{days}d" if days > 0 else f"{-days}d ago"
    text = f"{day:%b} {day.day} ({when})"
    if 0 <= days <= EARNINGS_SOON_DAYS:
        return f'<span class="earn-soon">{text}</span>'
    return text


def flag(value) -> str:
    if pd.isna(value):
        return "n/a"
    return "yes" if str(value).strip().lower() == "true" else "no"


def html_table(headers: list[str], rows: list[list[str]], name_column: int | None = None) -> str:
    """Render an HTML table. Cell values must already be HTML-safe strings."""
    head = "".join(
        f'<th class="name">{escape(h)}</th>' if i == name_column else f"<th>{escape(h)}</th>"
        for i, h in enumerate(headers)
    )
    body = []
    for row in rows:
        cells = "".join(
            f'<td class="name">{cell}</td>' if i == name_column else f"<td>{cell}</td>"
            for i, cell in enumerate(row)
        )
        body.append(f"<tr>{cells}</tr>")
    return (
        '<div class="table-wrap"><table>\n'
        f"<thead><tr>{head}</tr></thead>\n"
        "<tbody>\n" + "\n".join(body) + "\n</tbody>\n"
        "</table></div>"
    )


def ranking_section(ranks: pd.DataFrame) -> str:
    rows = [
        [
            str(r.Rank),
            escape(r.Sector),
            escape(SECTOR_NAMES.get(r.Sector, "")),
            signed(r["1m"]),
            signed(r["3m"]),
            signed(r["6m"]),
            signed(r.Score, 2),
        ]
        for _, r in ranks.iterrows()
    ]
    return (
        "<h2>Sector ranking</h2>\n"
        '<p class="note">Return minus SPY\'s return over 1, 3 and 6 months, in '
        "percentage points. Score is the average of the three.</p>\n"
        + html_table(["#", "ETF", "Sector", "1m", "3m", "6m", "Score"], rows, name_column=2)
    )


def load_status() -> dict:
    if not STATUS_PATH.exists():
        raise RuntimeError(f"{STATUS_PATH} not found. Run scripts/sector_status.py first.")
    return json.loads(STATUS_PATH.read_text(encoding="utf-8"))


def drill_sectors(status: dict) -> list[dict]:
    """Sectors whose stocks are scanned: the strongest Leading and weakest Lagging.

    The workflow runs sector_stocks.py for exactly this list
    (python scripts/build_site.py --list-sectors).
    """
    leading = [s for s in status["sectors"] if s["label"] == "Leading"]
    lagging = [s for s in status["sectors"] if s["label"] == "Lagging"]
    leading.sort(key=lambda s: s["rel_score"], reverse=True)
    lagging.sort(key=lambda s: s["rel_score"])
    return leading[:LEADING_SECTORS] + lagging[:LAGGING_SECTORS]


def load_stocks(sector: str) -> pd.DataFrame:
    path = OUTPUT_DIR / f"stocks_{sector}.csv"
    if not path.exists():
        raise RuntimeError(
            f"{path} not found. Run scripts/sector_stocks.py {sector} first."
        )
    stocks = pd.read_csv(path)
    missing = [c for c in ["Setup", "DistEMA20", "next_earnings"] if c not in stocks.columns]
    if missing:
        raise RuntimeError(
            f"{path} has no {missing} column. Rerun scripts/sector_stocks.py {sector}."
        )
    return stocks


def setups_section(drilled: list[dict]) -> str:
    """Trade idea lists built from the setup tags of the scanned sectors."""
    frames = []
    for entry in drilled:
        stocks = load_stocks(entry["sector"])
        stocks["Sector"] = entry["sector"]
        stocks["SectorLabel"] = entry["label"]
        frames.append(stocks)
    stocks = pd.concat(frames) if frames else pd.DataFrame(
        columns=[
            "Ticker", "Sector", "SectorLabel", "RelReturn3m", "DistEMA20", "Setup",
            "next_earnings",
        ]
    )

    def idea_list(
        title: str,
        note: str,
        label: str,
        setups: list[str],
        long_side: bool,
        limit: int | None = None,
        below_fast_ema: bool = False,
        hold_for_earnings: bool = False,
    ) -> str:
        """One list. Long-side lists keep relative return above 0, strongest
        first; put-side lists keep it below 0, weakest first."""
        picks = stocks[(stocks["SectorLabel"] == label) & stocks["Setup"].isin(setups)]
        dropped = []  # reasons, with counts, for the line under the list

        keep = picks["RelReturn3m"] > 0 if long_side else picks["RelReturn3m"] < 0
        if (~keep).any():
            side = "at or below" if long_side else "at or above"
            dropped.append(f"{(~keep).sum()} with relative 3-month return {side} 0")
        picks = picks[keep]

        if below_fast_ema:
            keep = picks["DistEMA20"] < 0
            if (~keep).any():
                dropped.append(f"{(~keep).sum()} with the close at or above the 20 EMA")
            picks = picks[keep]

        # One share class per company: drop the second class when both are here.
        present = set(picks["Ticker"])
        duplicates = [
            t for t in picks["Ticker"]
            if t in DUPLICATE_SHARE_CLASSES and DUPLICATE_SHARE_CLASSES[t] in present
        ]
        if duplicates:
            dropped.append(
                f"{len(duplicates)} second share class ({', '.join(duplicates)})"
            )
            picks = picks[~picks["Ticker"].isin(duplicates)]

        held_back = picks.iloc[0:0]
        if hold_for_earnings:
            days = picks["next_earnings"].map(days_to_earnings)
            close = days.between(0, EARNINGS_HOLD_DAYS)
            held_back, picks = picks[close], picks[~close]

        picks = picks.sort_values("RelReturn3m", ascending=not long_side)
        if limit is not None and len(picks) > limit:
            which = "strongest" if long_side else "weakest"
            dropped.append(f"{len(picks) - limit} beyond the {limit} {which}")
            picks = picks.head(limit)

        filtered = (
            f'<p class="note">Filtered out: {escape("; ".join(dropped))}.</p>'
            if dropped
            else '<p class="note">Nothing filtered out.</p>'
        )
        if not held_back.empty:
            names = ", ".join(
                f"{escape(str(r.Ticker))} ({date.fromisoformat(r.next_earnings):%b} "
                f"{date.fromisoformat(r.next_earnings).day})"
                for r in held_back.itertuples(index=False)
            )
            filtered = f"<p>Held back for earnings: {names}</p>\n" + filtered
        heading = f"<h3>{escape(title)} ({len(picks)})</h3>\n<p class=\"note\">{escape(note)}</p>\n"
        if picks.empty:
            return heading + "<p>None today</p>\n" + filtered
        headers = ["Ticker", "Sector", "Rel 3m", "vs 20 EMA", "Earnings"]
        rows = [
            [
                escape(str(r.Ticker)),
                escape(r.Sector),
                signed(r.RelReturn3m),
                "n/a" if pd.isna(r.DistEMA20) else f"{r.DistEMA20:+.1f}%",
                earnings_cell(r.next_earnings),
            ]
            for r in picks.itertuples(index=False)
        ]
        if len(setups) > 1:
            headers.insert(4, "Setup")
            for row, r in zip(rows, picks.itertuples(index=False)):
                row.insert(4, escape(r.Setup))
        return heading + html_table(headers, rows) + "\n" + filtered

    scanned = ", ".join(f"{e['sector']} ({e['label']})" for e in drilled) or "none"
    return (
        '<section class="setups">\n'
        "<h2>Setups today</h2>\n"
        f'<p class="note">From the largest holdings of the scanned sectors: {escape(scanned)}. '
        "Rel 3m is the 3-month return minus the sector ETF's return (percentage points); "
        "vs 20 EMA is the close's distance from its 20-day EMA. Earnings is the next "
        f"report date and how many days away it is, highlighted within "
        f"{EARNINGS_SOON_DAYS} days.</p>\n"
        + idea_list(
            "Long ideas",
            "Pullback stocks in Leading sectors, beating their sector over 3 months.",
            "Leading", ["Pullback"], long_side=True, hold_for_earnings=True,
        )
        + "\n"
        + idea_list(
            "Wait for pullback",
            f"Extended or Trending stocks in Leading sectors, beating their sector "
            f"over 3 months. The {WAIT_LIST_LIMIT} strongest.",
            "Leading", ["Extended", "Trending"], long_side=True, limit=WAIT_LIST_LIMIT,
        )
        + "\n"
        + idea_list(
            "Put ideas",
            f"Breaking down stocks in Lagging sectors, trailing their sector over "
            f"3 months and below the 20 EMA. The {PUT_LIST_LIMIT} weakest.",
            "Lagging", ["Breaking down"], long_side=False, limit=PUT_LIST_LIMIT,
            below_fast_ema=True, hold_for_earnings=True,
        )
        + "\n</section>"
    )


def stocks_section(entry: dict) -> str:
    sector = entry["sector"]
    stocks = load_stocks(sector)
    rows = [
        [
            str(s.Rank),
            escape(str(s.Ticker)),
            f"{s.Weight:.1f}",
            signed(s.RelReturn3m),
            flag(s.AboveEMA20),
            flag(s.AboveEMA50),
            flag(s.EMA20AboveEMA50),
            escape(str(s.Setup)),
            earnings_cell(s.next_earnings),
        ]
        for s in stocks.itertuples(index=False)
    ]
    name = SECTOR_NAMES.get(sector, "")
    return (
        f"<h2>{escape(sector)} {escape(name)} ({escape(entry['label'])}): top holdings</h2>\n"
        f'<p class="note">Largest holdings, ranked by 3-month return minus '
        f"{escape(sector)}'s return (percentage points). The next three columns "
        "show whether the price is above its 20-day and 50-day EMA, and whether "
        "the 20-day is above the 50-day.</p>\n"
        + html_table(
            ["#", "Ticker", "Wt %", "Rel 3m", ">20d", ">50d", "20>50", "Setup", "Earnings"],
            rows,
        )
    )


def environment_section() -> str:
    """The market environment box, from output/environment_today.json."""
    if not ENVIRONMENT_PATH.exists():
        raise RuntimeError(
            f"{ENVIRONMENT_PATH} not found. Run scripts/environment.py first."
        )
    env = json.loads(ENVIRONMENT_PATH.read_text(encoding="utf-8"))

    css_class = "env-" + env["label"].lower().replace(" ", "-")
    items = []
    for warning in env["warnings"]:
        state = '<span class="state on">ON</span>' if warning["on"] else '<span class="state">off</span>'
        items.append(f"<li>{state}<span>{escape(warning['text'])}</span></li>")
    as_of = ", ".join(
        f"{escape(name.replace('_', ' '))} {escape(day)}"
        for name, day in env["series_as_of"].items()
    )
    return (
        f'<section class="env {css_class}">\n'
        f'<p class="env-heading">Market environment, as of the {escape(env["date"])} close</p>\n'
        f'<p><span class="env-label">{escape(env["label"])}</span>'
        f'<span class="env-band">Volatility: {escape(env["volatility_band"])}</span></p>\n'
        f'<p class="env-posture">{escape(env["posture"])}</p>\n'
        f'<ul aria-label="Warnings ({env["warnings_on"]} of {len(env["warnings"])} on)">\n'
        + "\n".join(items)
        + "\n</ul>\n"
        f'<p class="note">{env["warnings_on"]} of {len(env["warnings"])} warnings on. '
        f"Data as of: {as_of}.</p>\n"
        "</section>"
    )


def status_section() -> str:
    """Sectors grouped by status label, from output/sector_status_today.json."""
    status = load_status()

    def name_cell(s: dict) -> str:
        name = escape(SECTOR_NAMES.get(s["sector"], ""))
        borderline = (
            abs(s["rel_score"]) <= BORDERLINE_SCORE or s["days_in_label"] < BORDERLINE_DAYS
        )
        return name + (' <span class="tag">borderline</span>' if borderline else "")

    groups = []
    for label, guidance in STATUS_GUIDANCE.items():
        members = [s for s in status["sectors"] if s["label"] == label]
        members.sort(key=lambda s: s["rel_score"], reverse=True)
        heading = (
            f"<h3>{escape(label)} ({len(members)})</h3>\n"
            f'<p class="guidance">{escape(guidance)}</p>\n'
        )
        if not members:
            groups.append(heading + '<p class="note">No sectors today.</p>')
            continue
        rows = [
            [
                escape(s["sector"]),
                name_cell(s),
                signed(s["score"]),
                signed(s["rel_score"]),
                signed(s["change"]),
                f"{s['days_in_label']}d",
            ]
            for s in members
        ]
        groups.append(
            heading + html_table(
                ["ETF", "Sector", "Score", "Rel", "Change", "Held"], rows, name_column=1
            )
        )

    return (
        '<section class="status">\n'
        "<h2>Sector status</h2>\n"
        f'<p class="note">As of the {escape(status["date"])} close. Score is the average '
        "1, 3 and 6-month return relative to SPY. Rel is the score minus the average "
        "score of all sectors, and Change is Rel versus "
        f'{status["change_days"]} trading days earlier (all in percentage points). '
        "Labels come from Rel and Change. Held is how many trading days in a row "
        "the sector has had its label. A sector is marked borderline when Rel is "
        f"within {BORDERLINE_SCORE} point of zero or it has held its label for fewer "
        f"than {BORDERLINE_DAYS} days.</p>\n"
        + "\n".join(groups)
        + "\n</section>"
    )


def prices_through() -> str | None:
    """Date of the last price row, if the price file is available."""
    if not PRICES_PATH.exists():
        return None
    dates = pd.read_csv(PRICES_PATH, usecols=["Date"])["Date"]
    return None if dates.empty else str(dates.iloc[-1])


def build_page() -> str:
    if not RANKS_PATH.exists():
        raise RuntimeError(f"{RANKS_PATH} not found. Run scripts/rank_sectors.py first.")
    if not (OUTPUT_DIR / DASHBOARD_NAME).exists():
        raise RuntimeError(
            f"{OUTPUT_DIR / DASHBOARD_NAME} not found. Run scripts/build_dashboard.py first."
        )

    ranks = pd.read_csv(RANKS_PATH).sort_values("Rank")
    if ranks.empty:
        raise RuntimeError(f"{RANKS_PATH} has no rows.")
    drilled = drill_sectors(load_status())

    run_time = datetime.now(MARKET_TIMEZONE)
    meta = f"Run date: {run_time:%A, %B %-d, %Y} ({run_time:%H:%M} US Eastern)"
    through = prices_through()
    if through:
        meta += f"<br>Prices through the {escape(through)} close"

    sections = [ranking_section(ranks)]
    sections += [stocks_section(entry) for entry in drilled]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sector rotation</title>
<style>{STYLE}</style>
</head>
<body>
<h1>Sector rotation</h1>
<p class="meta">{meta}</p>
{environment_section()}
{status_section()}
{setups_section(drilled)}
<p><a class="button" href="{DASHBOARD_NAME}">Open the dashboard</a></p>
{chr(10).join(sections)}
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--list-sectors",
        action="store_true",
        help="print the sectors whose stocks should be scanned, then exit",
    )
    args = parser.parse_args()

    try:
        if args.list_sectors:
            print(" ".join(entry["sector"] for entry in drill_sectors(load_status())))
            return 0
        page = build_page()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    INDEX_PATH.write_text(page, encoding="utf-8")
    print(f"Saved {INDEX_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
