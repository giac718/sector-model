"""Build a one-page dashboard: regime indicators above the sector rank heatmap.

Reads output/rank_history.csv and data/regime.csv and saves
output/dashboard.html. All panels share one x-axis, so zooming or panning
one moves the others.
"""

import sys
from pathlib import Path

import pandas as pd
from plotly.subplots import make_subplots
import plotly.graph_objects as go

from rank_history import build_heatmap

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RANKS_PATH = PROJECT_ROOT / "output" / "rank_history.csv"
REGIME_PATH = PROJECT_ROOT / "data" / "regime.csv"
OUTPUT_PATH = PROJECT_ROOT / "output" / "dashboard.html"

START = "2019-01-01"

# Regime column -> panel title, in top-to-bottom order
LINE_PANELS = {
    "credit_spread": "Credit spread: Baa yield minus 10-year Treasury (% pts)",
    "curve_10y2y": "Yield curve: 10-year minus 2-year Treasury (% pts)",
    "vix": "VIX",
    "dollar": "Broad US dollar index",
}
HEATMAP_TITLE = "Sector rank vs SPY, weekly (1 = strongest)"
# Regime column -> name shown in the hover label
HOVER_NAMES = {
    "credit_spread": "Credit spread (Baa − 10y)",
    "curve_10y2y": "Yield curve (10y − 2y)",
    "vix": "VIX",
    "dollar": "Dollar index",
}

LINE_COLOR = "#2a6fb0"
ZERO_LINE_COLOR = "#555555"
MUTED_TEXT = "#555555"
HEATMAP_SHARE = 0.52  # fraction of the plot height given to the heatmap
PANEL_GAP = 0.035     # vertical gap between panels, as a fraction of plot height

# Runs in the browser: after every zoom or pan, rescale each line chart's
# y-axis to the data inside the visible date range.
RESCALE_Y_SCRIPT = """
(function () {
  var gd = document.getElementById('{plot_id}');
  var busy = false;

  function rescale() {
    if (busy) return;
    var layout = gd._fullLayout;
    var update = {};
    gd._fullData.forEach(function (trace, i) {
      if (trace.type !== 'scatter') return;
      var xName = trace.xaxis.replace('x', 'xaxis');
      var yName = trace.yaxis.replace('y', 'yaxis');
      var range = layout[xName].range.map(function (d) {
        return new Date(String(d).replace(' ', 'T')).getTime();
      });
      var lo = Infinity, hi = -Infinity;
      gd.calcdata[i].forEach(function (pt) {
        if (typeof pt.y !== 'number' || !isFinite(pt.y)) return;
        if (pt.x < range[0] || pt.x > range[1]) return;
        if (pt.y < lo) lo = pt.y;
        if (pt.y > hi) hi = pt.y;
      });
      if (lo === Infinity) return;  // nothing visible in this panel
      if (yName === '{zero_axis}') {  // keep the dashed zero line in view
        lo = Math.min(lo, 0);
        hi = Math.max(hi, 0);
      }
      var pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.05 || 1;
      update[yName + '.range'] = [lo - pad, hi + pad];
    });
    if (!Object.keys(update).length) return;
    busy = true;
    Plotly.relayout(gd, update).then(function () { busy = false; });
  }

  gd.on('plotly_relayout', rescale);
})();
"""


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    for path, script in [(RANKS_PATH, "rank_history.py"), (REGIME_PATH, "fetch_regime.py")]:
        if not path.exists():
            raise RuntimeError(f"{path} not found. Run scripts/{script} first.")

    ranks = pd.read_csv(RANKS_PATH, parse_dates=["Date"]).set_index("Date")
    regime = pd.read_csv(REGIME_PATH, parse_dates=["Date"]).set_index("Date")

    missing = [c for c in LINE_PANELS if c not in regime.columns]
    if missing:
        raise RuntimeError(f"Missing columns in {REGIME_PATH.name}: {missing}")

    return ranks.loc[START:], regime.loc[START:]


