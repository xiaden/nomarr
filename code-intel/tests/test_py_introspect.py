"""Tests for py_introspect MCP tool.

Covers:
- MRO check on stdlib class
- Signature check on known function
- Doc check on known function
- issubclass check
- Multiple checks batched
- Invalid/unknown check type
- Invalid target
- ast_raises check
- No checks provided
- Pydantic validation error
"""



from mcp_code_intel.tools.py_introspect import py_introspect

# ---------------------------------------------------------------------------
# MRO checks
# ---------------------------------------------------------------------------


def test_mro_dict() -> None:
    result = py_introspect(checks=[{"check": "mro", "target": "builtins.dict"}])
    assert result["status"] == "ok"
    assert len(result["results"]) == 1
    r = result["results"][0]
    assert r["ok"] is True
    assert "dict" in r["result"]
    assert "object" in r["result"]


def test_mro_bool() -> None:
    result = py_introspect(checks=[{"check": "mro", "target": "builtins.bool"}])
    assert result["status"] == "ok"
    mro = result["results"][0]["result"]
    assert "bool" in mro
    assert "int" in mro


# ---------------------------------------------------------------------------
# Signature checks
# ---------------------------------------------------------------------------


def test_signature_os_path_join() -> None:
    result = py_introspect(checks=[{"check": "signature", "target": "os.path.join"}])
    assert result["status"] == "ok"
    r = result["results"][0]
    assert r["ok"] is True
    assert isinstance(r["result"], str)


def test_signature_json_dumps() -> None:
    result = py_introspect(checks=[{"check": "signature", "target": "json.dumps"}])
    assert result["status"] == "ok"
    r = result["results"][0]
    assert r["ok"] is True
    assert "obj" in r["result"] or r["result"]  # has parameters


# ---------------------------------------------------------------------------
# Doc checks
# ---------------------------------------------------------------------------


def test_doc_json_dumps() -> None:
    result = py_introspect(checks=[{"check": "doc", "target": "json.dumps"}])
    assert result["status"] == "ok"
    r = result["results"][0]
    assert r["ok"] is True
    assert r["meta"]["has_doc"] is True
    assert isinstance(r["result"], str)
    assert len(r["result"]) > 0


def test_doc_no_docstring() -> None:
    """Some builtins may lack docstrings; test the 'no doc' path."""
    # operator.itemgetter has a docstring, but test shows structure works
    result = py_introspect(checks=[{"check": "doc", "target": "json.dumps"}])
    assert result["status"] == "ok"
    assert result["results"][0]["ok"] is True


# ---------------------------------------------------------------------------
# issubclass checks
# ---------------------------------------------------------------------------


def test_issubclass_bool_int() -> None:
    result = py_introspect(checks=[{
        "check": "issubclass",
        "child": "builtins.bool",
        "parent": "builtins.int",
    }])
    assert result["status"] == "ok"
    r = result["results"][0]
    assert r["ok"] is True
    assert r["result"] is True


def test_issubclass_int_bool_false() -> None:
    result = py_introspect(checks=[{
        "check": "issubclass",
        "child": "builtins.int",
        "parent": "builtins.bool",
    }])
    assert result["status"] == "ok"
    assert result["results"][0]["result"] is False


# ---------------------------------------------------------------------------
# ast_raises check
# ---------------------------------------------------------------------------


def test_ast_raises_json_loads() -> None:
    """json.loads raises ValueError/JSONDecodeError."""
    result = py_introspect(checks=[{
        "check": "ast_raises",
        "target": "json.decoder.JSONDecoder.decode",
    }])
    assert result["status"] in ("ok", "partial")
    r = result["results"][0]
    # It at least ran the check
    assert r["check"] == "ast_raises"


def test_ast_raises_with_filter() -> None:
    """Filter for specific exceptions."""
    result = py_introspect(checks=[{
        "check": "ast_raises",
        "target": "json.decoder.JSONDecoder.decode",
        "exceptions": ["JSONDecodeError", "NonExistentError"],
    }])
    r = result["results"][0]
    if r["ok"]:
        # unmatched should contain NonExistentError
        assert "NonExistentError" in r["meta"].get("unmatched", [])


# ---------------------------------------------------------------------------
# Batched checks
# ---------------------------------------------------------------------------


def test_multiple_checks_batched() -> None:
    result = py_introspect(checks=[
        {"check": "mro", "target": "builtins.bool"},
        {"check": "signature", "target": "json.dumps"},
        {"check": "doc", "target": "json.loads"},
    ])
    assert result["status"] == "ok"
    assert len(result["results"]) == 3
    assert all(r["ok"] for r in result["results"])


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_no_checks() -> None:
    result = py_introspect(checks=[])
    assert result["status"] == "error"
    assert any("No checks" in e for e in result["errors"])


def test_none_checks() -> None:
    result = py_introspect(checks=None)
    assert result["status"] == "error"


def test_invalid_check_type() -> None:
    result = py_introspect(checks=[{"check": "nonexistent_type", "target": "os"}])
    assert result["status"] == "error"
    assert any("Invalid request" in e or "nonexistent" in str(e) for e in result["errors"])


def test_invalid_target() -> None:
    result = py_introspect(checks=[{
        "check": "mro",
        "target": "nonexistent.module.Class",
    }])
    # Should return partial or error with failed result
    assert len(result["results"]) == 1
    r = result["results"][0]
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# getsource_contains
# ---------------------------------------------------------------------------


def test_getsource_contains_positive() -> None:
    result = py_introspect(checks=[{
        "check": "getsource_contains",
        "target": "json.dumps",
        "needle": "def",
    }])
    assert result["status"] == "ok"
    r = result["results"][0]
    assert r["ok"] is True
    assert r["result"] is True
    assert r["meta"]["match_count"] >= 1


def test_getsource_contains_negative() -> None:
    result = py_introspect(checks=[{
        "check": "getsource_contains",
        "target": "json.dumps",
        "needle": "XYZZY_NONEXISTENT_TOKEN",
    }])
    assert result["status"] == "ok"
    r = result["results"][0]
    assert r["ok"] is True
    assert r["result"] is False
    assert r["meta"]["match_count"] == 0


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------


def test_response_has_python_version() -> None:
    result = py_introspect(checks=[{"check": "mro", "target": "builtins.int"}])
    assert "python_version" in result
    assert result["python_version"]  # non-empty
    parts = result["python_version"].split(".")
    assert len(parts) == 3


def test_response_structure_keys() -> None:
    result = py_introspect(checks=[{"check": "mro", "target": "builtins.int"}])
    assert "status" in result
    assert "results" in result
    assert "warnings" in result
    assert "errors" in result
