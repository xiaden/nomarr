"""Calibration state operations for ArangoDB.

calibration_state collection stores sparse uniform histogram-based calibration
results (p5/p95 percentiles) for each model head.
"""

import contextlib
from typing import Any, cast

from nomarr.persistence.arango_client import DatabaseLike


class CalibrationStateOperations:
    """Operations for the calibration_state collection (histogram-based calibration)."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("calibration_state")
        self._edge_collection = cast("Any", db.collection("model_has_calibration"))

    def get_sparse_histogram(
        self,
        model_id: str,
        label: str,
        lo: float = 0.0,
        hi: float = 1.0,
        bins: int = 10000,
    ) -> list[dict[str, Any]]:
        """Query sparse histogram for a single label using uniform binning.

        Per-label semantics: Each label is calibrated independently. For binary
        classification heads (e.g., gender with male/female labels), this method
        is called separately for each label, producing independent P5/P95 ranges.
        Sample count (n) represents file count, not prediction aggregation.

        Returns only bins with non-zero counts (sparse representation).
        Typical: 1,000-3,000 bins for real data (not full 10,000).

        Args:
            model_id: ArangoDB ``_id`` of the model vertex
                (e.g. ``"ml_models/abc1234567890123"``).
            label: Label to match (e.g., "male", "happy", "arousal")
            lo: Lower bound of calibrated range (default 0.0)
            hi: Upper bound of calibrated range (default 1.0)
            bins: Number of uniform bins (default 10000)

        Returns:
            List of {min_val: float, count: int, underflow_count: int, overflow_count: int}
            Sorted by min_val ascending.

        """
        bin_width = (hi - lo) / bins

        # Derive model_key_for_tag from model document
        # Tags use backbone+date without dashes (e.g. "musicnn20200331")
        # Model has backbone="musicnn", embedder_release_date="2020-03-31"
        query = """
            // Look up model to get backbone and release date
            LET model = DOCUMENT(@model_id)
            LET backbone = model.backbone
            LET release_date = SUBSTITUTE(model.embedder_release_date, "-", "")
            LET model_key_for_tag = CONCAT(backbone, release_date)

            FOR edge IN song_has_tags
              LET tag = DOCUMENT(edge._to)
              // Match individual head score tags containing model_key and label
              // Versioned tag format: nom:<label>_<framework>_<embedder><date>_<label><date>
              // Example: nom:not_aggressive_v1_musicnn20200331_not_aggressive20220825
              // model_key_for_tag in DB: <backbone><embedder_date> (e.g., "musicnn20200331")
              FILTER STARTS_WITH(tag.rel, "nom:")
              FILTER IS_NUMBER(tag.value)
              // Check if tag contains the model backbone/date pattern
              LET rel_without_prefix = SUBSTRING(tag.rel, 4)
              FILTER CONTAINS(rel_without_prefix, model_key_for_tag)
              // Extract label dynamically — works for any framework version string
              // (e.g. "_v1_" ONNX tags or legacy "_essentia..._" tags).
              // Tag format: {label}_{framework}_{backbone}{embedder_date}_{label}{head_date}
              // Step 1: find "_{embedder_part}" — everything before it is "{label}_{framework}"
              // Step 2: strip the last "_"-delimited segment (framework, e.g. "v1") to get the bare label
              // This handles multi-underscore labels (e.g. "not_aggressive") correctly.
              LET embedder_marker = CONCAT("_", model_key_for_tag)
              LET embedder_pos = FIND_FIRST(rel_without_prefix, embedder_marker)
              LET label_and_framework = embedder_pos > 0 ? SUBSTRING(rel_without_prefix, 0, embedder_pos) : rel_without_prefix
              LET framework_sep = FIND_LAST(label_and_framework, "_")
              LET extracted_label = framework_sep > 0 ? SUBSTRING(label_and_framework, 0, framework_sep) : label_and_framework
              // Check if extracted label matches the specified label
              FILTER extracted_label == @label

              LET value = tag.value

              // Compute integer bin index (avoid floating-point drift)
              LET bin_idx_raw = FLOOR((value - @lo) / @bin_width)
              LET bin_idx = MIN([MAX([bin_idx_raw, 0]), @max_bin])

              // Out-of-range flags
              LET is_underflow = value < @lo
              LET is_overflow = value > @hi

              // Group by integer bin index only (sparse: only bins with data)
              COLLECT bin_index = bin_idx
              AGGREGATE
                count = COUNT(1),
                underflow_count = SUM(is_underflow ? 1 : 0),
                overflow_count = SUM(is_overflow ? 1 : 0)

              // Derive min_val from integer bin index (stable floating-point)
              LET min_val = @lo + (bin_index * @bin_width)

              SORT min_val ASC

              RETURN {
                min_val: min_val,
                count: count,
                underflow_count: underflow_count,
                overflow_count: overflow_count
              }
        """

        cursor = self.db.aql.execute(
            query,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "model_id": model_id,
                    "label": label,
                    "lo": lo,
                    "hi": hi,
                    "bin_width": bin_width,
                    "max_bin": bins - 1,
                },
            ),
        )

        return list(cursor)  # type: ignore

    @staticmethod
    def _make_key(head_name: str, label: str) -> str:
        """Build an ArangoDB-safe _key from head_name and label.

        Model identity is now stored in the model_has_calibration edge,
        so the key only includes head_name and label.

        ArangoDB keys must not contain '/' or spaces.
        Replaces '/' with '_', spaces with '_', colons kept (allowed).
        """
        import re

        raw = f"{head_name}:{label}"
        return re.sub(r"[^a-zA-Z0-9_:.@()+,=;$!*'%-]", "_", raw)

    def upsert_calibration_state(
        self,
        model_id: str,
        head_name: str,
        label: str,
        calibration_def_hash: str,
        histogram_spec: dict[str, Any],
        p5: float,
        p95: float,
        sample_count: int,
        underflow_count: int,
        overflow_count: int,
        histogram_bins: list[dict[str, Any]] | None = None,
    ) -> None:
        """Upsert calibration_state document for a label.

        Per-label schema: Each label gets its own calibration document. Binary
        classification heads (e.g., gender) produce 2 documents with independent
        _key values (gender:male, gender:female). This enables independent
        P5/P95 ranges per label instead of aggregating complementary predictions
        (male=0.85, female=0.15) into single distribution.

        Model relationship is tracked via ``model_has_calibration`` edge, not
        stored on the document. Uses _key = sanitized "head_name:label" for
        stable identity. Overwrites existing document on upsert.

        Args:
            model_id: ArangoDB ``_id`` of the parent model vertex
                (e.g. ``"ml_models/abc1234567890123"``).
            head_name: Head name
            label: Label name (e.g., "male", "female", "arousal")
            calibration_def_hash: MD5 of (head_name, label) identity
            histogram_spec: {lo: float, hi: float, bins: int, bin_width: float}
            p5: 5th percentile (lower bound)
            p95: 95th percentile (upper bound)
            sample_count: Total number of values in histogram
            underflow_count: Count of values < lo
            overflow_count: Count of values > hi
            histogram_bins: Sparse histogram bins [{val: float, count: int}, ...]

        """
        _key = self._make_key(head_name, label)

        doc = {
            "_key": _key,
            "head_name": head_name,
            "label": label,
            "calibration_def_hash": calibration_def_hash,
            "histogram": histogram_spec,
            "histogram_bins": histogram_bins,
            "p5": p5,
            "p95": p95,
            "n": sample_count,
            "underflow_count": underflow_count,
            "overflow_count": overflow_count,
        }

        # UPSERT document
        if self.collection.has(_key):
            self.collection.update({"_key": _key, **doc})
        else:
            self.collection.insert(doc)

        # UPSERT edge: model -> calibration_state
        cs_id = f"calibration_state/{_key}"
        edge_key = _key  # Same key for idempotent edge
        edge_doc = {"_key": edge_key, "_from": model_id, "_to": cs_id}
        with contextlib.suppress(Exception):
            self._edge_collection.insert(edge_doc)  # Ignore if edge exists

    def get_calibration_state(self, head_name: str, label: str) -> dict[str, Any] | None:
        """Get calibration state for a specific label.

        Args:
            head_name: Head name
            label: Label name

        Returns:
            Calibration state document or None if not found

        """
        _key = self._make_key(head_name, label)
        try:
            return self.collection.get(_key)  # type: ignore
        except Exception:
            return None

    def get_all_calibration_states(self) -> list[dict[str, Any]]:
        """Get all calibration states with linked model info.

        Uses ``model_has_calibration`` edge traversal to join model metadata.

        Returns:
            List of calibration state documents with embedded model info.

        """
        cursor = self.db.aql.execute(
            """
            FOR cs IN calibration_state
                // Join model via INBOUND edge from model_has_calibration
                LET models = (
                    FOR model IN INBOUND cs model_has_calibration
                        RETURN {backbone: model.backbone, embedder_release_date: model.embedder_release_date}
                )
                LET model = LENGTH(models) > 0 ? FIRST(models) : null
                SORT cs.head_name ASC, cs.label ASC
                RETURN MERGE(cs, {model: model})
            """,
        )
        return list(cursor)  # type: ignore

    def delete_calibration_state(self, head_name: str, label: str) -> None:
        """Delete calibration state for a specific label.

        Also removes the ``model_has_calibration`` edge pointing to this document.

        Args:
            head_name: Head name
            label: Label name

        """
        _key = self._make_key(head_name, label)
        if self.collection.has(_key):
            # Delete edge(s) pointing to this calibration state
            cs_id = f"calibration_state/{_key}"
            self.db.aql.execute(
                """
                FOR e IN model_has_calibration
                    FILTER e._to == @cs_id
                    REMOVE e IN model_has_calibration
                """,
                bind_vars={"cs_id": cs_id},
            )
            # Delete the document
            self.collection.delete(_key)

    def truncate(self) -> None:
        """Remove all documents from the calibration_state collection."""
        self.collection.truncate()
