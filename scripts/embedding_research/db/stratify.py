"""DuckDB persistence for the stratified corpus table."""

from __future__ import annotations


def load_stratified_sids(con, config_hash: str) -> frozenset[str]:
    """Return all song_ids for a given config_hash from stratified_corpus."""
    rows = con.execute(
        "SELECT song_id FROM stratified_corpus WHERE config_hash = ?",
        [config_hash],
    ).fetchall()
    return frozenset(row[0] for row in rows)


def write_stratified_sids(con, config_hash: str, song_ids: frozenset[str]) -> None:
    """Bulk-insert song_ids into stratified_corpus for the given config_hash."""
    con.executemany(
        "INSERT INTO stratified_corpus (config_hash, song_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
        [(config_hash, sid) for sid in sorted(song_ids)],
    )


def clear_stale_stratification(con, config_hash: str) -> None:
    """Delete all rows from stratified_corpus where config_hash != the given hash."""
    con.execute(
        "DELETE FROM stratified_corpus WHERE config_hash != ?",
        [config_hash],
    )
