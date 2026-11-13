"""Charts for the Sectors and Macro tabs of output/index.html.

Reads output/rank_history.csv and data/regime.csv and provides, for
build_site.py to embed in the one-page site:

  - the weekly sector rank heatmap (Sectors tab)
  - four gauge charts: credit spread, yield curve, VIX, dollar (Macro tab)
  - a row of range buttons per tab that sets the date range of every chart
    on that tab, with y-axes rescaled to the visible range

Run directly, it writes output/dashboard.html: a tiny page that redirects
to index.html#macro, so old links to the dashboard keep working.
"""

import json
import sys
from pathlib import Path

import pandas as pd
from plotly.offline import get_plotlyjs_version

from rank_history import build_heatmap

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RANKS_PATH = PROJECT_ROOT / "output" / "rank_history.csv"
REGIME_PATH = PROJECT_ROOT / "data" / "regime.csv"
OUTPUT_PATH = PROJECT_ROOT / "output" / "dashboard.html"

START = "2019-01-01"
REDIRECT_TARGET = "index.html#macro"

# Smaller plotly build with just the chart types used here, loaded once per page.
PLOTLY_SRC = f"https://cdn.plot.ly/plotly-cartesian-{get_plotlyjs_version()}.min.js"

# Regime column -> chart title, hover name, and whether the y-axis must show zero
GAUGES = {
    "credit_spread": {
        "title": "Credit spread",
        "unit": "Baa yield minus 10-year Treasury, % pts",
        "hover": "Credit spread (Baa − 10y)",
        "zero": False,
    },
    "curve_10y2y": {
        "title": "Yield curve",
        "unit": "10-year minus 2-year Treasury, % pts",
        "hover": "Yield curve (10y − 2y)",
        "zero": True,
    },
    "vix": {"title": "VIX", "unit": "index", "hover": "VIX", "zero": False},
    "dollar": {
        "title": "Dollar index",
        "unit": "broad US dollar",
        "hover": "Dollar index",
        "zero": False,
    },
}
RANGE_BUTTONS = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12, "5Y": 60, "All": None}  # months
DEFAULT_RANGE = "6M"

CHART_STYLE = """
.ranges { display: flex; gap: 0.35rem; margin: 0.25rem 0 0.75rem; }
.ranges button {
  flex: 1;
  min-height: 2.5rem;
  padding: 0;
  border: 1px solid GrayText;
  border-radius: 0.4rem;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 0.9rem;
  cursor: pointer;
}
.ranges button[aria-pressed="true"] { background: CanvasText; color: Canvas; font-weight: 700; }
.chart-card { margin: 0 0 0.9rem; }
.chart-head { display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; }
.chart-head h3 { margin: 0; font-size: 1rem; }
.chart-head .latest { font-weight: 700; white-space: nowrap; }
.chart-card .unit { margin: 0; color: GrayText; font-size: 0.8rem; }
.chart { width: 100%; height: 220px; }
.chart.heat { height: 240px; }
.readout { min-height: 1.4rem; margin: 0.2rem 0; font-weight: 600; font-size: 0.9rem; }
.heat-legend { display: flex; align-items: center; gap: 0.5rem; color: GrayText; font-size: 0.8rem; }
.heat-legend .bar { flex: 1; max-width: 12rem; height: 0.6rem; border-radius: 0.3rem; }
.chart-error { color: GrayText; }
@media (min-width: 1000px) {
  .gauges { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem 2rem; }
  .chart { height: 260px; }
  .chart.heat { height: 420px; }
  .ranges { max-width: 28rem; }
}
"""

