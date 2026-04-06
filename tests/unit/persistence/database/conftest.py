from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_SCHEMA_AWARE_MOCK_PATH = Path(__file__).with_name("schema_aware_mock.py")
_SCHEMA_AWARE_MOCK_SPEC = spec_from_file_location(
    "tests.unit.persistence.database.schema_aware_mock",
    _SCHEMA_AWARE_MOCK_PATH,
)
assert _SCHEMA_AWARE_MOCK_SPEC is not None and _SCHEMA_AWARE_MOCK_SPEC.loader is not None
_SCHEMA_AWARE_MOCK_MODULE = module_from_spec(_SCHEMA_AWARE_MOCK_SPEC)
_SCHEMA_AWARE_MOCK_SPEC.loader.exec_module(_SCHEMA_AWARE_MOCK_MODULE)

SchemaAwareMockDBCtor: type[Any] = _SCHEMA_AWARE_MOCK_MODULE.SchemaAwareMockDB


@pytest.fixture
def mock_db() -> MagicMock:
    """Provide mock ArangoDB database handle."""
    db = MagicMock()
    db.name = "test_db"
    return db


@pytest.fixture
def schema_mock_db() -> Any:
    """Provide schema-validating mock ArangoDB."""
    return SchemaAwareMockDBCtor()
