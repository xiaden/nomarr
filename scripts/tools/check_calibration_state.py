"""Diagnose whether apply_calibration_wf actually updated the DB."""

from __future__ import annotations

import os
import sys

from sqlalchemy import text

sys.path.insert(0, "/app")
from nomarr.persistence.db import Database

DB_URL = os.environ.get(
    "NOMARR_DB_URL",
    "postgresql+psycopg2://nomarr:nomarr@localhost:5432/nomarr",
)


def main() -> None:
    db = Database(url=DB_URL)

    try:
        # ── Count files with calibration_hash ──────────────────────
        session = db._scoped
        # DIAGNOSTIC-ONLY DIRECT SQL (Plan C classification): the raw queries
        # below (songs calibration_hash counts, mood tags via file_tags/tags
        # JOIN, ml_model_outputs JOIN ml_models, uncalibrated-sample pick)
        # read NON-calibration domains (songs/tags/models/outputs) and are an
        # ad-hoc audit the intent facade does not expose.  They are
        # diagnostic-only direct SQL — NOT facade leaks — and must not be
        # used to justify any facade change.  They are deliberately isolated
        # from the calibration facade migration; calibration data itself is
        # read only through the public ``db.ml`` domain surface above.
        result = session.execute(
            text("SELECT COUNT(*) FROM songs WHERE calibration_hash IS NOT NULL"),
        )
        result.scalar() or 0

        # ── Check calibration version ──────────────────────────────
        db.app.get_calibration_version()
        db.app.get_calibration_last_run()

        # ── Print calibration_state summary ─────────────────────────
        # Plan C: ``list_calibration_states()`` returns ``list[CalibrationState]``
        # domain values (frozen/slotted dataclasses).  They must be read via
        # attributes — never dict-indexed (``s["state_data"]`` would crash).
        states = db.ml.list_calibration_states()
        for s in sorted(states, key=lambda x: x.label):
            _ = (s.p5, s.p95, s.sample_count)

        # ── Sample a calibrated file ────────────────────────────────
        result = session.execute(
            text("SELECT * FROM songs WHERE calibration_hash IS NOT NULL LIMIT 1"),
        )
        row = result.fetchone()

        if row:
            m = row._mapping
            fid: int = m["id"]

            # Mood tags via file_tags → tags JOIN
            tag_result = session.execute(
                text(
                    "SELECT t.name, t.value "
                    "FROM file_tags ft "
                    "JOIN tags t ON t.id = ft.tag_id "
                    "WHERE ft.file_id = :fid AND t.name LIKE 'nom:mood-%'",
                ),
                {"fid": fid},
            )
            mood_tags = [{"name": r[0], "value": r[1]} for r in tag_result.all()]

            for _t in sorted(mood_tags, key=lambda x: x["name"]):
                pass

            # Check segment_scores_stats equivalent (ml_model_outputs)
            stats_result = session.execute(
                text(
                    "SELECT m.id AS model_id, m.model_type, "
                    "o.label, o.output_data "
                    "FROM ml_model_outputs o "
                    "JOIN ml_models m ON m.id = o.model_id "
                    "WHERE o.file_id = :fid",
                ),
                {"fid": fid},
            )
            stats_rows = stats_result.all()

            labels_by_model: dict[str, list[str]] = {}
            for r in stats_rows:
                model_type = r._mapping.get("model_type", "?")
                label = r._mapping.get("label")
                if model_type not in labels_by_model:
                    labels_by_model[model_type] = []
                if label:
                    labels_by_model[model_type].append(str(label))
            for _head in sorted(labels_by_model):
                pass
        else:
            pass

        # ── Sample an uncalibrated file with mood tags ──────────────
        result = session.execute(
            text(
                "SELECT lf.* FROM songs lf "
                "JOIN file_tags ft ON ft.file_id = lf.id "
                "JOIN tags t ON t.id = ft.tag_id "
                "WHERE lf.calibration_hash IS NULL "
                "AND t.name LIKE 'nom:mood-%' "
                "LIMIT 1",
            ),
        )
        row2 = result.fetchone()

        if row2:
            m2 = row2._mapping
            fid2: int = m2["id"]

            tag_result = session.execute(
                text(
                    "SELECT t.name, t.value "
                    "FROM file_tags ft "
                    "JOIN tags t ON t.id = ft.tag_id "
                    "WHERE ft.file_id = :fid AND t.name LIKE 'nom:mood-%'",
                ),
                {"fid": fid2},
            )
            mood_tags2 = [{"name": r[0], "value": r[1]} for r in tag_result.all()]

            for _t in sorted(mood_tags2, key=lambda x: x["name"]):
                pass
        else:
            pass

    finally:
        db.close()


if __name__ == "__main__":
    main()
