"""Calibration state operations for ArangoDB.

calibration_state collection stores sparse uniform histogram-based calibration
results (p5/p95 percentiles) for each model head.
"""

from typing import Any, cast

from nomarr.persistence.arango_client import DatabaseLike


class CalibrationStateOperations:
    """Operations for the calibration_state collection (histogram-based calibration)."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("calibration_state")

    def get_sparse_histogram(
        self,
        model_key: str,
        head_name: str,
        lo: float = 0.0,
        hi: float = 1.0,
        bins: int = 10000,
    ) -> list[dict[str, Any]]:
        """Query sparse histogram for a head using uniform binning.

        Returns only bins with non-zero counts (sparse representation).
        Typical: 1,000-3,000 bins for real data (not full 10,000).

        Args:
            model_key: Model identifier (e.g., "effnet-discogs-effnet-1")
            head_name: Head name (e.g., "mood_happy")
            lo: Lower bound of calibrated range (default 0.0)
            hi: Upper bound of calibrated range (default 1.0)
            bins: Number of uniform bins (default 10000)

        Returns:
            List of {min_val: float, count: int, underflow_count: int, overflow_count: int}
            Sorted by min_val ascending.

        """
        bin_width = (hi - lo) / bins

        # Convert model_key format from "backbone-date" to "backbonedate" to match tag format
        # Tags store "yamnet20220825" but calibration uses "yamnet-20220825"
        model_key_for_tag = model_key.replace("-", "")

        query = """
            FOR edge IN song_tag_edges
              LET tag = DOCUMENT(edge._to)
              // Match individual head score tags containing model_key and head_name
              // Versioned tag format: nom:<label>_<framework>_<embedder>_<head>
              // Example: nom:happy_essentia21b6dev1389_yamnet20220825_happy20220825
              // model_key format in DB: <backbone><embedder_date> (e.g., "yamnet20220825")
              // head_name: label (e.g., "happy")
              FILTER STARTS_WITH(tag.rel, "nom:")
              FILTER IS_NUMBER(tag.value)
              // Check if tag contains both the model backbone/date and head label
              // The tag rel should contain model_key parts and start with head_name
              LET rel_without_prefix = SUBSTRING(tag.rel, 4)
              // Extract label (first segment before first underscore)
              LET first_underscore = POSITION(rel_without_prefix, "_")
              LET label = first_underscore > 0 ? SUBSTRING(rel_without_prefix, 0, first_underscore) : rel_without_prefix
              // Check if tag matches this head by label and contains model_key pattern
              FILTER label == @head_name
              FILTER CONTAINS(rel_without_prefix, @model_key_for_tag)

              LET lo = @lo
              LET hi = @hi
              LET bin_width = @bin_width
              LET value = tag.value

              // Compute integer bin index (avoid floating-point drift)
              LET bin_idx_raw = FLOOR((value - lo) / bin_width)
              LET bin_idx = MIN(MAX(bin_idx_raw, 0), @max_bin)

              // Out-of-range flags
              LET is_underflow = value < lo
              LET is_overflow = value > hi

              // Group by integer bin index only (sparse: only bins with data)
              COLLECT bin_index = bin_idx
              AGGREGATE
                count = COUNT(1),
                underflow_count = SUM(is_underflow ? 1 : 0),
                overflow_count = SUM(is_overflow ? 1 : 0)

              // Derive min_val from integer bin index (stable floating-point)
              LET min_val = lo + (bin_index * bin_width)

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
                    "model_key_for_tag": model_key_for_tag,
                    "head_name": head_name,
                    "lo": lo,
                    "hi": hi,
                    "bin_width": bin_width,
                    "max_bin": bins - 1,
                },
            ),
        )

        return list(cursor)  # type: ignore

    def get_sparse_histogram_with_limit(
        self,
        model_key: str,
        head_name: str,
        lo: float = 0.0,
        hi: float = 1.0,
        bins: int = 10000,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query sparse histogram with sample limiting for progressive calibration.

        Args:
            model_key: Model identifier
            head_name: Head name
            lo: Lower bound of calibrated range
            hi: Upper bound of calibrated range
            bins: Number of uniform bins
            limit: Maximum number of samples to use (None = unlimited)

        Returns:
            List of {min_val: float, count: int, underflow_count: int, overflow_count: int}

        """
        if limit is None:
            # No limit - use standard method
            return self.get_sparse_histogram(
                model_key=model_key,
                head_name=head_name,
                lo=lo,
                hi=hi,
                bins=bins,
            )

        bin_width = (hi - lo) / bins
        model_key_for_tag = model_key.replace("-", "")

        query = """
            FOR edge IN song_tag_edges
              LIMIT @limit
              LET tag = DOCUMENT(edge._to)
              FILTER STARTS_WITH(tag.rel, "nom:")
              FILTER IS_NUMBER(tag.value)
              LET rel_without_prefix = SUBSTRING(tag.rel, 4)
              LET first_underscore = POSITION(rel_without_prefix, "_")
              LET label = first_underscore > 0 ? SUBSTRING(rel_without_prefix, 0, first_underscore) : rel_without_prefix
              FILTER label == @head_name
              FILTER CONTAINS(rel_without_prefix, @model_key_for_tag)

              LET lo = @lo
              LET hi = @hi
              LET bin_width = @bin_width
              LET value = tag.value

              LET bin_idx_raw = FLOOR((value - lo) / bin_width)
              LET bin_idx = MIN(MAX(bin_idx_raw, 0), @max_bin)

              LET is_underflow = value < lo
              LET is_overflow = value > hi

              COLLECT bin_index = bin_idx
              AGGREGATE
                count = COUNT(1),
                underflow_count = SUM(is_underflow ? 1 : 0),
                overflow_count = SUM(is_overflow ? 1 : 0)

              LET min_val = lo + (bin_index * bin_width)

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
                    "model_key_for_tag": model_key_for_tag,
                    "head_name": head_name,
                    "lo": lo,
                    "hi": hi,
                    "bin_width": bin_width,
                    "max_bin": bins - 1,
                    "limit": limit,
                },
            ),
        )

        return list(cursor)  # type: ignore

    def upsert_calibration_state(
        self,
        model_key: str,
        head_name: str,
        calibration_def_hash: str,
        version: int,
        histogram_spec: dict[str, Any],
        p5: float,
        p95: float,
        sample_count: int,
        underflow_count: int,
        overflow_count: int,
    ) -> None:
        """Upsert calibration_state document for a head.

        Uses _key = "model_key:head_name" for stable identity.
        Overwrites existing document on version bump.

        Args:
            model_key: Model identifier
            head_name: Head name
            calibration_def_hash: MD5 of (model_key, head_name, version)
            version: Calibration version from head metadata
            histogram_spec: {lo: float, hi: float, bins: int, bin_width: float}
            p5: 5th percentile (lower bound)
            p95: 95th percentile (upper bound)
            n: Total number of values in histogram
            underflow_count: Count of values < lo
            overflow_count: Count of values > hi

        """
        now_ms = int(__import__("time").time() * 1000)
        _key = f"{model_key}:{head_name}"

        doc = {
            "_key": _key,
            "model_key": model_key,
            "head_name": head_name,
            "calibration_def_hash": calibration_def_hash,
            "version": version,
            "histogram": histogram_spec,
            "p5": p5,
            "p95": p95,
            "n": sample_count,
            "underflow_count": underflow_count,
            "overflow_count": overflow_count,
            "updated_at": now_ms,
            "last_computation_at": now_ms,
        }

        # Check if document exists
        if self.collection.has(_key):
            # Update existing document (preserve created_at)
            existing = self.collection.get(_key)
            doc["created_at"] = existing["created_at"]  # type: ignore
            self.collection.update({"_key": _key, **doc})
        else:
            # Insert new document
            doc["created_at"] = now_ms
            self.collection.insert(doc)

    def get_calibration_state(self, model_key: str, head_name: str) -> dict[str, Any] | None:
        """Get calibration state for a specific head.

        Args:
            model_key: Model identifier
            head_name: Head name

        Returns:
            Calibration state document or None if not found

        """
        _key = f"{model_key}:{head_name}"
        try:
            return self.collection.get(_key)  # type: ignore
        except Exception:
            return None

    def get_all_calibration_states(self) -> list[dict[str, Any]]:
        """Get all calibration states.

        Returns:
            List of calibration state documents

        """
        cursor = self.db.aql.execute(
            """
            FOR c IN calibration_state
                SORT c.updated_at DESC
                RETURN c
            """,
        )
        return list(cursor)  # type: ignore

    def delete_calibration_state(self, model_key: str, head_name: str) -> None:
        """Delete calibration state for a specific head.

        Args:
            model_key: Model identifier
            head_name: Head name

        """
        _key = f"{model_key}:{head_name}"
        if self.collection.has(_key):
            self.collection.delete(_key)
