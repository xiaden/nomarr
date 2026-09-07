"""Active songs / corpus health section.

Research-only.  Renders the retained ``songs`` table as corpus health for the active
matching corpus.  No retired pipeline vocabulary.
"""

from __future__ import annotations

import plotly.graph_objects as go

from ._base import (
    _FONT_COLOR,
    _GRID_COLOR,
    _H_SMALL,
    apply_dark_theme,
    make_chart,
    make_section,
    make_table,
)


def _label_degeneracy_warnings(
    con,
    ruler: str,
    label_column: str,
    *,
    error_id: str,
    error_message: str,
    pairs_id: str,
    pairs_message: str,
) -> list[dict]:
    """Degeneracy warning for ONE label ruler's corpus population (artist / genre).

    A ruler whose labeled corpus population has fewer than two distinct labels cannot form
    the within-vs-cross pairs its ``disc_<ruler>`` aggregate needs; the report surfaces this
    as an ``error`` (single label value) or a ``warning`` (every label has exactly one song,
    so no within-<ruler> pair exists).  ``label_column`` is a ``songs`` column; NULL/blank
    values count as MISSING labels for that ruler and are excluded from the labeled
    population (mirroring the compute-layer per-ruler missing-label exclusion).
    """
    try:
        n_labeled = con.execute(
            f"SELECT COUNT(*) FROM songs WHERE {label_column} IS NOT NULL "
            f"AND TRIM(CAST({label_column} AS VARCHAR)) <> ''"
        ).fetchone()[0]
        n_distinct = con.execute(
            f"SELECT COUNT(DISTINCT {label_column}) FROM songs WHERE {label_column} IS NOT NULL "
            f"AND TRIM(CAST({label_column} AS VARCHAR)) <> ''"
        ).fetchone()[0]
    except Exception:
        return []
    if n_distinct < 2:
        return [
            {
                "id": error_id,
                "level": "error",
                "message": error_message,
                "detail": (
                    f"Only {n_labeled} labeled song(s) across {n_distinct} distinct "
                    f"{ruler} label value(s), so disc_{ruler} cannot be computed (it needs "
                    f"both within-{ruler} and cross-{ruler} pair scores). Discrimination "
                    f"metrics for the {ruler} ruler in the analysis and winners sections will "
                    f"show 0.0 (guarded) \u2014 expected, not a bug. Add songs across multiple "
                    f"{ruler} labels to get meaningful {ruler} discrimination."
                ),
            }
        ]
    try:
        n_solo = con.execute(
            f"SELECT COUNT(*) FROM (SELECT {label_column} FROM songs "
            f"WHERE {label_column} IS NOT NULL AND TRIM(CAST({label_column} AS VARCHAR)) <> '' "
            f"GROUP BY {label_column} HAVING COUNT(*) = 1)"
        ).fetchone()[0]
    except Exception:
        return []
    if n_solo == n_distinct:
        return [
            {
                "id": pairs_id,
                "level": "warning",
                "message": pairs_message,
                "detail": (
                    f"Every {ruler} label value has exactly 1 song ({n_distinct} distinct "
                    f"{ruler} labels), so disc_{ruler} cannot be computed. Add multiple songs "
                    f"per {ruler} label to get meaningful {ruler} retrieval discrimination."
                ),
            }
        ]
    return []