# Runs in the browser. __DATA__ is replaced with the chart data.
CHART_SCRIPT = """
(function () {
  var DATA = __DATA__;
  var MONTHS = DATA.ranges;
  var state = { sectors: DATA.defaultRange, macro: DATA.defaultRange };
  var built = { sectors: false, macro: false };
  var phone = window.matchMedia('(max-width: 699px)');
  var dark = window.matchMedia('(prefers-color-scheme: dark)');
  var DAY = 86400000;

  function colors() {
    return dark.matches
      ? { text: '#e6e6e6', grid: 'rgba(255,255,255,0.14)', line: '#6aa9e9', zero: '#cfcfcf',
          hoverBg: '#1f1f1f', hoverText: '#f2f2f2', gap: '#121212' }
      : { text: '#333333', grid: 'rgba(0,0,0,0.10)', line: '#2a6fb0', zero: '#555555',
          hoverBg: '#ffffff', hoverText: '#1a1a1a', gap: '#ffffff' };
  }

  function iso(ms) { return new Date(ms).toISOString().slice(0, 10); }
  function ms(day) { return Date.parse(day + 'T00:00:00Z'); }

  // Visible date range for a tab: back from the latest date by the chosen
  // number of months, never earlier than the first date.
  function dateRange(tab) {
    var days = tab === 'macro' ? DATA.dates : DATA.heat.x;
    var first = ms(days[0]), last = ms(days[days.length - 1]);
    var months = MONTHS[state[tab]];
    var start = first;
    if (months !== null) {
      var d = new Date(last);
      d.setUTCMonth(d.getUTCMonth() - months);
      start = Math.max(first, d.getTime());
    }
    var pad = tab === 'macro' ? DAY : 4 * DAY;  // room for the end points / half a weekly cell
    return { start: iso(start), end: iso(last), axis: [iso(start - pad), iso(last + pad)] };
  }

  // Y-axis range covering only the values inside the visible dates.
  function valueRange(values, range, includeZero) {
    var lo = Infinity, hi = -Infinity;
    for (var i = 0; i < DATA.dates.length; i++) {
      var day = DATA.dates[i], v = values[i];
      if (v === null || day < range.start || day > range.end) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    if (lo === Infinity) return null;
    if (includeZero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    var pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.05 || 1;
    return [lo - pad, hi + pad];
  }

  function baseLayout(c, range) {
    return {
      autosize: true,
      margin: { l: 40, r: 6, t: 6, b: 26 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'system-ui, -apple-system, "Segoe UI", sans-serif', size: 11, color: c.text },
      showlegend: false,
      // No drag-to-zoom: a finger dragging over a chart scrolls the page
      // instead. The range buttons set the dates; a tap shows the value.
      dragmode: false,
      hoverlabel: { bgcolor: c.hoverBg, bordercolor: c.grid, font: { color: c.hoverText, size: 12 } },
      xaxis: { type: 'date', range: range.axis, fixedrange: true, showgrid: false,
               hoverformat: '%a %b %-d, %Y', ticks: 'outside', tickcolor: c.grid, nticks: 6 },
      yaxis: { fixedrange: true, gridcolor: c.grid, zeroline: false, nticks: 5 }
    };
  }

  function config() {
    return { responsive: true, displaylogo: false, scrollZoom: false, doubleClick: false,
             displayModeBar: phone.matches ? false : 'hover',
             modeBarButtons: [['toImage']] };
  }

  function buildMacro() {
    var c = colors(), range = dateRange('macro');
    DATA.gauges.forEach(function (g) {
      var layout = baseLayout(c, range);
      layout.hovermode = 'x unified';
      layout.yaxis.range = valueRange(g.values, range, g.zero);
      if (g.zero) {
        layout.shapes = [{ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: 0, y1: 0,
                           line: { color: c.zero, width: 1, dash: 'dash' } }];
      }
      Plotly.react('chart-' + g.id, [{
        type: 'scatter', mode: 'lines', x: DATA.dates, y: g.values, connectgaps: false,
        line: { color: c.line, width: 1.6 },
        hovertemplate: g.hover + ': %{y:.2f}<extra></extra>'
      }], layout, config());
    });
  }

  function buildSectors() {
    var c = colors(), range = dateRange('sectors'), h = DATA.heat;
    var layout = baseLayout(c, range);
    layout.margin.l = 46;
    layout.hovermode = 'closest';
    layout.yaxis = { type: 'category', autorange: 'reversed', fixedrange: true, showgrid: false };
    Plotly.react('chart-heat', [{
      type: 'heatmap', x: h.x, y: h.y, z: h.z, zmin: h.zmin, zmax: h.zmax,
      colorscale: h.colorscale, showscale: false, ygap: 2, xgap: 1, hoverongaps: false,
      hovertemplate: h.hovertemplate
    }], layout, config());
  }

  var builders = { sectors: buildSectors, macro: buildMacro };

  // On a touch screen a tap is a click with no lasting hover, so show the
  // tapped point's value ourselves and keep it up until the next tap.
  function showValueOnTap(el) {
    if (el.dataset.tapReady) return;
    el.dataset.tapReady = 'yes';
    el.on('plotly_click', function (event) {
      var point = event.points[0];
      var readout = document.getElementById(el.id + '-readout');
      if (readout) {
        // Heatmap: write the tapped cell out under the chart.
        var week = new Date(point.x + 'T00:00:00Z').toLocaleDateString('en-US', {
          weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
        readout.textContent = 'Week ending ' + week + ' · ' + point.y + ' · Rank ' + point.z;
        return;
      }
      setTimeout(function () {
        Plotly.Fx.hover(el, [{ curveNumber: point.curveNumber, pointNumber: point.pointNumber }]);
      }, 80);
    });
  }

  function chartsIn(tab) {
    return Array.prototype.slice.call(document.querySelectorAll('#panel-' + tab + ' .chart'));
  }

  function markButtons(tab) {
    var buttons = document.querySelectorAll('.ranges[data-tab="' + tab + '"] button');
    Array.prototype.forEach.call(buttons, function (b) {
      b.setAttribute('aria-pressed', b.dataset.range === state[tab] ? 'true' : 'false');
    });
  }

  // Called whenever a tab is shown. Charts are drawn the first time their tab
  // opens (a hidden tab has no width to draw into) and resized after that.
  function open(tab) {
    if (!builders[tab]) return;
    if (typeof Plotly === 'undefined') {
      chartsIn(tab).forEach(function (el) {
        el.innerHTML = '<p class="chart-error">The chart library did not load. Check the connection and reload.</p>';
      });
      return;
    }
    markButtons(tab);
    if (!built[tab]) {
      builders[tab]();
      built[tab] = true;
      chartsIn(tab).forEach(showValueOnTap);
    } else {
      chartsIn(tab).forEach(function (el) { Plotly.Plots.resize(el); });
    }
  }

  function redraw() {
    Object.keys(builders).forEach(function (tab) { if (built[tab]) builders[tab](); });
  }

  document.addEventListener('click', function (event) {
    var button = event.target.closest('.ranges button');
    if (!button) return;
    var tab = button.parentNode.dataset.tab;
    state[tab] = button.dataset.range;
    markButtons(tab);
    if (typeof Plotly !== 'undefined') { open(tab); builders[tab](); }
  });
  if (dark.addEventListener) dark.addEventListener('change', redraw);

  window.dashboardCharts = { open: open, state: state };
  if (window.currentTab) open(window.currentTab());
})();
"""


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    for path, script in [(RANKS_PATH, "rank_history.py"), (REGIME_PATH, "fetch_regime.py")]:
        if not path.exists():
            raise RuntimeError(f"{path} not found. Run scripts/{script} first.")

    ranks = pd.read_csv(RANKS_PATH, parse_dates=["Date"]).set_index("Date")
    regime = pd.read_csv(REGIME_PATH, parse_dates=["Date"]).set_index("Date")

    missing = [c for c in GAUGES if c not in regime.columns]
    if missing:
        raise RuntimeError(f"Missing columns in {REGIME_PATH.name}: {missing}")

    ranks, regime = ranks.loc[START:], regime.loc[START:]
    if ranks.empty or regime.empty:
        raise RuntimeError(f"No rank history or regime data from {START} on.")
    return ranks, regime


