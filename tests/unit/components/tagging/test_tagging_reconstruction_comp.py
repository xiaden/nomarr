"""Unit tests for canonical stream-based tagging reconstruction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from nomarr.components.tagging.tagging_reconstruction_comp import reconstruct_head_outputs_from_streams
from nomarr.helpers.dto.ml_dto import HeadOutput, LoadedOutputStream


@dataclass
class _FakeHeadInfo:
    name: str
    labels: list[str]
    head_type: str
    is_regression_head: bool = False

    def build_versioned_tag_key(
        self,
        label: str,
        calib_method: str = "none",
        calib_version: int = 0,
    ) -> tuple[str, str]:
        return (f"model:{self.name}:{label}:{calib_method}:{calib_version}", f"{calib_method}_{calib_version}")


@pytest.mark.unit
@pytest.mark.mocked
class TestReconstructHeadOutputsFromStreams:
    """Tests for canonical raw-stream reconstruction."""

    @patch("nomarr.components.tagging.tagging_reconstruction_comp.decide_binary_multiclass")
    def test_classification_recomputes_probs_and_std_in_output_index_order(
        self,
        mock_decide_binary_multiclass: MagicMock,
    ) -> None:
        head_info = _FakeHeadInfo(
            name="mood_multiclass",
            labels=["happy", "sad"],
            head_type="multiclass",
        )
        streams = [
            LoadedOutputStream(
                head_name="mood_multiclass",
                output_id="ml_model_outputs/out-sad",
                output_index=1,
                label="sad",
                values=[0.1, 0.3],
            ),
            LoadedOutputStream(
                head_name="mood_multiclass",
                output_id="ml_model_outputs/out-happy",
                output_index=0,
                label="happy",
                values=[0.8, 0.8],
            ),
        ]
        mock_decide_binary_multiclass.return_value = {
            "selected": {"sad": {"p": 0.4, "tier": "medium"}},
            "all_probs": {"happy": 0.8, "sad": 0.4},
        }

        result = reconstruct_head_outputs_from_streams(
            output_streams=streams,
            head_infos=[head_info],
            calibrations={"sad": {"p5": 0.0, "p95": 0.5, "calibration_def_hash": "sad-hash"}},
        )

        probs = mock_decide_binary_multiclass.call_args.args[0]
        segment_std = mock_decide_binary_multiclass.call_args.kwargs["segment_std"]
        assert np.allclose(probs, np.array([0.8, 0.4], dtype=np.float32))
        assert np.allclose(segment_std, np.array([0.0, 0.2], dtype=np.float32))

        assert [(output.label, output.value, output.tier, output.calibration_id) for output in result] == [
            ("sad", 0.4, "medium", "minmax_sad-hash"),
            ("happy", 0.8, None, None),
        ]

    @patch("nomarr.components.tagging.tagging_reconstruction_comp.assign_regression_outputs")
    def test_regression_applies_calibration_before_tier_assignment(
        self,
        mock_assign_regression_outputs: MagicMock,
    ) -> None:
        head_info = _FakeHeadInfo(
            name="approachability_regression",
            labels=["approachability"],
            head_type="regression",
            is_regression_head=True,
        )
        mock_assign_regression_outputs.return_value = [
            HeadOutput(
                head=cast("Any", head_info),
                model_key="model:approachability_regression:approachable:none:0",
                label="approachable",
                value=0.5,
                tier="high",
                calibration_id="minmax_reg-hash",
            )
        ]

        result = reconstruct_head_outputs_from_streams(
            output_streams=[
                LoadedOutputStream(
                    head_name="approachability_regression",
                    output_id="ml_model_outputs/out-1",
                    output_index=0,
                    label="approachability",
                    values=[0.2, 0.4, 0.6],
                )
            ],
            head_infos=[head_info],
            calibrations={"approachability": {"p5": 0.2, "p95": 0.6, "calibration_def_hash": "reg-hash"}},
        )

        assert result == mock_assign_regression_outputs.return_value
        assert mock_assign_regression_outputs.call_args.args[:4] == (
            head_info,
            "approachability_regression",
            pytest.approx(0.5),
            pytest.approx(float(np.std(np.asarray([0.2, 0.4, 0.6], dtype=np.float32))) * 2.5),
        )
        assert mock_assign_regression_outputs.call_args.kwargs["applied_calibration_id"] == "minmax_reg-hash"
        assert mock_assign_regression_outputs.call_args.kwargs["log_prefix"] == "reconstruction"

    def test_returns_empty_when_no_streams_exist_for_discovered_heads(self) -> None:
        head_info = _FakeHeadInfo(
            name="mood_multiclass",
            labels=["happy", "sad"],
            head_type="multiclass",
        )

        result = reconstruct_head_outputs_from_streams(output_streams=[], head_infos=[head_info])

        assert result == []
