# Migrate Embedding Research Report: Matplotlib → Plotly + JSON Output — Design Document

**Status:** Draft  
**Author:** rnd-dd-author  
**Created:** 2026-05-23  

---

## Scope

scripts/embedding_research/report/ — all seven report modules plus __init__.py. No changes outside this directory except: requirements.txt (swap matplotlib/seaborn for plotly), contracts.md (updated signatures). The main nomarr application is unaffected.

---

## Problem Statement

The report package currently renders all charts via matplotlib, encodes them as base64 PNG `<img>` tags, and returns HTML strings from every `section_*` function. This has two compounding problems:

1. **Static images only.** Matplotlib charts are opaque PNGs — no hover, no zoom, no programmatic re-rendering. Plotly produces interactive `<div>` elements with embedded JS at negligible additional file size cost.

2. **No machine-readable output.** Every section function returns `str` (HTML). There is no way to consume the report results programmatically — e.g. to compare two runs, feed scores into a CI gate, or plot cross-run trends — without re-scraping the HTML. Adding a `report.json` alongside `report.html` provides a stable structured contract for downstream consumers.

Secondary: the `_HAS_MPL` guard creates two dead code paths. All environments that run the report already have Python dependencies available; the fallback-to-table path is never tested and adds maintenance burden.

---

## Architecture

## Module Change Map

| File | Nature of change |
| --- | --- |
| `_base.py` | Remove `_HAS_MPL`, `matplotlib` imports, `png()`, `style_ax()`. Add `apply_dark_theme()`, `chart_div()`, new `bar_chart()`, new `scatter_chart()`. Keep `table()`, `fmt()`, `empty_df()`, `table_exists()`, `CSS`, column lists. |
| `_retrieval.py` | Call signatures to `bar_chart()` and `scatter_chart()` unchanged; callers embed returned div string directly. Return type changes from `str` to `tuple[str, dict]` for `section_per_backbone` and `section_unified_table`. |
| `_heads.py` | Remove all `plt.subplots()` + `style_ax()` + `png()` blocks (6 sections). Replace with `go.Figure()` / `px.*` + `apply_dark_theme()` + `chart_div()`. All 6 `section_*` functions return `tuple[str, dict]`. |
| `_binned.py` | Same as `_heads.py` — 4 `section_*` functions, remove inline matplotlib, add Plotly. |
| `_efficiency.py` | Single section horizontal bar → `go.Bar(orientation='h')`. Returns `tuple[str, dict]`. |
| `_corpus.py` | Single section horizontal bar → `go.Bar(orientation='h')`. Returns `tuple[str, dict]`. |
| `_summary.py` | No charts, already returns `str`. Change to return `tuple[str, dict]`. |
| `__init__.py` | Update `_step()` and `run()` to unpack `tuple[str, dict]`, collect dicts, write `report.json`. Add Plotly JS delivery to HTML shell. |
| `requirements.txt` | Remove `matplotlib>=3.8.0`, `seaborn>=0.13.0`. Add `plotly>=5.20.0`. |
| `contracts.md` | Update all `section_*` return types, `bar_chart`/`scatter_chart` signatures, remove `_HAS_MPL`, add `apply_dark_theme`, `chart_div`. |

---

## `_base.py` — New Primitives

### Dark theme constants (module-level, private)

```
_PLOT_BG    = "#12131e"
_PAPER_BG   = "#1a1b26"
_GRID_COLOR = "rgba(85,85,85,0.12)"   # #555 @ alpha 0.12
_FONT_COLOR = "#e0e0e8"
```

### `apply_dark_theme(fig: go.Figure) -> None`

Mutates the figure in-place. Applies to all axes including subplots via `update_xaxes`/`update_yaxes`.

```
fig.update_layout(
    plot_bgcolor  = _PLOT_BG,
    paper_bgcolor = _PAPER_BG,
    font          = dict(color=_FONT_COLOR),
    legend        = dict(bgcolor=_PAPER_BG, bordercolor="#333", borderwidth=1),
)
fig.update_xaxes(gridcolor=_GRID_COLOR, zerolinecolor=_GRID_COLOR, linecolor="#333")
fig.update_yaxes(gridcolor=_GRID_COLOR, zerolinecolor=_GRID_COLOR, linecolor="#333")
```