def numbers(values) -> list:
    """Plain list for JSON, with blanks (gaps in the data) as None."""
    return [None if pd.isna(v) else round(float(v), 4) for v in values]


def chart_data(ranks: pd.DataFrame, regime: pd.DataFrame) -> dict:
    """Everything the browser needs to draw the charts."""
    # Same heatmap trace as rank_history.py builds: colours, sector order
    # (top to bottom by current rank) and hover text.
    heat = build_heatmap(ranks).data[0]
    return {
        "ranges": RANGE_BUTTONS,
        "defaultRange": DEFAULT_RANGE,
        "dates": [d.strftime("%Y-%m-%d") for d in regime.index],
        "gauges": [
            {
                "id": column,
                "hover": spec["hover"],
                "zero": spec["zero"],
                "values": numbers(regime[column]),  # gaps stay gaps, never filled
            }
            for column, spec in GAUGES.items()
        ],
        "heat": {
            "x": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in heat.x],
            "y": [str(s) for s in heat.y],
            "z": [[None if pd.isna(v) else int(v) for v in row] for row in heat.z],
            "zmin": heat.zmin,
            "zmax": heat.zmax,
            "colorscale": [list(stop) for stop in heat.colorscale],
            "hovertemplate": heat.hovertemplate,
        },
    }


