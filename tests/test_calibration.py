"""
Test calibration module - percentile calibration generation and sidecar saving.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from nomarr.persistence.db import Database
from nomarr.ml.calibration import (
    generate_minmax_calibration,
    save_calibration_sidecars,
)


@pytest.fixture
def temp_db():
    """Create temporary database with test data."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".db") as f:
        db_path = f.name

    db = Database(db_path)

    # Add 1000+ test library files with versioned tags to meet calibration minimum
    # Tags stored WITHOUT namespace prefix in nom_tags column
    import random

    random.seed(42)  # Reproducible test data

    for i in range(1100):
        db.upsert_library_file(
            path=f"/music/song{i}.mp3",
            file_size=1024,
            modified_time=1234567890,
            nom_tags=json.dumps(
                {
                    "happy_essentia21b6dev1389_yamnet20210604_happy20220825_none_0": random.random(),
                    "sad_essentia21b6dev1389_yamnet20210604_sad20220825_none_0": random.random(),
                }
            ),
        )

    yield db

    # Cleanup
    db.close()
    os.unlink(db_path)


@pytest.fixture
def temp_models_dir():
    """Create temporary models directory with test model sidecars."""
    with tempfile.TemporaryDirectory() as tmpdir:
        models_dir = Path(tmpdir)

        # Create YAMNet head directory structure
        yamnet_heads = models_dir / "yamnet" / "heads" / "softmax"
        yamnet_heads.mkdir(parents=True)

        # Create test head sidecars
        happy_head = {
            "name": "mood_happy-audioset-yamnet-1",
            "description": "Happy mood classifier",
            "release_date": "2022-08-25",
            "labels": ["happy"],
            "type": "binary_classification",
            "embedding": "../embeddings/audioset-yamnet-1.pb",
        }

        sad_head = {
            "name": "mood_sad-audioset-yamnet-1",
            "description": "Sad mood classifier",
            "release_date": "2022-08-25",
            "labels": ["sad"],
            "type": "binary_classification",
            "embedding": "../embeddings/audioset-yamnet-1.pb",
        }

        with open(yamnet_heads / "mood_happy-audioset-yamnet-1.json", "w") as f:
            json.dump(happy_head, f)

        with open(yamnet_heads / "mood_sad-audioset-yamnet-1.json", "w") as f:
            json.dump(sad_head, f)

        # Create dummy .pb files (discovery needs them to exist)
        (yamnet_heads / "mood_happy-audioset-yamnet-1.pb").touch()
        (yamnet_heads / "mood_sad-audioset-yamnet-1.pb").touch()

        # Create YAMNet embedding sidecar
        yamnet_embed = models_dir / "yamnet" / "embeddings"
        yamnet_embed.mkdir(parents=True)

        embedding_info = {
            "name": "audioset-yamnet-1",
            "release_date": "2021-06-04",
            "backbone": "yamnet",
        }

        with open(yamnet_embed / "audioset-yamnet-1.json", "w") as f:
            json.dump(embedding_info, f)

        # Create dummy embedding .pb file
        (yamnet_embed / "audioset-yamnet-1.pb").touch()

        yield str(models_dir)


def test_generate_minmax_calibration(temp_db):
    """Test min-max calibration generation with 1000+ samples."""
    calibration_data = generate_minmax_calibration(
        db=temp_db,
        namespace="",  # Empty namespace - tags stored without prefix
    )

    # Check structure
    assert calibration_data["method"] == "minmax"
    assert calibration_data["library_size"] == 1100
    assert calibration_data["min_samples"] == 1000

    # Should have calibrations for both tags (1100 samples each)
    calibrations = calibration_data["calibrations"]
    assert len(calibrations) == 2

    # Check happy tag calibration
    happy_key = "happy_essentia21b6dev1389_yamnet20210604_happy20220825_none_0"
    assert happy_key in calibrations

    happy_calib = calibrations[happy_key]
    assert happy_calib["method"] == "minmax"
    assert happy_calib["samples"] == 1100
    assert "mean" in happy_calib
    assert "std" in happy_calib
    assert "p5" in happy_calib  # 5th percentile
    assert "p95" in happy_calib  # 95th percentile

    # p95 should be greater than p5
    assert happy_calib["p95"] > happy_calib["p5"]


def test_save_calibration_sidecars(temp_db, temp_models_dir):
    """Test saving calibration sidecars next to model files."""
    # Generate calibration data
    calibration_data = generate_minmax_calibration(db=temp_db, namespace="")

    # Save sidecars
    save_result = save_calibration_sidecars(calibration_data=calibration_data, models_dir=temp_models_dir, version=1)

    # Check save result
    assert save_result["total_files"] == 2  # happy and sad heads
    assert save_result["total_labels"] == 2

    # Verify files exist
    saved_files = save_result["saved_files"]
    assert len(saved_files) == 2

    # Check happy calibration file
    happy_calib_path = None
    for path in saved_files:
        if "happy" in path:
            happy_calib_path = path
            break

    assert happy_calib_path is not None
    assert os.path.exists(happy_calib_path)

    # Verify file content
    with open(happy_calib_path) as f:
        sidecar = json.load(f)

    assert sidecar["calibration_version"] == 1
    assert sidecar["calibration_method"] == "minmax"
    assert sidecar["library_size"] == 1100
    assert sidecar["min_samples"] == 1000
    assert sidecar["model"] == "mood_happy-audioset-yamnet-1"
    assert sidecar["head_type"] == "softmax"  # From directory structure
    assert sidecar["backbone"] == "yamnet"

    # Should have happy label calibration
    assert "happy" in sidecar["labels"]
    happy_data = sidecar["labels"]["happy"]
    assert happy_data["method"] == "minmax"
    assert happy_data["samples"] == 1100
    assert "p5" in happy_data
    assert "p95" in happy_data
    assert happy_data["p95"] > happy_data["p5"]


def test_calibration_min_samples_filter():
    """Test that tags with insufficient samples are skipped (hard-coded 1000 minimum)."""
    # Create a database with only a few samples (< 1000)
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".db") as f:
        db_path = f.name

    db = Database(db_path)

    # Add only 3 files (well below 1000 minimum)
    for i in range(3):
        db.upsert_library_file(
            path=f"/music/song{i}.mp3",
            file_size=1024,
            modified_time=1234567890,
            nom_tags=json.dumps(
                {
                    "happy_essentia21b6dev1389_yamnet20210604_happy20220825_none_0": 0.5,
                    "sad_essentia21b6dev1389_yamnet20210604_sad20220825_none_0": 0.5,
                }
            ),
        )

    calibration_data = generate_minmax_calibration(
        db=db,
        namespace="",
    )

    # Should skip both tags (only 3 test samples < 1000 minimum)
    assert len(calibration_data["calibrations"]) == 0
    assert calibration_data["skipped_tags"] == 2

    db.close()
    os.unlink(db_path)


def test_calibration_empty_library():
    """Test calibration with empty library."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".db") as f:
        db_path = f.name

    db = Database(db_path)

    calibration_data = generate_minmax_calibration(db=db, namespace="")

    assert calibration_data["library_size"] == 0
    assert len(calibration_data["calibrations"]) == 0
    assert calibration_data["skipped_tags"] == 0

    db.close()
    os.unlink(db_path)