### `chart_div(fig: go.Figure) -> str`

Replacement for `png(fig)`. Returns a Plotly `<div>` string with `full_html=False, include_plotlyjs=False` — Plotly JS is loaded once in the HTML shell (see `__init__.py`).

### `bar_chart(labels, values, colors, title, xlabel, *, orientation="h") -> str`

New Plotly implementation. Horizontal by default (matches existing behaviour — the old `bar_chart` used `ax.barh()`). Uses `go.Bar(orientation=orientation)` with `apply_dark_theme`. Returns `chart_div(fig)`.

Pareto-front text annotations from the old matplotlib version are dropped — Plotly provides hover natively.

### `scatter_chart(x, y, labels, colors, title, xlabel, ylabel) -> str`

New Plotly implementation. Uses `go.Scatter(mode="markers+text")` with selective labelling (Pareto front + axis bests, same logic as current `_pareto_front_indices()`). Returns `chart_div(fig)`.

`_pareto_front_indices()` helper is kept unchanged.

---

## Chart Type Inventory and Plotly Equivalents

| Module | Section | Current chart | Plotly equivalent |
| --- | --- | --- | --- |
| `_retrieval.py` | `section_per_backbone` | `bar_chart()` (horizontal bar) | new `bar_chart()` |
| `_retrieval.py` | `section_per_backbone` | `scatter_chart()` | new `scatter_chart()` |
| `_heads.py` | `section_head_sim_corr` | `ax.plot()` multi-line per backbone × bin_mode | `go.Scatter(mode="lines+markers")` per head, subplots for bin_modes |
| `_heads.py` | `section_ptc_ctp_alignment` | `ax.plot()` per backbone | `go.Scatter(mode="lines+markers")` |
| `_heads.py` | `section_head_heatmap` | `ax.imshow()` | `go.Heatmap()` |
| `_heads.py` | `section_flat_head_comparison` | `ax.barh()` per backbone | `go.Bar(orientation='h')` |
| `_heads.py` | `section_head_agreement` | `ax.plot()` per backbone | `go.Scatter(mode="lines+markers")` |
| `_heads.py` | `section_ptc_ctp_retrieval_comparison` | `ax.plot()` per backbone | `go.Scatter(mode="lines+markers")` |
| `_binned.py` | `section_threshold_sweep` | `ax.plot()` per bin_mode | `go.Scatter(mode="lines+markers")` |
| `_binned.py` | `section_bin_diversity` | `ax.plot()` per backbone | `go.Scatter(mode="lines+markers")` |
| `_binned.py` | `section_segment_counts` | `ax.plot()` | `go.Scatter(mode="lines+markers")` |
| `_binned.py` | `section_bin_mode_comparison` | `ax.plot()` | `go.Scatter(mode="lines+markers")` |
| `_efficiency.py` | `section_efficiency` | `ax.barh()` | `go.Bar(orientation='h')` |
| `_corpus.py` | `section_corpus` | `ax.barh()` | `go.Bar(orientation='h')` |

**Rule:** use `go.Figure()` with explicit trace construction for all charts (over `px.*`) to maintain full control of hover templates, subplot layout, and dark theme application. `px.*` is acceptable only for trivial single-series prototypes.

**Multi-subplot charts** (e.g. `section_head_sim_corr` renders one subplot per `bin_mode`): use `make_subplots(rows=1, cols=n_bm)` from `plotly.subplots`, then call `apply_dark_theme(fig)` once after all traces are added.

---

## `__init__.py` — Orchestration Changes

### `_step()` updated contract

```python
def _step(label: str, fn, *args, **kwargs) -> tuple[str, dict]:
    ...
    result = fn(*args, **kwargs)
    return result  # callers unpack html, data = _step(...)
```

`disc_score_warning()` is NOT a `section_*` function — it remains `(con) -> str` and is called directly without `_step`.

### `run()` updated skeleton

