"""Build the published site: one mobile-first page, output/index.html.

Five tabs under a sticky tab bar, each with its own URL hash:

  Today    environment card, what changed, sector status chips, setup counts
  Setups   the three setup lists with trade plans
  Sectors  the weekly rank heatmap          (charts from build_dashboard.py)
  Macro    the four gauge charts            (charts from build_dashboard.py)
  Stocks   collapsible stock tables for the scanned sectors, sector ranking

Reads the files the other scripts write to output/, so run those first.
"""

import argparse
import json
import sys
from datetime import date, datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from build_dashboard import chart_parts

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
RANKS_PATH = OUTPUT_DIR / "ranks_today.csv"
ENVIRONMENT_PATH = OUTPUT_DIR / "environment_today.json"
STATUS_PATH = OUTPUT_DIR / "sector_status_today.json"
LOG_PATH = PROJECT_ROOT / "log" / "signals.csv"
PRICES_PATH = PROJECT_ROOT / "data" / "prices.csv"
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
STOP_ATRS = 0.5          # stop sits this many ATRs beyond the EMA
# Lists whose day-to-day membership is reported in the "What changed" box
TRACKED_LISTS = ["Long ideas", "Put ideas"]
MARKET_TIMEZONE = ZoneInfo("America/New_York")

