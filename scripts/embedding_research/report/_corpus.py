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


def disc_score_warning(con) -> list[dict]:
    """Return warning dicts if disc_score is degenerate (not enough artists / songs)."""
    try:
        n_artists = con.execute("SELECT COUNT(DISTINCT artist) FROM songs").fetchone()[0]
        n_songs = con.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        if n_artists < 2:
            return [
                {
                    "id": "single_artist",
                    "level": "error",
                    "message": "Single-artist corpus detected",
                    "detail": (
                        f"All {n_songs} songs are from the same artist, so disc_score cannot be "
                        f"computed (requires both within-artist and cross-artist pairs). "
                        f"Discrimination metrics in the analysis and winners sections will show "
                        f"0.0 everywhere \u2014 this is expected, not a bug. Add songs from multiple "
                        f"artists to get meaningful discrimination scores. The corpus, "
                        f"head-analysis, and efficiency sections are unaffected."
                    ),
                }
            ]
        solo_artists = con.execute(
            "SELECT COUNT(*) FROM (  SELECT artist FROM songs GROUP BY artist HAVING COUNT(*) = 1)"
        ).fetchone()[0]
        if solo_artists == n_artists:
            return [
                {
                    "id": "no_within_artist_pairs",
                    "level": "warning",
                    "message": "No within-artist pairs",
                    "detail": (
                        f"Every artist has exactly 1 song ({n_songs} songs, {n_artists} artists), "
                        f"so disc_score cannot be computed. Add multiple songs per artist to get "
                        f"meaningful retrieval discrimination scores."
                    ),
                }
            ]
    except Exception:
        pass
    return []


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
            "Artists with only 1 song cannot form within-artist pairs, so disc_score "
            "cannot be computed for them. "
            "Green bars = contributor (\u22652 songs); red bars = no-pair songs (1 song)."
        ),
        stats=stats,
        charts=charts,
        tables=tables,
    )