```python
html_parts: list[str] = []
json_sections: dict[str, dict] = {}

for key, fn, args in SECTION_TABLE:   # ordered list of (json_key, fn, positional_args)
    html, data = _step(key, fn, *args)
    html_parts.append(html)
    json_sections[key] = data

body_html = disc_score_warning(con) + "".join(html_parts)
...
json_out = {
    "generated": run_ts,
    "sections": json_sections,
}
json_path = out_path.with_name("report.json")
json_path.write_text(json.dumps(json_out, indent=2, default=str), encoding="utf-8")
```

### HTML shell — Plotly JS delivery

Add to `<head>` in `_shell()`:

```html
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
```

All `chart_div()` calls use `include_plotlyjs=False`; the single script tag loads Plotly once. The version pin (`2.35.2`) ensures reproducibility. For offline mode, `run()` gains an `offline: bool = False` parameter; when `True`, the shell uses `plotly.offline.get_plotlyjs()` to embed the ~3 MB bundle inline instead of the CDN tag.

### CSS update

The existing `img { width: 100%; max-width: 760px; ... }` rule applies to base64 chart images and must be preserved for any remaining `<img>` elements. Plotly divs render as `<div class="plotly-graph-div">` — they need a width constraint added to CSS:

```css
.plotly-graph-div {
  width: 100%;
  max-width: 900px;
}
```

Plotly default height is set via `fig.update_layout(height=...)` per chart; no global CSS height override needed.

---

## Design Goals

1. Replace all matplotlib chart production with Plotly interactive charts (dark-themed, consistent with existing CSS palette).
2. Provide `apply_dark_theme(fig)` as a single-call Plotly equivalent of `style_ax()`.
3. Replace `bar_chart()` and `scatter_chart()` in `_base.py` with Plotly equivalents that return HTML div strings instead of base64 PNG strings.
4. Change every `section_*` function signature from `(…) -> str` to `(…) -> tuple[str, dict]` where the dict is machine-readable structured data for that section.
5. Have `__init__.py` collect all dicts and write `report.json` alongside `report.html`.
6. Drop the `_HAS_MPL` guard and the matplotlib/seaborn dependencies entirely.
7. Update `contracts.md` to reflect the new public API.

---

## Constraints

- Pure Python + Plotly. No TypeScript build, no Node, no webpack.
- `plotly>=5.20.0` is the minimum version pinned (supports `make_subplots`, `go.Heatmap`, `fig.to_html(full_html=False)`).
- No changes to any module outside `scripts/embedding_research/`.
- The existing HTML CSS shell (`CSS` constant in `_base.py`) stays intact — only the `img` → plotly div adjustment in CSS.
- `disc_score_warning()` keeps its `(con) -> str` signature — it is a utility banner, not a `section_*` function, and does not contribute to `report.json`.
- `table()`, `fmt()`, `empty_df()`, `table_exists()`, `FLAT_COLUMNS`, `BINNED_COLUMNS` are unchanged.
- Forward-only: existing `report.html` files from old runs become stale (no back-compat shim needed — this is research tooling, not a production API).

---

## Open Questions

1. **Plotly CDN vs bundled JS for offline use.** The design proposes CDN default with an `offline=True` flag. Should offline be the default instead, given researchers may run this inside containers without internet access? The bundled size is ~3 MB inline; CDN requires outbound HTTPS to `cdn.plot.ly`.

2. **Version pin strategy.** The design pins `plotly-2.35.2.min.js` in the CDN URL. Should this be a constant in `_base.py` (e.g. `_PLOTLY_CDN_VERSION = "2.35.2"`) so it's a single-line update, or derived dynamically from the installed plotly package version at report generation time?

3. **Responsive chart height.** Matplotlib charts had fixed `figsize` per chart (e.g. `figsize=(7, 3.5)` for threshold sweep). Plotly default height is 450px. Should there be a standard set of height constants in `_base.py` (e.g. `_H_SMALL = 300`, `_H_MED = 400`, `_H_LARGE = 550`) or should each chart specify its own height?

4. **Heatmap colour scale.** The old `ax.imshow()` in `section_head_heatmap` uses matplotlib's default colormap. The Plotly `go.Heatmap` design uses `colorscale="RdYlGn"` (red-low, green-high) to match the "higher disc_score = better" semantics. Confirm or override.

---
