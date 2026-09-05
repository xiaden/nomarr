"""Active run-provenance section.

Research-only.  Renders the active ``run_provenance`` rows (command lines, config hashes,
artifact hashes, statuses) with an explicit scope-and-limitations note describing what this
report reused / refused to reuse.  This section performs no inference — it reports the
completed phases that produced the current catalog analysis and head provenance.
"""

from __future__ import annotations

from scripts.embedding_research.db.provenance import read_run_provenance

from ._base import fmt, make_panel, make_section, make_table


def _history_rows(rows: list[dict]) -> list[dict]:
    return [
        {
            "run_id": fmt(r.get("run_id")),
            "phase": fmt(r.get("phase")),
            "status": fmt(r.get("status")),
            "started_at": fmt(r.get("started_at")),
            "finished_at": fmt(r.get("finished_at")),
            "command_line": fmt(r.get("command_line")) if r.get("command_line") else "—",
            "config_hash": fmt(r.get("config_hash")),
            "song_count": fmt(r.get("song_count")),
            "warning_count": fmt(r.get("warning_count")),
        }
        for r in rows
    ]


def _hash_rows(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        inp = r.get("input_artifact_hashes")
        oup = r.get("output_artifact_hashes")
        if not inp and not oup:
            continue
        out.append(
            {
                "run_id": fmt(r.get("run_id")),
                "phase": fmt(r.get("phase")),
                "input_artifact_hashes": inp or "—",
                "output_artifact_hashes": oup or "—",
            }
        )
    return out


def section_provenance(con, *, run_id: str | None = None) -> dict:
    """Render the active ``run_provenance`` rows and scope/limitations notes."""
    try:
        rows = read_run_provenance(con)
    except Exception:
        rows = []

    active_rows = rows
    if run_id is not None:
        active_rows = [r for r in rows if r.get("run_id") == run_id]

    tables = []
    stats = [{"label": "recorded runs", "value": len(active_rows)}]
    phases = sorted({str(r.get("phase")) for r in active_rows if r.get("phase")})
    stats.append({"label": "phases", "value": len(phases)})
    n_complete = sum(1 for r in active_rows if r.get("status") == "complete")
    stats.append({"label": "completed", "value": n_complete})

    if active_rows:
        history = _history_rows(active_rows)
        history_sorted = sorted(
            history,
            key=lambda d: (
                str(d["run_id"]),
                str(d["phase"]),
            ),
        )
        tables.append(
            make_table(
                history_sorted,
                id="run_history",
                title="Run history (command lines & config hashes)",
                collapsible=True,
                summary_text=f"{len(history_sorted)} recorded run(s)",
            )
        )
        hash_rows = _hash_rows(active_rows)
        if hash_rows:
            tables.append(
                make_table(
                    hash_rows,
                    id="artifact_hashes",
                    title="Input / output artifact hashes",
                    collapsible=True,
                    summary_text=f"{len(hash_rows)} run(s) with artifact hashes",
                )
            )

    scope_note = (
        "This report reads the active completed scope: every recorded analyze/head-analysis/"
        "catalog phase that produced current rows. No legacy analyses are reused because none "
        "are active, and no inference is performed at report time — the current report.json / "
        "report.html are rendered verbatim from the completed analysis and head provenance."
    )
    if run_id is not None:
        scope_note = (
            f"This report is scoped to run_id={run_id}. Only that run's analyze rows and "
            f"head provenance feed the sections; no inference is performed at report time."
        )

    panels = [
        make_panel(
            "provenance-scope-and-limitations",
            "Scope & limitations",
            open=True,
            text=scope_note,
        )
    ]

    return make_section(
        "provenance",
        "Run Provenance",
        description=(
            "Active run provenance: recorded phases with their command lines, config hashes, "
            "input/output artifact hashes, statuses, and the report's reuse / refusal notes."
        ),
        stats=stats,
        tables=tables,
        panels=panels,
    )
