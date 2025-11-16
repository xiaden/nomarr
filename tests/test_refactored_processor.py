"""
Test refactored processor with new signature.

Verifies:
1. ProcessorConfig dataclass works
2. process_file accepts typed config + optional DB
3. File validation helpers work
4. Skip logic works
"""

import os
import tempfile

import pytest


@pytest.fixture
def mock_config():
    """Create a ProcessorConfig for testing."""
    from nomarr.helpers.dataclasses import ProcessorConfig

    return ProcessorConfig(
        models_dir="/fake/models",
        min_duration_s=5,
        allow_short=False,
        batch_size=16,
        overwrite_tags=False,
        namespace="essentia",
        version_tag_key="essentia:tagger-version",
        tagger_version="2.0.0",
        calibrate_heads=False,
    )


def test_processor_config_creation():
    """Test ProcessorConfig dataclass can be created."""
    from nomarr.helpers.dataclasses import ProcessorConfig

    config = ProcessorConfig(
        models_dir="/fake/models",
        min_duration_s=5,
        allow_short=False,
        batch_size=16,
        overwrite_tags=False,
        namespace="essentia",
        version_tag_key="essentia:tagger-version",
        tagger_version="2.0.0",
        calibrate_heads=False,
    )

    assert config.models_dir == "/fake/models"
    assert config.min_duration_s == 5
    assert config.allow_short is False
    assert config.batch_size == 16
    assert config.overwrite_tags is False
    assert config.namespace == "essentia"
    assert config.version_tag_key == "essentia:tagger-version"
    assert config.tagger_version == "2.0.0"
    assert config.calibrate_heads is False


def test_config_service_make_processor_config():
    """Test ConfigService can create ProcessorConfig."""
    from nomarr.services.config import ConfigService

    service = ConfigService()
    config = service.make_processor_config()

    # Check it returns ProcessorConfig type
    from nomarr.helpers.dataclasses import ProcessorConfig

    assert isinstance(config, ProcessorConfig)

    # Check required fields exist
    assert hasattr(config, "models_dir")
    assert hasattr(config, "min_duration_s")
    assert hasattr(config, "namespace")


def test_validate_file_exists_with_valid_file():
    """Test file validation succeeds for existing file."""
    from nomarr.services.file_validation import validate_file_exists

    # Create temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
        temp_path = f.name

    try:
        # Should not raise
        validate_file_exists(temp_path)
    finally:
        os.unlink(temp_path)


def test_validate_file_exists_with_missing_file():
    """Test file validation raises for missing file."""
    from nomarr.services.file_validation import validate_file_exists

    with pytest.raises(RuntimeError, match="File not found"):
        validate_file_exists("/fake/nonexistent/file.mp3")


def test_should_skip_processing_returns_tuple():
    """Test skip logic returns (should_skip, reason) tuple."""
    from nomarr.services.file_validation import should_skip_processing

    # Create temp file without tags
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
        temp_path = f.name

    try:
        should_skip, reason = should_skip_processing(
            temp_path,
            force=False,
            namespace="essentia",
            version_tag_key="essentia:tagger-version",
            tagger_version="2.0.0",
        )

        # Should be bool and str (or None)
        assert isinstance(should_skip, bool)
        assert reason is None or isinstance(reason, str)
    finally:
        os.unlink(temp_path)


def test_make_skip_result_format():
    """Test skip result matches process_file output format."""
    from nomarr.services.file_validation import make_skip_result

    result = make_skip_result("/test/path.mp3", "already_tagged")

    # Should match process_file result format
    assert "file" in result
    assert "skipped" in result
    assert "skip_reason" in result
    assert result["file"] == "/test/path.mp3"
    assert result["skipped"] is True
    assert result["skip_reason"] == "already_tagged"


def test_process_file_signature_accepts_config_and_db(mock_config):
    """Test process_file_workflow accepts new signature (config + optional db)."""
    import inspect

    from nomarr.workflows.process_file import process_file_workflow

    # Check signature
    sig = inspect.signature(process_file_workflow)
    params = list(sig.parameters.keys())

    # New signature should have: path, config, db
    assert "path" in params
    assert "config" in params
    assert "db" in params

    # Old signature params should NOT be present
    assert "force" not in params
    assert "progress_callback" not in params
    assert "db_path" not in params

    # Verify parameter annotations exist
    assert sig.parameters["config"].annotation is not None
    assert sig.parameters["db"].annotation is not None


def test_process_file_no_longer_accepts_old_signature():
    """Test process_file_workflow rejects old signature (path, force)."""
    from nomarr.workflows.process_file import process_file_workflow

    # Create temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
        temp_path = f.name

    try:
        # Old signature should fail (no force parameter)
        with pytest.raises(TypeError):
            process_file_workflow(temp_path, force=False)  # type: ignore
    finally:
        os.unlink(temp_path)
