"""Tests for lint_project_backend and lint_project_frontend MCP tools.

Covers:
- Backend: parse_raw_errors for ruff, mypy, import-linter
- Backend: normalize_to_json_structure
- Backend: _is_valid_mypy_json
- Frontend: parse_eslint_output, parse_typescript_output
- Frontend: lint_project_frontend missing frontend dir

NOTE: Integration tests that shell out to ruff/mypy are skipped if binaries
are unavailable. Pure parsing/normalization functions are tested directly.
"""

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcp_code_intel.tools.lint_project_backend import (
    _is_valid_mypy_json,
    normalize_to_json_structure,
    parse_raw_errors,
)
from mcp_code_intel.tools.lint_project_frontend import (
    parse_eslint_output,
    parse_typescript_output,
)


def _make_proc_bytes(
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int = 0,
) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


def _make_proc_text(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


def _prepare_backend_project_root(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    (project_root / "tests").mkdir(parents=True)
    (project_root / ".venv" / "Scripts").mkdir(parents=True)
    (project_root / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    return project_root


# ===================================================================
# Backend — parse_raw_errors
# ===================================================================


class TestParseRuffErrors:
    def test_valid_ruff_json(self) -> None:
        ruff_output = json.dumps(
            [
                {
                    "code": "F401",
                    "message": "os imported but unused",
                    "filename": "nomarr/main.py",
                    "location": {"row": 1, "column": 1},
                    "fix": {"edits": []},
                },
                {
                    "code": "E501",
                    "message": "Line too long",
                    "filename": "nomarr/main.py",
                    "location": {"row": 10, "column": 80},
                    "fix": None,
                },
            ]
        )
        errors = parse_raw_errors(ruff_output, "", "ruff")
        assert len(errors) == 2
        assert errors[0]["code"] == "F401"
        assert errors[0]["fix_available"] is True
        assert errors[1]["fix_available"] is False
        assert errors[0]["file"] == "nomarr/main.py"
        assert errors[0]["line"] == 1

    def test_empty_ruff_output(self) -> None:
        errors = parse_raw_errors("", "", "ruff")
        assert errors == []

    def test_invalid_ruff_json(self) -> None:
        errors = parse_raw_errors("not json", "", "ruff")
        assert errors == []

    def test_ruff_no_errors_empty_array(self) -> None:
        errors = parse_raw_errors("[]", "", "ruff")
        assert errors == []


class TestParseMypyErrors:
    def test_valid_mypy_json_lines(self) -> None:
        lines = "\n".join(
            [
                json.dumps(
                    {
                        "severity": "error",
                        "code": "arg-type",
                        "message": "Argument 1 has incompatible type",
                        "file": "nomarr/wf.py",
                        "line": 15,
                    }
                ),
                json.dumps(
                    {
                        "severity": "note",
                        "code": "note",
                        "message": "See docs",
                        "file": "nomarr/wf.py",
                        "line": 16,
                    }
                ),
            ]
        )
        errors = parse_raw_errors(lines, "", "mypy")
        # Notes are skipped
        assert len(errors) == 1
        assert errors[0]["code"] == "arg-type"
        assert errors[0]["file"] == "nomarr/wf.py"

    def test_empty_mypy_output(self) -> None:
        errors = parse_raw_errors("", "", "mypy")
        assert errors == []

    def test_mypy_non_json_lines_skipped(self) -> None:
        errors = parse_raw_errors("Success: no issues found\n", "", "mypy")
        assert errors == []


class TestParseImportLinterErrors:
    def test_broken_contract(self) -> None:
        output = "nomarr.helpers.time imports nomarr.services.scan (broken contract)\n"
        errors = parse_raw_errors(output, "", "import-linter")
        assert len(errors) == 1
        assert errors[0]["code"] == "architecture"
        assert "nomarr.helpers.time imports nomarr.services.scan" in errors[0]["description"]

    def test_clean_output(self) -> None:
        errors = parse_raw_errors("All contracts satisfied.\n", "", "import-linter")
        assert errors == []


# ===================================================================
# Backend — normalize_to_json_structure
# ===================================================================


class TestNormalizeToJsonStructure:
    def test_groups_by_code(self) -> None:
        errors = [
            {
                "code": "F401",
                "description": "unused import",
                "fix_available": True,
                "file": "a.py",
                "line": 1,
            },
            {
                "code": "F401",
                "description": "unused import",
                "fix_available": True,
                "file": "b.py",
                "line": 5,
            },
            {
                "code": "E501",
                "description": "line too long",
                "fix_available": False,
                "file": "a.py",
                "line": 10,
            },
        ]
        result = normalize_to_json_structure(errors, "ruff")
        assert "F401" in result
        assert len(result["F401"]["occurrences"]) == 2
        assert result["F401"]["fix_available"] is True
        assert "E501" in result
        assert len(result["E501"]["occurrences"]) == 1

    def test_import_linter_no_file_line(self) -> None:
        errors = [
            {
                "code": "architecture",
                "description": "violation",
                "fix_available": False,
                "file": None,
                "line": None,
            },
        ]
        result = normalize_to_json_structure(errors, "import-linter")
        assert "architecture" in result
        assert result["architecture"]["occurrences"][0]["file"] is None

    def test_empty_errors(self) -> None:
        result = normalize_to_json_structure([], "ruff")
        assert result == {}


# ===================================================================
# Backend — _is_valid_mypy_json
# ===================================================================


class TestIsValidMypyJson:
    def test_empty_is_valid(self) -> None:
        assert _is_valid_mypy_json("") is True

    def test_valid_json_lines(self) -> None:
        lines = json.dumps({"severity": "error", "message": "bad"}) + "\n"
        assert _is_valid_mypy_json(lines) is True

    def test_plain_text_is_invalid(self) -> None:
        assert _is_valid_mypy_json("Success: no issues found") is False

    def test_non_dict_json_is_invalid(self) -> None:
        assert _is_valid_mypy_json('["list"]') is False


# ===================================================================
# Frontend — parse_eslint_output
# ===================================================================


class TestParseEslintOutput:
    def test_standard_eslint_output(self) -> None:
        stdout = textwrap.dedent("""\
            /home/user/project/frontend/src/App.tsx
              12:5  error  Unexpected console statement  no-console
              20:10  warning  Unused variable  no-unused-vars
        """)
        errors = parse_eslint_output(stdout, "")
        assert len(errors) == 2
        assert errors[0]["line"] == 12
        assert errors[0]["column"] == 5
        assert errors[0]["code"] == "no-console"
        assert errors[0]["severity"] == "error"
        assert errors[1]["severity"] == "warning"

    def test_empty_output(self) -> None:
        errors = parse_eslint_output("", "")
        assert errors == []

    def test_no_errors_output(self) -> None:
        errors = parse_eslint_output("All files passed linting.\n", "")
        assert errors == []


# ===================================================================
# Frontend — parse_typescript_output
# ===================================================================


class TestParseTypescriptOutput:
    def test_standard_ts_error(self) -> None:
        stdout = (
            "src/App.tsx(15,3): error TS2322: Type 'string' is not assignable to type 'number'.\n"
        )
        errors = parse_typescript_output(stdout, "")
        assert len(errors) == 1
        assert errors[0]["line"] == 15
        assert errors[0]["column"] == 3
        assert errors[0]["code"] == "TS2322"
        assert "not assignable" in errors[0]["message"]

    def test_empty_output(self) -> None:
        errors = parse_typescript_output("", "")
        assert errors == []

    def test_multiple_errors(self) -> None:
        stdout = textwrap.dedent("""\
            src/A.tsx(1,1): error TS1001: msg1
            src/B.tsx(2,2): warning TS1002: msg2
        """)
        errors = parse_typescript_output(stdout, "")
        assert len(errors) == 2
        assert errors[0]["code"] == "TS1001"
        assert errors[1]["severity"] == "warning"


# ===================================================================
# Frontend — lint_project_frontend: missing frontend dir
# ===================================================================


def test_lint_frontend_missing_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """When frontend dir doesn't exist, returns error status."""
    from pathlib import Path as _Path

    import mcp_code_intel.tools.lint_project_frontend as mod

    # Point frontend_dir to a non-existent path
    monkeypatch.setattr(mod, "frontend_dir", _Path("/nonexistent/frontend"))

    from mcp_code_intel.tools.lint_project_frontend import lint_project_frontend

    result = lint_project_frontend()
    assert result["status"] == "error"
    assert "not found" in result["summary"]["error"]


# ===================================================================
# Backend — lint_project_backend: ruff format parsing
# ===================================================================


class TestRuffFormatParsing:
    def test_ruff_format_violation_produces_ruff_format_key(self) -> None:
        from mcp_code_intel.tools.lint_project_backend import lint_project_backend

        with patch(
            "mcp_code_intel.tools.lint_project_backend.subprocess.run",
            side_effect=[
                _make_proc_bytes(stdout=b"[]", stderr=b"", returncode=0),
                _make_proc_bytes(
                    stdout=b"Would reformat: /abs/path/file.py\n",
                    stderr=b"",
                    returncode=1,
                ),
                _make_proc_bytes(stdout=b"", stderr=b"", returncode=0),
            ],
        ):
            result = lint_project_backend(path=".", check_all=False)

        assert "ruff-format" in result
        assert "/abs/path/file.py" in result["ruff-format"]
        assert result["ruff-format"]["/abs/path/file.py"]["fix_available"] is True
        assert result["ruff-format"]["/abs/path/file.py"]["occurrences"][0]["line"] is None

    def test_ruff_format_clean_omits_ruff_format_key(self) -> None:
        from mcp_code_intel.tools.lint_project_backend import lint_project_backend

        with patch(
            "mcp_code_intel.tools.lint_project_backend.subprocess.run",
            side_effect=[
                _make_proc_bytes(stdout=b"[]", stderr=b"", returncode=0),
                _make_proc_bytes(stdout=b"", stderr=b"", returncode=0),
                _make_proc_bytes(stdout=b"", stderr=b"", returncode=0),
            ],
        ):
            result = lint_project_backend(path=".", check_all=False)

        assert "ruff-format" not in result

    def test_ruff_format_multiple_files(self) -> None:
        from mcp_code_intel.tools.lint_project_backend import lint_project_backend

        with patch(
            "mcp_code_intel.tools.lint_project_backend.subprocess.run",
            side_effect=[
                _make_proc_bytes(stdout=b"[]", stderr=b"", returncode=0),
                _make_proc_bytes(
                    stdout=(
                        b"Would reformat: /abs/path/one.py\nWould reformat: /abs/path/two.py\n"
                    ),
                    stderr=b"",
                    returncode=1,
                ),
                _make_proc_bytes(stdout=b"", stderr=b"", returncode=0),
            ],
        ):
            result = lint_project_backend(path=".", check_all=False)

        assert "ruff-format" in result
        assert "/abs/path/one.py" in result["ruff-format"]
        assert "/abs/path/two.py" in result["ruff-format"]


# ===================================================================
# Backend — lint_project_backend: pytest summary
# ===================================================================


class TestPytestSummary:
    def test_pytest_passing_sets_pass_status(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import mcp_code_intel.tools.lint_project_backend as mod
        from mcp_code_intel.tools.lint_project_backend import lint_project_backend

        monkeypatch.setattr(mod, "project_root", _prepare_backend_project_root(tmp_path))

        with patch(
            "mcp_code_intel.tools.lint_project_backend.subprocess.run",
            side_effect=[
                _make_proc_bytes(stdout=b"[]", stderr=b"", returncode=0),
                _make_proc_bytes(stdout=b"", stderr=b"", returncode=0),
                _make_proc_bytes(stdout=b"", stderr=b"", returncode=0),
                _make_proc_bytes(
                    stdout=b"All contracts satisfied.\n",
                    stderr=b"",
                    returncode=0,
                ),
                _make_proc_bytes(stdout=b"5 passed in 0.5s\n", stderr=b"", returncode=0),
            ],
        ):
            result = lint_project_backend(path=".", check_all=True)

        assert result["pytest"]["status"] == "pass"
        assert result["pytest"]["passed"] == 5

    def test_pytest_failure_sets_fail_status(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import mcp_code_intel.tools.lint_project_backend as mod
        from mcp_code_intel.tools.lint_project_backend import lint_project_backend

        monkeypatch.setattr(mod, "project_root", _prepare_backend_project_root(tmp_path))

        with patch(
            "mcp_code_intel.tools.lint_project_backend.subprocess.run",
            side_effect=[
                _make_proc_bytes(stdout=b"[]", stderr=b"", returncode=0),
                _make_proc_bytes(stdout=b"", stderr=b"", returncode=0),
                _make_proc_bytes(stdout=b"", stderr=b"", returncode=0),
                _make_proc_bytes(
                    stdout=b"All contracts satisfied.\n",
                    stderr=b"",
                    returncode=0,
                ),
                _make_proc_bytes(
                    stdout=b"3 passed, 2 failed in 1.0s\n",
                    stderr=b"",
                    returncode=1,
                ),
            ],
        ):
            result = lint_project_backend(path=".", check_all=True)

        assert result["pytest"]["status"] == "fail"
        assert result["pytest"]["failed"] == 2
        assert "output" in result["pytest"]

    def test_pytest_omitted_when_check_all_false(self) -> None:
        from mcp_code_intel.tools.lint_project_backend import lint_project_backend

        with patch(
            "mcp_code_intel.tools.lint_project_backend.subprocess.run",
            side_effect=[
                _make_proc_bytes(stdout=b"[]", stderr=b"", returncode=0),
                _make_proc_bytes(stdout=b"", stderr=b"", returncode=0),
                _make_proc_bytes(stdout=b"", stderr=b"", returncode=0),
            ],
        ):
            result = lint_project_backend(path=".", check_all=False)

        assert "pytest" not in result

    def test_pytest_error_on_subprocess_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import mcp_code_intel.tools.lint_project_backend as mod
        from mcp_code_intel.tools.lint_project_backend import lint_project_backend

        monkeypatch.setattr(mod, "project_root", _prepare_backend_project_root(tmp_path))

        with patch(
            "mcp_code_intel.tools.lint_project_backend.subprocess.run",
            side_effect=[
                _make_proc_bytes(stdout=b"[]", stderr=b"", returncode=0),
                _make_proc_bytes(stdout=b"", stderr=b"", returncode=0),
                _make_proc_bytes(stdout=b"", stderr=b"", returncode=0),
                _make_proc_bytes(
                    stdout=b"All contracts satisfied.\n",
                    stderr=b"",
                    returncode=0,
                ),
                Exception("pytest crashed"),
            ],
        ):
            result = lint_project_backend(path=".", check_all=True)

        assert result["pytest"]["status"] == "error"
        assert result["pytest"]["error"] == "pytest crashed"


# ===================================================================
# Frontend — lint_project_frontend: vitest step
# ===================================================================


class TestVitestStep:
    def test_vitest_pass_produces_clean_status(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import mcp_code_intel.tools.lint_project_frontend as mod
        from mcp_code_intel.tools.lint_project_frontend import lint_project_frontend

        monkeypatch.setattr(mod, "frontend_dir", Path("d:/Github/nomarr/frontend"))

        with patch(
            "mcp_code_intel.tools.lint_project_frontend.subprocess.run",
            side_effect=[
                _make_proc_text(stdout="", stderr="", returncode=0),
                _make_proc_text(stdout="", stderr="", returncode=0),
                _make_proc_text(stdout="", stderr="", returncode=0),
            ],
        ):
            result = lint_project_frontend()

        assert result["status"] == "clean"
        assert all(error.get("tool") != "vitest" for error in result.get("errors", []))

    def test_vitest_failure_adds_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import mcp_code_intel.tools.lint_project_frontend as mod
        from mcp_code_intel.tools.lint_project_frontend import lint_project_frontend

        monkeypatch.setattr(mod, "frontend_dir", Path("d:/Github/nomarr/frontend"))

        with patch(
            "mcp_code_intel.tools.lint_project_frontend.subprocess.run",
            side_effect=[
                _make_proc_text(stdout="", stderr="", returncode=0),
                _make_proc_text(stdout="", stderr="", returncode=0),
                _make_proc_text(stdout="FAIL 2 tests\n", stderr="", returncode=1),
            ],
        ):
            result = lint_project_frontend()

        assert result["status"] == "errors"
        assert any(
            error["tool"] == "vitest" and error["code"] == "test-failure"
            for error in result["errors"]
        )

    def test_vitest_exception_adds_tool_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import mcp_code_intel.tools.lint_project_frontend as mod
        from mcp_code_intel.tools.lint_project_frontend import lint_project_frontend

        monkeypatch.setattr(mod, "frontend_dir", Path("d:/Github/nomarr/frontend"))

        with patch(
            "mcp_code_intel.tools.lint_project_frontend.subprocess.run",
            side_effect=[
                _make_proc_text(stdout="", stderr="", returncode=0),
                _make_proc_text(stdout="", stderr="", returncode=0),
                RuntimeError("npm not found"),
            ],
        ):
            result = lint_project_frontend()

        assert result["status"] == "errors"
        assert any(
            error["tool"] == "vitest" and error["code"] == "tool-error"
            for error in result["errors"]
        )