def range_buttons(tab: str) -> str:
    buttons = "".join(
        f'<button type="button" data-range="{name}" '
        f'aria-pressed="{"true" if name == DEFAULT_RANGE else "false"}">{name}</button>'
        for name in RANGE_BUTTONS
    )
    return f'<div class="ranges" data-tab="{tab}" role="group" aria-label="Date range">{buttons}</div>'


def sectors_tab(ranks: pd.DataFrame, data: dict) -> str:
    stops = ", ".join(f"{color} {float(pos) * 100:.0f}%" for pos, color in data["heat"]["colorscale"])
    n = int(data["heat"]["zmax"])
    return (
        range_buttons("sectors")
        + '\n<div class="chart-card">\n'
        '<div class="chart-head"><h3>Sector rank vs SPY, weekly</h3></div>\n'
        f'<p class="unit">Sectors ordered by rank on {ranks.index[-1].date()}. Tap a cell for its rank.</p>\n'
        '<div id="chart-heat" class="chart heat"></div>\n'
        '<p id="chart-heat-readout" class="readout" aria-live="polite"></p>\n'
        f'<div class="heat-legend"><span>1 strongest</span>'
        f'<span class="bar" style="background: linear-gradient(to right, {stops})"></span>'
        f"<span>{n} weakest</span></div>\n"
        "</div>"
    )


def macro_tab(regime: pd.DataFrame) -> str:
    cards = []
    for column, spec in GAUGES.items():
        series = regime[column].dropna()
        latest = f"{series.iloc[-1]:.2f}" if not series.empty else "n/a"
        as_of = f"{series.index[-1]:%b} {series.index[-1].day}" if not series.empty else ""
        cards.append(
            '<div class="chart-card">\n'
            f'<div class="chart-head"><h3>{spec["title"]}</h3>'
            f'<span class="latest">{latest} <span class="unit">{as_of}</span></span></div>\n'
            f'<p class="unit">{spec["unit"]}</p>\n'
            f'<div id="chart-{column}" class="chart"></div>\n'
            "</div>"
        )
    return range_buttons("macro") + '\n<div class="gauges">\n' + "\n".join(cards) + "\n</div>"


def chart_parts() -> dict:
    """The pieces build_site.py puts into index.html."""
    ranks, regime = load_inputs()
    data = chart_data(ranks, regime)
    return {
        "style": CHART_STYLE,
        "plotly_src": PLOTLY_SRC,
        "sectors_html": sectors_tab(ranks, data),
        "macro_html": macro_tab(regime),
        "script": CHART_SCRIPT.replace("__DATA__", json.dumps(data, separators=(",", ":"))),
    }


def redirect_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="0; url={REDIRECT_TARGET}">
<title>Sector rotation</title>
<script>location.replace("{REDIRECT_TARGET}");</script>
</head>
<body>
<p>The dashboard has moved to <a href="{REDIRECT_TARGET}">the Macro tab</a>.</p>
</body>
</html>
"""


def main() -> int:
    try:
        ranks, regime = load_inputs()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(redirect_page(), encoding="utf-8")

    print(f"Regime data: {regime.index[0].date()} to {regime.index[-1].date()}")
    print(f"Sector ranks: {ranks.index[0].date()} to {ranks.index[-1].date()} ({len(ranks)} weeks)")
    print(f"Saved redirect to {OUTPUT_PATH} (the charts are built into index.html by build_site.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