def build_dashboard(ranks: pd.DataFrame, regime: pd.DataFrame) -> go.Figure:
    n_lines = len(LINE_PANELS)
    heatmap_row = n_lines + 1
    gaps = PANEL_GAP * n_lines
    # The gaps come out of the line charts' half, so the heatmap keeps its full share.
    line_share = (1 - HEATMAP_SHARE - gaps) / n_lines

    fig = make_subplots(
        rows=heatmap_row,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=PANEL_GAP,
        row_heights=[line_share] * n_lines + [HEATMAP_SHARE],
        subplot_titles=[*LINE_PANELS.values(), HEATMAP_TITLE],
    )

    for row, column in enumerate(LINE_PANELS, start=1):
        fig.add_trace(
            go.Scatter(
                x=regime.index,
                y=regime[column],
                mode="lines",
                line=dict(color=LINE_COLOR, width=1.5),
                connectgaps=False,  # blank days stay as gaps in the line
                hovertemplate=(
                    "%{x|%a %b %-d, %Y}<br>"
                    + HOVER_NAMES[column]
                    + ": %{y:.2f}<extra></extra>"
                ),
                showlegend=False,
            ),
            row=row,
            col=1,
        )
        fig.update_yaxes(
            row=row, col=1, nticks=4, gridcolor="#ececec", zeroline=False,
            tickfont=dict(size=11),
        )

    curve_row = list(LINE_PANELS).index("curve_10y2y") + 1
    fig.add_hline(
        y=0, row=curve_row, col=1,
        line=dict(color=ZERO_LINE_COLOR, width=1, dash="dash"),
    )

    # Same heatmap trace as rank_heatmap.html: colours, sector order, and hover.
    heatmap = build_heatmap(ranks).data[0]
    fig.add_trace(heatmap, row=heatmap_row, col=1)
    fig.update_yaxes(
        row=heatmap_row, col=1,
        autorange="reversed", type="category", showgrid=False,
    )
    # Keep the colour bar beside the heatmap rather than the whole page.
    bottom, top = fig.layout[f"yaxis{heatmap_row}"].domain
    fig.update_traces(
        selector=dict(type="heatmap"),
        colorbar=dict(len=top - bottom, lenmode="fraction", y=bottom, yanchor="bottom"),
    )

    # Left-align the panel titles and keep them quieter than the page title.
    fig.update_annotations(x=0, xanchor="left", font=dict(size=13, color=MUTED_TEXT))

    last_day = max(regime.index[-1], ranks.index[-1])
    fig.update_xaxes(showgrid=False, range=[START, last_day + pd.Timedelta(days=7)])
    fig.update_xaxes(row=heatmap_row, col=1, ticks="outside", tickcolor="#cccccc")
    fig.update_layout(
        title=dict(
            text=(
                "Sector rotation dashboard"
                "<br><sup>Market regime indicators and weekly sector ranks. "
                f"Sectors ordered by rank on {ranks.index[-1].date()}.</sup>"
            ),
            x=0.01,
            xanchor="left",
        ),
        template="plotly_white",
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=13),
        margin=dict(l=70, r=30, t=95, b=35),
        hovermode="closest",
        hoverlabel=dict(bgcolor="white", font_size=13),
    )
    return fig


def main() -> int:
    try:
        ranks, regime = load_inputs()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    fig = build_dashboard(ranks, regime)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Layout name of the yield curve panel's y-axis ("yaxis", "yaxis2", ...).
    curve_row = list(LINE_PANELS).index("curve_10y2y") + 1
    zero_axis = "yaxis" if curve_row == 1 else f"yaxis{curve_row}"

    # Fill the browser window, so the heatmap takes about half the page height.
    fig.write_html(
        OUTPUT_PATH, include_plotlyjs="cdn", default_width="100%", default_height="96vh",
        post_script=RESCALE_Y_SCRIPT.replace("{zero_axis}", zero_axis),
    )

    print(f"Regime data: {regime.index[0].date()} to {regime.index[-1].date()}")
    print(f"Sector ranks: {ranks.index[0].date()} to {ranks.index[-1].date()} ({len(ranks)} weeks)")
    print(f"Saved dashboard to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
