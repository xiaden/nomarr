"""Diagnose whether apply_calibration_wf actually updated the DB."""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text

sys.path.insert(0, "/app")
from nomarr.persistence.db import Database

DB_URL = os.environ.get(
    "NOMARR_DB_URL",
    "postgresql+asyncpg://nomarr:nomarr@localhost:5432/nomarr",
)


async def main() -> None:
    db = Database(url=DB_URL)

    try:
        # ── Count files with calibration_hash ──────────────────────
        total = await db.library.count_files()

        session_factory = db._pg_session  # type: ignore[union-attr]
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM library_files WHERE calibration_hash IS NOT NULL"),
            )
            calibrated = result.scalar() or 0

        print(f"Total files:            {total}")
        print(f"With calibration_hash:  {calibrated}")

        # ── Check calibration version ──────────────────────────────
        ver_doc = await db.app.get_config_option("calibration_version")
        last_run_doc = await db.app.get_config_option("calibration_last_run")
        ver = None if ver_doc is None else ver_doc.get("value")
        last_run = None if last_run_doc is None else last_run_doc.get("value")
        print(f"calibration_version:    {ver}")
        print(f"calibration_last_run:   {last_run}")

        # ── Print calibration_state summary ─────────────────────────
        states = await db.ml.list_calibration_states()
        print(f"\ncalibration_state entries: {len(states)}")
        for s in sorted(states, key=lambda x: x["state_data"].get("label", "")):
            sd = s["state_data"]
            print(
                f"  {sd.get('label', '?'):<25} "
                f"p5={sd.get('p5', 0):.4f}  "
                f"p95={sd.get('p95', 0):.4f}  "
                f"n={sd.get('n', 0)}",
            )

        # ── Sample a calibrated file ────────────────────────────────
        print("\n--- Sample calibrated file ---")
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM library_files WHERE calibration_hash IS NOT NULL LIMIT 1"),
            )
            row = result.fetchone()

        if row:
            m = row._mapping
            fid: int = m["id"]
            print(f"path: {m.get('path', '?')}")
            print(f"calibration_hash: {m.get('calibration_hash', '?')}")

            # Mood tags via file_tags → tags JOIN
            async with session_factory() as session:
                tag_result = await session.execute(
                    text(
                        "SELECT t.name, t.value "
                        "FROM file_tags ft "
                        "JOIN tags t ON t.id = ft.tag_id "
                        "WHERE ft.file_id = :fid AND t.name LIKE 'nom:mood-%'",
                    ),
                    {"fid": fid},
                )
                mood_tags = [{"name": r[0], "value": r[1]} for r in tag_result.all()]

            print(f"Mood tags ({len(mood_tags)}):")
            for t in sorted(mood_tags, key=lambda x: x["name"]):
                print(f"  {t['name']}: {t['value']}")

            # Check segment_scores_stats equivalent (ml_model_outputs)
            async with session_factory() as session:
                stats_result = await session.execute(
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

            print(f"\nsegment_scores_stats heads ({len(stats_rows)}):")
            labels_by_model: dict[str, list[str]] = {}
            for r in stats_rows:
                model_type = r._mapping.get("model_type", "?")
                label = r._mapping.get("label")
                if model_type not in labels_by_model:
                    labels_by_model[model_type] = []
                if label:
                    labels_by_model[model_type].append(str(label))
            for head in sorted(labels_by_model):
                print(f"  {head}: {labels_by_model[head]}")
        else:
            print("No calibrated files found!")

        # ── Sample an uncalibrated file with mood tags ──────────────
        print("\n--- Sample UN-calibrated file ---")
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT lf.* FROM library_files lf "
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
            print(f"path: {m2.get('path', '?')}")

            async with session_factory() as session:
                tag_result = await session.execute(
                    text(
                        "SELECT t.name, t.value "
                        "FROM file_tags ft "
                        "JOIN tags t ON t.id = ft.tag_id "
                        "WHERE ft.file_id = :fid AND t.name LIKE 'nom:mood-%'",
                    ),
                    {"fid": fid2},
                )
                mood_tags2 = [{"name": r[0], "value": r[1]} for r in tag_result.all()]

            print(f"Mood tags ({len(mood_tags2)}):")
            for t in sorted(mood_tags2, key=lambda x: x["name"]):
                print(f"  {t['name']}: {t['value']}")
        else:
            print("All files have calibration_hash (or no untagged files found)")

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