def ruler_disc_warnings(con) -> list[dict]:
    """Return per-ruler discrimination warnings when a ruler's labeled population is degenerate.

    Emits the historical ``single_artist`` / ``no_within_artist_pairs`` artist warnings plus the
    analogous ``single_genre`` / ``no_within_genre_pairs`` genre warnings, each computed from
    that ruler's OWN labeled population (the ``songs.artist`` / ``songs.genre`` columns with
    NULL/blank excluded as missing).  Head-ruler discrimination degeneracy is NOT surfaced here
    because per-song head-tuple labels live in the committed head artifacts (not a ``songs``
    column the report corpus layer can read); the head ruler's ``disc_head`` guard is enforced
    at the compute layer (:class:`RulerResult.disc_guard`) instead.
    """
    warnings: list[dict] = []
    warnings.extend(
        _label_degeneracy_warnings(
            con,
            "artist",
            "artist",
            error_id="single_artist",
            error_message="Single-artist corpus detected",
            pairs_id="no_within_artist_pairs",
            pairs_message="No within-artist pairs",
        )
    )
    warnings.extend(
        _label_degeneracy_warnings(
            con,
            "genre",
            "genre",
            error_id="single_genre",
            error_message="Single-genre corpus detected",
            pairs_id="no_within_genre_pairs",
            pairs_message="No within-genre pairs",
        )
    )
    return warnings


def section_corpus(con) -> dict:
    """Corpus overview: counts, per-artist distribution chart, full breakdown table."""
    try:
        n_songs = con.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
    except Exception:
        return make_section("corpus", "Active Songs & Corpus Health", empty_message="No songs table found.")

    if n_songs == 0:
        return make_section(
            "corpus",
            "Active Songs & Corpus Health",
            empty_message="No songs in the database yet. Run the ingest phase.",
        )

    try:
        n_artists = con.execute("SELECT COUNT(DISTINCT artist) FROM songs").fetchone()[0]
        n_albums = con.execute("SELECT COUNT(DISTINCT album) FROM songs").fetchone()[0]
        per_artist = con.execute(
            "SELECT COALESCE(artist, '<unknown>') AS artist, COUNT(*) AS n "
            "FROM songs GROUP BY artist ORDER BY n DESC, artist"
        ).df()
    except Exception:
        return make_section("corpus", "Active Songs & Corpus Health", empty_message="Could not load corpus data.")

    mean_spa = round(n_songs / max(1, n_artists), 1)
    multi = int((per_artist["n"] >= 2).sum())

    stats = [
        {"label": "songs", "value": n_songs},
        {"label": "artists", "value": n_artists},
        {"label": "albums", "value": n_albums},
        {"label": "avg songs/artist", "value": mean_spa},
        {"label": "artists with \u22652 songs", "value": multi},
    ]

    charts = []
    if len(per_artist) > 0:
        display = per_artist.head(40)
        artists = display["artist"].tolist()[::-1]
        counts = display["n"].tolist()[::-1]
        bar_colors = ["#4ade80" if c >= 2 else "#f87171" for c in counts]
        height = max(_H_SMALL, len(artists) * 22 + 60)
        fig = go.Figure([go.Bar(x=counts, y=artists, orientation="h", marker_color=bar_colors)])
        apply_dark_theme(fig, grid=False)
        fig.add_vline(x=2, line_dash="dash", line_color="#555", line_width=0.8)
        fig.update_layout(
            title={"text": "Songs per artist (green \u22652, red = 1)", "font": {"color": _FONT_COLOR}},
            height=height,
            xaxis={
                "title": "song count",
                "showgrid": True,
                "gridcolor": _GRID_COLOR,
                "gridwidth": 0.5,
            },
        )
        charts.append(make_chart(fig, id="artist_distribution", title="Songs per artist"))

    tbl_rows = per_artist.rename(columns={"n": "songs"}).to_dict("records")
    tables = [
        make_table(
            tbl_rows,
            id="per_artist",
            collapsible=True,
            summary_text=f"Full artist breakdown ({len(per_artist)} artists)",
        )
    ]

    return make_section(
        "corpus",
        "Active Songs & Corpus Health",
        description=(
            "Active matching corpus used by the catalog analysis and head analysis. "
            "Trust signal for all discrimination metrics. "
            "Artists with only 1 song cannot form within-artist pairs, so disc_artist "
            "cannot be computed for them. "
            "Green bars = contributor (\u22652 songs); red bars = no-pair songs (1 song)."
        ),
        stats=stats,
        charts=charts,
        tables=tables,
    )