# Tab id (also its URL hash) -> title, in display order. The first one opens by default.
TABS = {
    "today": "Today",
    "setups": "Setups",
    "sectors": "Sectors",
    "macro": "Macro",
    "stocks": "Stocks",
}

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
* { box-sizing: border-box; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.45;
  margin: 0;
}
.page { max-width: 46rem; margin: 0 auto; padding: 0 1rem 2.5rem; }
header.top { padding: 0.7rem 0 0.4rem; }
h1 { font-size: 1.2rem; margin: 0; }
h2 { font-size: 1.1rem; margin: 1.25rem 0 0.4rem; }
h3 { font-size: 1rem; margin: 1rem 0 0; }
.meta, .note { color: GrayText; font-size: 0.85rem; }
.meta { margin: 0.1rem 0 0; }
nav.tabs {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  margin: 0 -1rem;
  padding: 0 0.5rem;
  background: Canvas;
  border-bottom: 1px solid GrayText;
}
nav.tabs a {
  flex: 1;
  padding: 0.75rem 0 0.6rem;
  border-bottom: 3px solid transparent;
  color: GrayText;
  font-size: 0.9rem;
  font-weight: 600;
  text-align: center;
  text-decoration: none;
  white-space: nowrap;
}
nav.tabs a[aria-current="page"] { color: CanvasText; border-bottom-color: CanvasText; }
.panel { padding-top: 1rem; }
.panel[hidden] { display: none; }
.panel > h2:first-child { margin-top: 0; }
.card {
  border: 1px solid GrayText;
  border-radius: 0.5rem;
  padding: 0.75rem 1rem;
  margin-bottom: 0.9rem;
}
.card h2 { margin: 0 0 0.4rem; }
.card p { margin: 0.35rem 0 0; }
summary { cursor: pointer; padding: 0.5rem 0; font-weight: 600; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
th, td { padding: 0.35rem 0.3rem; text-align: right; white-space: nowrap; }
th:nth-child(-n+2), td:nth-child(-n+2), td.name, th.name { text-align: left; }
th { border-bottom: 2px solid GrayText; }
td { border-bottom: 1px solid color-mix(in srgb, GrayText 30%, transparent); }
td.name { white-space: normal; }
.env { border-left: 0.5rem solid var(--env-color); }
.env-risk-on { --env-color: #1a7f37; --env-text: #ffffff; }
.env-caution { --env-color: #f0a500; --env-text: #1a1a1a; }
.env-risk-off { --env-color: #c02b2b; --env-text: #ffffff; }
.env .env-heading { margin: 0 0 0.4rem; font-size: 0.85rem; color: GrayText; }
.env-label {
  display: inline-block;
  padding: 0.1rem 0.7rem;
  border-radius: 0.3rem;
  background: var(--env-color);
  color: var(--env-text);
  font-size: 1.3rem;
  font-weight: 700;
}
.env-band { margin-left: 0.5rem; white-space: nowrap; }
.env .env-posture { margin: 0.5rem 0 0.2rem; font-weight: 600; }
.env ul { list-style: none; margin: 0.2rem 0 0.4rem; padding: 0; }
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
.changes ul { margin: 0.4rem 0 0; padding-left: 1.2rem; }
.changes li { padding: 0.1rem 0; }
.chips { display: flex; flex-wrap: wrap; align-items: center; gap: 0.3rem; }
.chips .chip-label { flex: none; width: 5.2rem; font-weight: 600; font-size: 0.9rem; }
.chip {
  padding: 0.05rem 0.5rem;
  border: 2px solid var(--chip);
  border-radius: 1rem;
  background: var(--chip);
  color: var(--chip-text);
  font-size: 0.85rem;
  font-weight: 700;
}
.chip.borderline { background: transparent; color: CanvasText; }
.chip.leading { --chip: #1a7f37; --chip-text: #ffffff; }
.chip.improving { --chip: #0b7285; --chip-text: #ffffff; }
.chip.weakening { --chip: #f0a500; --chip-text: #1a1a1a; }
.chip.lagging { --chip: #c02b2b; --chip-text: #ffffff; }
.status .guidance { margin: 0.1rem 0 0.3rem; font-weight: 600; }
.setup-count { font-weight: 600; }
details.fold { border-top: 1px solid GrayText; }
details.fold:last-of-type { border-bottom: 1px solid GrayText; }
details.fold > summary { padding: 0.7rem 0; font-size: 1.05rem; }
details.fold > :last-child { margin-bottom: 0.9rem; }
details.fold p { margin: 0.3rem 0; }
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
@media (min-width: 1000px) {
  .page { max-width: 64rem; }
  .panel.narrow { max-width: 46rem; }
}
"""

# Runs in the browser: shows one tab at a time, following the URL hash so
# tabs can be bookmarked and the back button moves between them.
TAB_SCRIPT = """
(function () {
  var tabs = __TABS__;
  function current() {
    var name = location.hash.replace('#', '');
    return tabs.indexOf(name) >= 0 ? name : tabs[0];
  }
  function show() {
    var name = current();
    tabs.forEach(function (tab) {
      document.getElementById('panel-' + tab).hidden = tab !== name;
      var link = document.querySelector('nav.tabs a[href="#' + tab + '"]');
      if (tab === name) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    window.scrollTo(0, 0);
    // Charts are drawn or resized when their tab becomes visible.
    if (window.dashboardCharts) window.dashboardCharts.open(name);
  }
  window.currentTab = current;
  window.addEventListener('hashchange', show);
  show();
})();
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
    needed = ["Setup", "Close", "DistEMA20", "DistEMA50", "ATRPct", "next_earnings"]
    missing = [c for c in needed if c not in stocks.columns]
    if missing:
        raise RuntimeError(
            f"{path} has no {missing} column. Rerun scripts/sector_stocks.py {sector}."
        )
    return stocks


# The three setup lists. Long-side lists keep relative return above 0,
# strongest first; put-side lists keep it below 0, weakest first.
SETUP_LISTS = [
    {
        "title": "Long ideas",
        "note": "Pullback stocks in Leading sectors, beating their sector over 3 months.",
        "label": "Leading",
        "setups": ["Pullback"],
        "long_side": True,
        "limit": None,
        "below_fast_ema": False,
        "hold_for_earnings": True,
    },
    {
        "title": "Wait for pullback",
        "note": (
            "Extended or Trending stocks in Leading sectors, beating their sector "
            f"over 3 months. The {WAIT_LIST_LIMIT} strongest."
        ),
        "label": "Leading",
        "setups": ["Extended", "Trending"],
        "long_side": True,
        "limit": WAIT_LIST_LIMIT,
        "below_fast_ema": False,
        "hold_for_earnings": False,
    },
    {
        "title": "Put ideas",
        "note": (
            "Breaking down stocks in Lagging sectors, trailing their sector over "
            f"3 months and below the 20 EMA. The {PUT_LIST_LIMIT} weakest."
        ),
        "label": "Lagging",
        "setups": ["Breaking down"],
        "long_side": False,
        "limit": PUT_LIST_LIMIT,
        "below_fast_ema": True,
        "hold_for_earnings": True,
    },
]


def scanned_stocks(drilled: list[dict]) -> pd.DataFrame:
    """Stock tables of the scanned sectors, with each stock's sector and its label."""
    frames = []
    for entry in drilled:
        stocks = load_stocks(entry["sector"])
        stocks["Sector"] = entry["sector"]
        stocks["SectorLabel"] = entry["label"]
        frames.append(stocks)
    if frames:
        return pd.concat(frames)
    return pd.DataFrame(
        columns=[
            "Ticker", "Sector", "SectorLabel", "Close", "RelReturn3m", "DistEMA20",
            "DistEMA50", "ATRPct", "Setup", "next_earnings",
        ]
    )


def add_trade_plan(stocks: pd.DataFrame, long_side: bool) -> pd.DataFrame:
    """Add Stop, RiskPct and RiskATR columns.

    Longs: stop = 50 EMA minus half an ATR. Puts: stop = 20 EMA plus half an
    ATR. Risk is the distance from the close to the stop, as a % of the close
    and in ATRs. The EMAs are recovered from the close and its % distance.
    """
    stocks = stocks.copy()
    atr = stocks["Close"] * stocks["ATRPct"] / 100
    if long_side:
        ema = stocks["Close"] / (1 + stocks["DistEMA50"] / 100)
        stocks["Stop"] = ema - STOP_ATRS * atr
        risk = stocks["Close"] - stocks["Stop"]
    else:
        ema = stocks["Close"] / (1 + stocks["DistEMA20"] / 100)
        stocks["Stop"] = ema + STOP_ATRS * atr
        risk = stocks["Stop"] - stocks["Close"]
    stocks["RiskPct"] = risk / stocks["Close"] * 100
    stocks["RiskATR"] = risk / atr
    return stocks


def select_setups(stocks: pd.DataFrame, spec: dict) -> dict:
    """Apply one list's rules. Returns the spec plus its picks, the names held
    back for earnings, and the reasons (with counts) other names were dropped."""
    long_side = spec["long_side"]
    picks = stocks[
        (stocks["SectorLabel"] == spec["label"]) & stocks["Setup"].isin(spec["setups"])
    ]
    picks = add_trade_plan(picks, long_side)
    dropped = []

    keep = picks["RelReturn3m"] > 0 if long_side else picks["RelReturn3m"] < 0
    if (~keep).any():
        side = "at or below" if long_side else "at or above"
        dropped.append(f"{(~keep).sum()} with relative 3-month return {side} 0")
    picks = picks[keep]

    if spec["below_fast_ema"]:
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
        dropped.append(f"{len(duplicates)} second share class ({', '.join(duplicates)})")
        picks = picks[~picks["Ticker"].isin(duplicates)]

    held_back = picks.iloc[0:0]
    if spec["hold_for_earnings"]:
        days = picks["next_earnings"].map(days_to_earnings)
        close = days.between(0, EARNINGS_HOLD_DAYS)
        held_back, picks = picks[close], picks[~close]

    picks = picks.sort_values("RelReturn3m", ascending=not long_side)
    limit = spec["limit"]
    if limit is not None and len(picks) > limit:
        which = "strongest" if long_side else "weakest"
        dropped.append(f"{len(picks) - limit} beyond the {limit} {which}")
        picks = picks.head(limit)

    return {**spec, "picks": picks, "held_back": held_back, "dropped": dropped}


def setup_lists(drilled: list[dict]) -> list[dict]:
    """The three setup lists for today, as data. Also used by log_signals.py."""
    stocks = scanned_stocks(drilled)
    return [select_setups(stocks, spec) for spec in SETUP_LISTS]


def setup_list_html(result: dict, open_by_default: bool) -> str:
    """One setup list as a collapsible block."""
    picks, held_back, dropped = result["picks"], result["held_back"], result["dropped"]
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

    if picks.empty:
        body = "<p>None today</p>"
    else:
        headers = ["Ticker", "Sector", "Rel 3m", "vs 20 EMA", "Earnings", "Stop", "Risk %", "ATRs"]
        rows = [
            [
                escape(str(r.Ticker)),
                escape(r.Sector),
                signed(r.RelReturn3m),
                "n/a" if pd.isna(r.DistEMA20) else f"{r.DistEMA20:+.1f}%",
                earnings_cell(r.next_earnings),
                "n/a" if pd.isna(r.Stop) else f"{r.Stop:.2f}",
                "n/a" if pd.isna(r.RiskPct) else f"{r.RiskPct:.1f}%",
                "n/a" if pd.isna(r.RiskATR) else f"{r.RiskATR:.1f}",
            ]
            for r in picks.itertuples(index=False)
        ]
        if len(result["setups"]) > 1:
            headers.insert(4, "Setup")
            for row, r in zip(rows, picks.itertuples(index=False)):
                row.insert(4, escape(r.Setup))
        body = html_table(headers, rows)

    return (
        f'<details class="fold"{" open" if open_by_default else ""}>\n'
        f"<summary>{escape(result['title'])} ({len(picks)})</summary>\n"
        f"<p class=\"note\">{escape(result['note'])}</p>\n"
        f"{body}\n{filtered}\n"
        "</details>"
    )


def setups_section(drilled: list[dict], lists: list[dict]) -> str:
    """Setups tab: the three lists, with only the first one open."""
    scanned = ", ".join(f"{e['sector']} ({e['label']})" for e in drilled) or "none"
    return (
        '<p class="note">From the largest holdings of the scanned sectors: '
        f"{escape(scanned)}.</p>\n"
        + "\n".join(setup_list_html(result, i == 0) for i, result in enumerate(lists))
        + '\n<details class="fold">\n<summary>How to read the columns</summary>\n'
        "<p>Rel 3m is the 3-month return minus the sector ETF's return (percentage points); "
        "vs 20 EMA is the close's distance from its 20-day EMA. Earnings is the next "
        f"report date and how many days away it is, highlighted within "
        f"{EARNINGS_SOON_DAYS} days. Stop is the 50-day EMA minus {STOP_ATRS} ATR for "
        f"longs and the 20-day EMA plus {STOP_ATRS} ATR for puts (14-day ATR). Risk % "
        "is the distance from the close to the stop, and ATRs is that same "
        "distance in ATRs.</p>\n</details>"
    )


def setup_count_line(lists: list[dict]) -> str:
    """One line for the Today tab, linking to the Setups tab."""
    counts = {result["title"]: len(result["picks"]) for result in lists}
    held = sum(len(result["held_back"]) for result in lists)
    longs, puts = counts.get("Long ideas", 0), counts.get("Put ideas", 0)
    text = (
        f"{longs} long idea{'' if longs == 1 else 's'} · "
        f"{puts} put{'' if puts == 1 else 's'}"
    )
    extra = f" · {held} held back for earnings" if held else ""
    return f'<p class="setup-count"><a href="#setups">{text}</a>{extra}</p>'


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
        '<details class="fold">\n'
        f"<summary>{escape(sector)} {escape(name)} ({escape(entry['label'])}): "
        f"top {len(rows)} holdings</summary>\n"
        f'<p class="note">Largest holdings, ranked by 3-month return minus '
        f"{escape(sector)}'s return (percentage points). The next three columns "
        "show whether the price is above its 20-day and 50-day EMA, and whether "
        "the 20-day is above the 50-day.</p>\n"
        + html_table(
            ["#", "Ticker", "Wt %", "Rel 3m", ">20d", ">50d", "20>50", "Setup", "Earnings"],
            rows,
        )
        + "\n</details>"
    )


def changes_section(lists: list[dict]) -> str:
    """What changed since the previous price date in log/signals.csv."""
    environment = json.loads(ENVIRONMENT_PATH.read_text(encoding="utf-8"))
    status = load_status()
    today = status["date"]

    log = pd.read_csv(LOG_PATH, dtype=str).fillna("") if LOG_PATH.exists() else None
    earlier = sorted(set(log["price_date"][log["price_date"] < today])) if log is not None else []
    if not earlier:
        return (
            '<section class="card changes">\n<h2>What changed</h2>\n'
            "<p>First day of the log; changes start tomorrow.</p>\n</section>"
        )
    previous_date = earlier[-1]
    previous = log[log["price_date"] == previous_date]

    items = []
    old_environment = previous["env_label"].iloc[0]
    if old_environment != environment["label"]:
        items.append(
            f"Environment: {escape(old_environment)} → <strong>{escape(environment['label'])}</strong>"
        )

    old_labels = dict(
        previous.loc[previous["item"] == "sector", ["sector", "sector_label"]].values
    )
    for sector in status["sectors"]:
        old = old_labels.get(sector["sector"])
        if old is not None and old != sector["label"]:
            name = SECTOR_NAMES.get(sector["sector"], "")
            items.append(
                f"{escape(sector['sector'])} {escape(name)}: {escape(old)} → "
                f"<strong>{escape(sector['label'])}</strong>"
            )

    held_back = {t for result in lists for t in result["held_back"]["Ticker"]}
    for result in lists:
        title = result["title"]
        if title not in TRACKED_LISTS:
            continue
        now = list(result["picks"]["Ticker"])
        before = list(previous.loc[previous["list"] == title.lower(), "ticker"])
        added = [t for t in now if t not in before]
        removed = [t for t in before if t not in now]
        if added:
            items.append(f"New in {escape(title)}: {escape(', '.join(added))}")
        if removed:
            names = ", ".join(
                t + (" (held back for earnings)" if t in held_back else "") for t in removed
            )
            items.append(f"Dropped from {escape(title)}: {escape(names)}")

    if not items:
        body = f"<p>No changes since {escape(previous_date)}.</p>"
    else:
        body = (
            f'<p class="note">Since the {escape(previous_date)} close.</p>\n<ul>\n'
            + "\n".join(f"<li>{item}</li>" for item in items)
            + "\n</ul>"
        )
    return f'<section class="card changes">\n<h2>What changed</h2>\n{body}\n</section>'


def environment_section() -> str:
    """Environment card: label, volatility band, posture, warnings behind a tap."""
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
        f'<section class="card env {css_class}">\n'
        f'<p class="env-heading">Market environment, as of the {escape(env["date"])} close</p>\n'
        f'<p><span class="env-label">{escape(env["label"])}</span>'
        f'<span class="env-band">Volatility: {escape(env["volatility_band"])}</span></p>\n'
        f'<p class="env-posture">{escape(env["posture"])}</p>\n'
        "<details>\n"
        f'<summary>{env["warnings_on"]} of {len(env["warnings"])} warnings</summary>\n'
        "<ul>\n" + "\n".join(items) + "\n</ul>\n"
        f'<p class="note">Data as of: {as_of}.</p>\n'
        "</details>\n"
        "</section>"
    )


def is_borderline(sector: dict) -> bool:
    return (
        abs(sector["rel_score"]) <= BORDERLINE_SCORE
        or sector["days_in_label"] < BORDERLINE_DAYS
    )


def status_section() -> str:
    """Sector status card: chips grouped by label, full tables behind "Details"."""
    status = load_status()

    def name_cell(s: dict) -> str:
        name = escape(SECTOR_NAMES.get(s["sector"], ""))
        return name + (' <span class="tag">borderline</span>' if is_borderline(s) else "")

    chip_rows, groups = [], []
    for label, guidance in STATUS_GUIDANCE.items():
        members = [s for s in status["sectors"] if s["label"] == label]
        members.sort(key=lambda s: s["rel_score"], reverse=True)

        chips = "".join(
            f'<span class="chip {label.lower()}{" borderline" if is_borderline(s) else ""}">'
            f"{escape(s['sector'])}</span>"
            for s in members
        ) or '<span class="note">none</span>'
        chip_rows.append(
            f'<p class="chips"><span class="chip-label">{escape(label)}</span>{chips}</p>'
        )

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
        '<section class="card status">\n'
        "<h2>Sector status</h2>\n"
        + "\n".join(chip_rows)
        + '\n<p class="note">Outlined = borderline.</p>\n'
        "<details>\n<summary>Details</summary>\n"
        + "\n".join(groups)
        + f'\n<p class="note">As of the {escape(status["date"])} close. Score is the average '
        "1, 3 and 6-month return relative to SPY. Rel is the score minus the average "
        "score of all sectors, and Change is Rel versus "
        f'{status["change_days"]} trading days earlier (all in percentage points). '
        "Labels come from Rel and Change. Held is how many trading days in a row "
        "the sector has had its label. A sector is marked borderline when Rel is "
        f"within {BORDERLINE_SCORE} point of zero or it has held its label for fewer "
        f"than {BORDERLINE_DAYS} days.</p>\n"
        "</details>\n"
        "</section>"
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

    ranks = pd.read_csv(RANKS_PATH).sort_values("Rank")
    if ranks.empty:
        raise RuntimeError(f"{RANKS_PATH} has no rows.")
    drilled = drill_sectors(load_status())
    lists = setup_lists(drilled)
    charts = chart_parts()

    run_time = datetime.now(MARKET_TIMEZONE)
    meta = f"Run {run_time:%a %b} {run_time.day}, {run_time:%H:%M} ET"
    through = prices_through()
    if through:
        meta = f"Prices through the {escape(through)} close · " + meta

    stock_tables = "\n".join(stocks_section(entry) for entry in drilled)
    panels = {
        "today": (
            f"{environment_section()}\n{changes_section(lists)}\n{status_section()}\n"
            f"{setup_count_line(lists)}"
        ),
        "setups": setups_section(drilled, lists),
        "sectors": charts["sectors_html"],
        "macro": charts["macro_html"],
        "stocks": (
            "<h2>Stock tables</h2>\n"
            '<p class="note">Tap a sector to show its largest holdings.</p>\n'
            f"{stock_tables}\n{ranking_section(ranks)}"
        ),
    }
    chart_tabs = {"sectors", "macro"}
    nav = "".join(f'<a href="#{tab}">{title}</a>' for tab, title in TABS.items())
    sections = "\n".join(
        f'<section id="panel-{tab}" class="panel{"" if tab in chart_tabs else " narrow"}">\n'
        f"{panels[tab]}\n</section>"
        for tab in TABS
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sector rotation</title>
<style>{STYLE}{charts["style"]}</style>
</head>
<body>
<div class="page">
<header class="top">
<h1>Sector rotation</h1>
<p class="meta">{meta}</p>
</header>
<nav class="tabs" aria-label="Sections">{nav}</nav>
{sections}
</div>
<script>{TAB_SCRIPT.replace("__TABS__", json.dumps(list(TABS)))}</script>
<script src="{charts["plotly_src"]}"></script>
<script>{charts["script"]}</script>
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
