"""Corpus health and overview sections."""

from __future__ import annotations

from ._base import _HAS_MPL, fmt, png, table

try:
    import matplotlib.pyplot as plt
except ImportError:
    pass


def disc_score_warning(con) -> str:
    """Return a banner HTML string if disc_score is degenerate (e.g. single-artist corpus)."""
    try:
        n_artists = con.execute("SELECT COUNT(DISTINCT artist) FROM songs").fetchone()[0]
        n_songs = con.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        if n_artists < 2:
            return f"""
<div style="background:#3b1f1f;border:1px solid #a33;border-radius:6px;padding:14px 18px;margin-bottom:24px">
  <strong style="color:#f87171">&#9888; Single-artist corpus detected</strong>
  <p style="color:#e0a0a0;margin-top:6px;font-size:13px">
    All {n_songs} songs are from the same artist, so <code>disc_score</code> cannot be computed
    (requires both within-artist <em>and</em> cross-artist pairs). Sections that rank by
    <code>disc_score</code> will show 0.0 everywhere &mdash; this is expected, not a bug.
    Add songs from multiple artists to get meaningful discrimination scores.
    The <strong>Head &times; Similarity Correlation</strong> and <strong>PTC / CTP Alignment</strong>
    sections are unaffected and contain real data.
  </p>
</div>
"""
        solo_artists = con.execute(
            "SELECT COUNT(*) FROM (SELECT artist FROM songs GROUP BY artist HAVING COUNT(*) = 1)"
        ).fetchone()[0]
        if solo_artists == n_artists:
            return f"""
<div style="background:#2d2a1a;border:1px solid #a08030;border-radius:6px;padding:14px 18px;margin-bottom:24px">
  <strong style="color:#fbbf24">&#9888; No within-artist pairs</strong>
  <p style="color:#d4b96a;margin-top:6px;font-size:13px">
    Every artist has exactly 1 song ({n_songs} songs, {n_artists} artists), so
    <code>disc_score</code> cannot be computed. Add multiple songs per artist
    to get meaningful retrieval discrimination scores.
  </p>
</div>
"""
    except Exception:
        pass
    return ""


def section_corpus(con) -> str:
    """Corpus overview: counts, per-artist distribution, trust signal for all metrics."""
    try:
        n_songs = con.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
    except Exception:
        return ""

    if n_songs == 0:
        return """
<section id="corpus">
  <h2>Corpus</h2>
  <p class="empty">No songs in the database yet. Run the <em>embed</em> phase.</p>
</section>
"""

    try:
        n_artists = con.execute("SELECT COUNT(DISTINCT artist) FROM songs").fetchone()[0]
        n_albums = con.execute("SELECT COUNT(DISTINCT album) FROM songs").fetchone()[0]
        per_artist = con.execute(
            "SELECT COALESCE(artist, '<unknown>') AS artist, COUNT(*) AS n "
            "FROM songs GROUP BY artist ORDER BY n DESC, artist"
        ).df()
    except Exception:
        return ""

    mean_spa = round(n_songs / max(1, n_artists), 1)
    multi = int((per_artist["n"] >= 2).sum())

    # Stats bar
    stats_html = (
        f'<div class="stat-row">'
        f'<div class="stat"><span class="stat-val">{n_songs}</span><span class="stat-lbl">songs</span></div>'
        f'<div class="stat"><span class="stat-val">{n_artists}</span><span class="stat-lbl">artists</span></div>'
        f'<div class="stat"><span class="stat-val">{n_albums}</span><span class="stat-lbl">albums</span></div>'
        f'<div class="stat"><span class="stat-val">{mean_spa}</span><span class="stat-lbl">avg songs/artist</span></div>'
        f'<div class="stat"><span class="stat-val">{multi}</span><span class="stat-lbl">artists with &#8805;2 songs</span></div>'
        f'</div>'
    )

    # Songs-per-artist horizontal bar chart
    chart_html = ""
    if _HAS_MPL and len(per_artist) > 0:
        display = per_artist.head(40)  # cap at 40 to keep chart readable
        artists = display["artist"].tolist()[::-1]
        counts = display["n"].tolist()[::-1]
        colors = ["#4ade80" if c >= 2 else "#f87171" for c in counts]

        fig, ax = plt.subplots(figsize=(7, max(2.5, len(artists) * 0.28)))
        ax.barh(artists, counts, color=colors, height=0.7)
        ax.set_xlabel("song count", color="#999", fontsize=9)
        ax.set_title(
            "Songs per artist (green \u2265 2, red = 1)", color="#e0e0e8", fontsize=10
        )
        ax.axvline(2, color="#555", linewidth=0.8, linestyle="--")
        ax.grid(True, axis="x", alpha=0.12, color="#555")
        ax.spines[["top", "right"]].set_visible(False)
        for sp in ax.spines.values():
            sp.set_color("#333")
        ax.set_facecolor("#12131e")
        fig.patch.set_facecolor("#1a1b26")
        ax.tick_params(colors="#aaa", labelsize=8)
        fig.tight_layout()
        chart_html = png(fig)

    # Detailed table
    tbl_rows = per_artist.rename(columns={"n": "songs"}).to_dict("records")
    tbl_html = (
        f'<details style="margin-top:14px">'
        f'<summary>Full artist breakdown ({len(per_artist)} artists)</summary>'
        f'<div class="details-body">{table(tbl_rows)}</div>'
        f'</details>'
    )

    return f"""
<section id="corpus">
  <h2>Corpus Overview</h2>
  <div class="card">
    <p class="muted">
      Trust signal for all discrimination metrics.
      Artists with only 1 song cannot form within-artist pairs, so <code>disc_score</code>
      cannot be computed for them. Green bars = contributor; red bars = no-pair songs.
    </p>
    {stats_html}
  </div>
  {chart_html}
  {tbl_html}
</section>
"""
