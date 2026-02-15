"""Integration tests for content-based edit tools."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mcp_code_intel.tools.edit_file_insert_text import (
    edit_file_insert_text,
)
from mcp_code_intel.tools.edit_file_move_by_content import (
    edit_file_move_by_content,
)
from mcp_code_intel.tools.edit_file_replace_by_content import (
    edit_file_replace_by_content,
)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Return a temp workspace root."""
    return tmp_path


def _write(workspace: Path, name: str, content: str) -> str:
    """Write a file and return its workspace-relative path."""
    p = workspace / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return name


def _read(workspace: Path, name: str) -> str:
    return (workspace / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# edit_file_replace_by_content
# ---------------------------------------------------------------------------


class TestReplaceByContent:
    def test_replace_typescript_function(self, workspace: Path) -> None:
        path = _write(
            workspace,
            "widget.tsx",
            """\
            import React from 'react';

            const Widget = () => {
                const [count, setCount] = React.useState(0);
                const handleClick = () => {
                    setCount(count + 1);
                    console.log('clicked');
                    // lots of legacy code
                    // that we want to remove
                };
                return <button onClick={handleClick}>{count}</button>;
            };

            export default Widget;
            """,
        )

        result = edit_file_replace_by_content(
            file_path=path,
            start_boundary="const handleClick = () => {",
            end_boundary="};",
            expected_line_count=6,
            new_content=(
                "    const handleClick = () => setCount(c => c + 1);\n"
            ),
            workspace_root=workspace,
        )
        assert result["status"] == "applied"

        content = _read(workspace, path)
        assert "setCount(c => c + 1)" in content
        assert "console.log" not in content
        assert "lots of legacy code" not in content

    def test_replace_yaml_section(self, workspace: Path) -> None:
        path = _write(
            workspace,
            "config.yaml",
            """\
            server:
              host: localhost
              port: 8080

            database:
              host: db.example.com
              port: 5432
              name: mydb
              pool_size: 10

            logging:
              level: DEBUG
            """,
        )

        result = edit_file_replace_by_content(
            file_path=path,
            start_boundary="database:",
            end_boundary="pool_size: 10",
            expected_line_count=5,
            new_content="database:\n  url: postgresql://db/mydb\n",
            workspace_root=workspace,
        )
        assert result["status"] == "applied"

        content = _read(workspace, path)
        assert "url: postgresql://db/mydb" in content
        assert "pool_size" not in content
        assert "host: db.example.com" not in content

    def test_ambiguous_fails(self, workspace: Path) -> None:
        path = _write(
            workspace,
            "dup.txt",
            """\
            START
            body1
            END
            START
            body2
            END
            """,
        )

        result = edit_file_replace_by_content(
            file_path=path,
            start_boundary="START",
            end_boundary="END",
            expected_line_count=3,
            new_content="REPLACED\n",
            workspace_root=workspace,
        )
        assert result["status"] == "failed"
        assert "Ambiguous" in result["failed_ops"][0]["reason"]


# ---------------------------------------------------------------------------
# edit_file_move_by_content (same file)
# ---------------------------------------------------------------------------


class TestMoveByContent:
    def test_same_file_move(self, workspace: Path) -> None:
        path = _write(
            workspace,
            "module.py",
            """\
            def helper():
                return 42

            def main():
                x = helper()
                return x

            def utility():
                pass
            """,
        )

        result = edit_file_move_by_content(
            file_path=path,
            start_boundary="def helper():",
            end_boundary="return 42",
            expected_line_count=2,
            target_anchor="def utility():",
            target_position="after",
            workspace_root=workspace,
        )
        assert result.get("changed") is True

        content = _read(workspace, path)
        lines = content.strip().splitlines()
        # helper should now be after utility
        utility_idx = next(
            i for i, ln in enumerate(lines) if "def utility" in ln
        )
        helper_idx = next(
            i for i, ln in enumerate(lines) if "def helper" in ln
        )
        assert helper_idx > utility_idx

    def test_cross_file_move(self, workspace: Path) -> None:
        src = _write(
            workspace,
            "source.py",
            """\
            import os

            def move_me():
                return "moved"

            def stay():
                pass
            """,
        )
        tgt = _write(
            workspace,
            "target.py",
            """\
            # Target file

            def existing():
                pass
            """,
        )

        result = edit_file_move_by_content(
            file_path=src,
            start_boundary="def move_me():",
            end_boundary='return "moved"',
            expected_line_count=2,
            target_anchor="def existing():",
            target_position="before",
            workspace_root=workspace,
            target_file=tgt,
        )
        assert result.get("changed") is True

        src_content = _read(workspace, src)
        tgt_content = _read(workspace, tgt)
        assert "move_me" not in src_content
        assert "move_me" in tgt_content
        assert "existing" in tgt_content

    def test_move_to_new_file(self, workspace: Path) -> None:
        """Extract a symbol into a brand-new file (no anchor)."""
        src = _write(
            workspace,
            "big_module.py",
            """\
            class Keep:
                pass

            class ExtractMe:
                def method(self):
                    return "extracted"

            class AlsoKeep:
                pass
            """,
        )

        result = edit_file_move_by_content(
            file_path=src,
            start_boundary="class ExtractMe:",
            end_boundary='return "extracted"',
            expected_line_count=3,
            target_anchor=None,
            target_position="after",  # ignored but required param
            workspace_root=workspace,
            target_file="extracted.py",
        )
        assert result.get("changed") is True
        assert result.get("created_new_file") is True

        src_content = _read(workspace, src)
        assert "ExtractMe" not in src_content
        assert "Keep" in src_content
        assert "AlsoKeep" in src_content

        tgt_content = _read(workspace, "extracted.py")
        assert "class ExtractMe:" in tgt_content
        assert 'return "extracted"' in tgt_content

    def test_move_to_new_file_fails_if_exists(
        self, workspace: Path,
    ) -> None:
        """Fail when target_anchor is None but target file exists."""
        src = _write(
            workspace,
            "source.py",
            """\
            def func():
                pass
            """,
        )
        _write(workspace, "already.py", "# existing\n")

        result = edit_file_move_by_content(
            file_path=src,
            start_boundary="def func():",
            end_boundary="pass",
            expected_line_count=2,
            target_anchor=None,
            target_position="after",
            workspace_root=workspace,
            target_file="already.py",
        )
        assert result.get("changed") is False
        assert "already exists" in result.get("error", "")

    def test_no_anchor_same_file_fails(self, workspace: Path) -> None:
        """Fail when target_anchor is None for a same-file move."""
        src = _write(
            workspace,
            "module.py",
            """\
            def a():
                pass
            def b():
                pass
            """,
        )

        result = edit_file_move_by_content(
            file_path=src,
            start_boundary="def a():",
            end_boundary="pass",
            expected_line_count=2,
            target_anchor=None,
            target_position="after",
            workspace_root=workspace,
        )
        assert result.get("changed") is False
        assert "required" in result.get("error", "").lower()


# ---------------------------------------------------------------------------
# edit_file_insert_at_line (anchor mode)
# ---------------------------------------------------------------------------


class TestInsertAtAnchor:
    def test_insert_after_anchor(self, workspace: Path) -> None:
        path = _write(
            workspace,
            "config.yaml",
            """\
            server:
              host: localhost
              port: 8080
            logging:
              level: INFO
            """,
        )

        result = edit_file_insert_text(
            [
                {
                    "path": path,
                    "content": "  timeout: 30",
                    "at": "after_line",
                    "anchor": "port: 8080",
                },
            ],
            workspace_root=workspace,
        )
        assert result["status"] == "applied"

        content = _read(workspace, path)
        assert "timeout: 30" in content
        lines = content.splitlines()
        port_idx = next(i for i, ln in enumerate(lines) if "port: 8080" in ln)
        timeout_idx = next(
            i for i, ln in enumerate(lines) if "timeout: 30" in ln
        )
        assert timeout_idx == port_idx + 1

    def test_insert_before_anchor(self, workspace: Path) -> None:
        path = _write(
            workspace,
            "app.ts",
            """\
            import { Component } from '@angular/core';

            @Component({})
            export class AppComponent {}
            """,
        )

        result = edit_file_insert_text(
            [
                {
                    "path": path,
                    "content": "import { Injectable } from '@angular/core';",
                    "at": "before_line",
                    "anchor": "@Component({})",
                },
            ],
            workspace_root=workspace,
        )
        assert result["status"] == "applied"

        content = _read(workspace, path)
        assert "Injectable" in content

    def test_ambiguous_anchor_fails(self, workspace: Path) -> None:
        path = _write(
            workspace,
            "dup.txt",
            """\
            pass
            something
            pass
            """,
        )

        result = edit_file_insert_text(
            [
                {
                    "path": path,
                    "content": "# inserted",
                    "at": "after_line",
                    "anchor": "pass",
                },
            ],
            workspace_root=workspace,
        )
        assert result["status"] == "failed"
        assert "Ambiguous" in result["failed_ops"][0]["reason"]
