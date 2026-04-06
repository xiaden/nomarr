"""Tests for ADR tools — adr_suggest, adr_commit, adr_read, adr_search.

Covers:
- adr_suggest: happy path, writes draft to staging dir, validation errors, parseable markdown
- adr_commit: happy path, auto-numbering, writes to disk, validation (defense in depth),
  collision retry, source_log, extra sections, references, commit-from-draft-id, draft cleanup
- adr_read: by number/filename/prefix, not found, path traversal, empty name
- adr_search: no filters, by tag, by status, by query, combined, limit, empty dir, sort order
"""

import builtins
from pathlib import Path
from typing import Any
from unittest.mock import patch

from mcp_code_intel.helpers.adr_md import parse_adr
from mcp_code_intel.tools.adr_commit import adr_commit
from mcp_code_intel.tools.adr_read import adr_read
from mcp_code_intel.tools.adr_search import adr_search
from mcp_code_intel.tools.adr_suggest import adr_suggest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULTS = dict(
    title="Use Edges",
    status="Proposed",
    tags=["persistence"],
    context=(
        "We need a way to represent relationships between documents in ArangoDB. "
        "Currently all data is stored in document collections with no explicit "
        "connections. This makes traversal queries impossible and forces the "
        "application layer to perform manual joins across collections."
    ),
    decision=(
        "Use ArangoDB edge collections to model relationships between documents. "
        "Edge collections provide native graph traversal capabilities and allow "
        "efficient shortest-path and neighbor queries. Each edge stores a _from "
        "and _to reference linking source and target documents."
    ),
    consequences=(
        "Graph traversal queries become first-class operations supported by the "
        "database engine. Query performance improves significantly for relationship "
        "lookups compared to application-level joins. However, edge collections "
        "add storage overhead and require careful index management to maintain "
        "write performance under load."
    ),
)


def _suggest_sample_adr(tmp_path: Path, **kwargs: object) -> dict:  # type: ignore[type-arg]
    defaults = {**_DEFAULTS, "workspace_root": tmp_path}
    defaults.update(kwargs)
    return adr_suggest(**defaults)  # type: ignore[arg-type, no-any-return]


def _commit_sample_adr(tmp_path: Path, **kwargs: object) -> dict:  # type: ignore[type-arg]
    defaults = {**_DEFAULTS, "workspace_root": tmp_path}
    defaults.update(kwargs)
    return adr_commit(**defaults)  # type: ignore[arg-type, no-any-return]


# ---------------------------------------------------------------------------
# adr_suggest
# ---------------------------------------------------------------------------


def test_adr_suggest_happy_path(tmp_path: Path) -> None:
    result = _suggest_sample_adr(tmp_path)
    assert "markdown" in result
    assert result["title"] == "Use Edges"
    assert "draft_id" in result
    assert "word_count" in result
    assert "number" not in result
    assert "filename" not in result


def test_adr_suggest_writes_draft_to_disk(tmp_path: Path) -> None:
    result = _suggest_sample_adr(tmp_path)
    assert "error" not in result
    assert "draft_path" in result
    draft_file = tmp_path / result["draft_path"]
    assert draft_file.exists(), f"Expected draft at {draft_file}"
    assert "ADR-DRAFT" in draft_file.read_text(encoding="utf-8")


def test_adr_suggest_draft_not_in_decisions_dir(tmp_path: Path) -> None:
    result = _suggest_sample_adr(tmp_path)
    assert "error" not in result
    decisions_dir = tmp_path / "artifacts" / "decisions"
    committed = (
        [p for p in decisions_dir.iterdir() if p.is_file() and p.suffix == ".md"]
        if decisions_dir.exists()
        else []
    )
    assert committed == [], "adr_suggest should not write to the committed ADR directory"


def test_adr_suggest_returns_parseable_markdown(tmp_path: Path) -> None:
    result = _suggest_sample_adr(tmp_path)
    adr = parse_adr(result["markdown"])
    assert adr.title == "Use Edges"
    assert adr.status == "Proposed"
    assert adr.tags == ["persistence"]
    assert "ADR-DRAFT" in result["markdown"]


def test_adr_suggest_invalid_status(tmp_path: Path) -> None:
    result = _suggest_sample_adr(tmp_path, status="Invalid")
    assert result["error"] == "invalid_status"


def test_adr_suggest_empty_title(tmp_path: Path) -> None:
    result = _suggest_sample_adr(tmp_path, title="")
    assert result["error"] == "invalid_title"


def test_adr_suggest_no_tags(tmp_path: Path) -> None:
    result = _suggest_sample_adr(tmp_path, tags=[])
    assert result["error"] == "invalid_tags"


def test_adr_suggest_empty_context(tmp_path: Path) -> None:
    result = _suggest_sample_adr(tmp_path, context="")
    assert result["error"] == "invalid_section"


def test_adr_suggest_empty_decision(tmp_path: Path) -> None:
    result = _suggest_sample_adr(tmp_path, decision="")
    assert result["error"] == "invalid_section"


def test_adr_suggest_empty_consequences(tmp_path: Path) -> None:
    result = _suggest_sample_adr(tmp_path, consequences="")
    assert result["error"] == "invalid_section"


def test_adr_suggest_invalid_source_log(tmp_path: Path) -> None:
    result = _suggest_sample_adr(tmp_path, source_log="bad-format")
    assert result["error"] == "invalid_source_log"


def test_adr_suggest_valid_source_log(tmp_path: Path) -> None:
    result = _suggest_sample_adr(tmp_path, source_log="rnd-test#L10")
    assert "markdown" in result
    adr = parse_adr(result["markdown"])
    assert adr.source_log == "rnd-test#L10"


def test_adr_suggest_extra_sections(tmp_path: Path) -> None:
    result = _suggest_sample_adr(
        tmp_path,
        extra_sections=[{"heading": "Migration", "content": "Migration notes."}],
    )
    assert "markdown" in result
    assert "## Migration" in result["markdown"]


def test_adr_suggest_with_references(tmp_path: Path) -> None:
    result = _suggest_sample_adr(tmp_path, references="- [Link](url)")
    assert "markdown" in result
    assert "## References" in result["markdown"]


# ---------------------------------------------------------------------------
# adr_commit
# ---------------------------------------------------------------------------


def test_adr_commit_happy_path(tmp_path: Path) -> None:
    result = _commit_sample_adr(tmp_path)
    assert "path" in result
    assert result["number"] == 1
    assert result["title"] == "Use Edges"
    assert "markdown" in result
    assert "content_warning" not in result
    created = tmp_path / result["path"]
    assert created.exists()


def test_adr_commit_file_is_parseable(tmp_path: Path) -> None:
    result = _commit_sample_adr(tmp_path)
    md = (tmp_path / result["path"]).read_text(encoding="utf-8")
    adr = parse_adr(md)
    assert adr.title == "Use Edges"
    assert adr.status == "Proposed"
    assert adr.tags == ["persistence"]


def test_adr_commit_auto_numbering(tmp_path: Path) -> None:
    _commit_sample_adr(tmp_path, title="First")
    result = _commit_sample_adr(tmp_path, title="Second")
    assert result["number"] == 2


def test_adr_commit_validates_inputs(tmp_path: Path) -> None:
    """Defense-in-depth: adr_commit also validates (same as adr_suggest)."""
    result = _commit_sample_adr(tmp_path, status="Invalid")
    assert result["error"] == "invalid_status"


def test_adr_commit_valid_source_log(tmp_path: Path) -> None:
    result = _commit_sample_adr(tmp_path, source_log="rnd-test#L10")
    assert "path" in result
    md = (tmp_path / result["path"]).read_text(encoding="utf-8")
    adr = parse_adr(md)
    assert adr.source_log == "rnd-test#L10"


def test_adr_commit_extra_sections(tmp_path: Path) -> None:
    result = _commit_sample_adr(
        tmp_path,
        extra_sections=[{"heading": "Migration", "content": "Migration notes."}],
    )
    assert "path" in result
    md = (tmp_path / result["path"]).read_text(encoding="utf-8")
    assert "## Migration" in md


def test_adr_commit_with_references(tmp_path: Path) -> None:
    result = _commit_sample_adr(tmp_path, references="- [Link](url)")
    assert "path" in result
    md = (tmp_path / result["path"]).read_text(encoding="utf-8")
    assert "## References" in md


def test_adr_commit_collision_retry(tmp_path: Path) -> None:
    """When open('x') raises FileExistsError, adr_commit retries with the next number."""
    call_count = 0
    original_open = builtins.open

    def _open_that_fails_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        # Only intercept exclusive-create calls to ADR files
        if len(args) >= 2 and args[1] == "x":
            call_count += 1
            if call_count == 1:
                raise FileExistsError(str(args[0]))
        return original_open(*args, **kwargs)

    with patch("builtins.open", _open_that_fails_once):
        result = _commit_sample_adr(tmp_path, title="Collider")

    assert "path" in result
    assert call_count == 2  # First attempt failed, second succeeded


def test_adr_commit_from_draft_id(tmp_path: Path) -> None:
    """adr_commit loads content from the staging draft when draft_id is given."""
    suggest_result = _suggest_sample_adr(tmp_path)
    assert "error" not in suggest_result
    draft_id = suggest_result["draft_id"]

    result = adr_commit(draft_id=draft_id, workspace_root=tmp_path)
    assert "error" not in result, result
    assert result["number"] == 1
    assert result["title"] == "Use Edges"
    committed = tmp_path / result["path"]
    assert committed.exists()


def test_adr_commit_draft_deleted_after_commit(tmp_path: Path) -> None:
    """The staging draft is removed once adr_commit succeeds."""
    suggest_result = _suggest_sample_adr(tmp_path)
    draft_id = suggest_result["draft_id"]
    draft_file = tmp_path / suggest_result["draft_path"]
    assert draft_file.exists()

    adr_commit(draft_id=draft_id, workspace_root=tmp_path)
    assert not draft_file.exists(), "Draft should be deleted after successful commit"


def test_adr_commit_draft_id_not_found(tmp_path: Path) -> None:
    """adr_commit returns draft_not_found when the staging file is missing."""
    result = adr_commit(draft_id="nonexistent-slug", workspace_root=tmp_path)
    assert result["error"] == "draft_not_found"


# ---------------------------------------------------------------------------
# adr_read
# ---------------------------------------------------------------------------


def test_adr_read_by_number(tmp_path: Path) -> None:
    _commit_sample_adr(tmp_path)
    result = adr_read(name="1", workspace_root=tmp_path)
    assert result["title"] == "Use Edges"
    assert result["number"] == 1


def test_adr_read_by_padded_number(tmp_path: Path) -> None:
    _commit_sample_adr(tmp_path)
    result = adr_read(name="001", workspace_root=tmp_path)
    assert result["title"] == "Use Edges"


def test_adr_read_by_filename(tmp_path: Path) -> None:
    committed = _commit_sample_adr(tmp_path)
    filename = committed["path"].split("/")[-1]
    result = adr_read(name=filename, workspace_root=tmp_path)
    assert result["title"] == "Use Edges"


def test_adr_read_not_found(tmp_path: Path) -> None:
    result = adr_read(name="999", workspace_root=tmp_path)
    assert result["error"] == "adr_not_found"


def test_adr_read_empty_name(tmp_path: Path) -> None:
    result = adr_read(name="", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


def test_adr_read_path_traversal_rejected(tmp_path: Path) -> None:
    result = adr_read(name="../../../etc/passwd", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


def test_adr_read_backslash_rejected(tmp_path: Path) -> None:
    result = adr_read(name="..\\etc\\passwd", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


# ---------------------------------------------------------------------------
# adr_search
# ---------------------------------------------------------------------------


def _setup_search_fixtures(tmp_path: Path) -> None:
    """Create 3 ADRs for search testing."""
    _commit_sample_adr(
        tmp_path,
        title="Use Edges",
        tags=["persistence", "arangodb"],
        status="Proposed",
    )
    _commit_sample_adr(
        tmp_path,
        title="Adopt ONNX",
        tags=["ml", "inference"],
        status="Accepted",
    )
    _commit_sample_adr(
        tmp_path,
        title="REST API Design",
        tags=["api", "persistence"],
        status="Proposed",
    )


def test_adr_search_no_filters(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(workspace_root=tmp_path)
    assert result["total"] == 3
    assert len(result["results"]) == 3


def test_adr_search_by_tag(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(tag="persistence", workspace_root=tmp_path)
    assert result["total"] == 2


def test_adr_search_by_status(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(status="Accepted", workspace_root=tmp_path)
    assert result["total"] == 1
    assert result["results"][0]["title"] == "Adopt ONNX"


def test_adr_search_by_query(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(query="ONNX", workspace_root=tmp_path)
    assert result["total"] == 1


def test_adr_search_combined_filters(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(tag="persistence", status="Proposed", workspace_root=tmp_path)
    assert result["total"] == 2


def test_adr_search_limit(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(limit=1, workspace_root=tmp_path)
    assert len(result["results"]) == 1
    assert result["total"] == 3


def test_adr_search_empty_dir(tmp_path: Path) -> None:
    result = adr_search(workspace_root=tmp_path)
    assert result["results"] == []
    assert result["total"] == 0


def test_adr_search_sort_order_newest_first(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(workspace_root=tmp_path)
    numbers = [r["number"] for r in result["results"]]
    assert numbers == sorted(numbers, reverse=True)


def test_adr_search_tag_case_insensitive(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(tag="PERSISTENCE", workspace_root=tmp_path)
    assert result["total"] == 2


def test_adr_search_query_case_insensitive(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(query="onnx", workspace_root=tmp_path)
    assert result["total"] == 1


# ---------------------------------------------------------------------------
# Phase 6: New tests for suggest/commit features
# ---------------------------------------------------------------------------


def test_adr_suggest_unescape_newlines(tmp_path: Path) -> None:
    """Literal \\n sequences in body fields are unescaped to real newlines."""
    result = _suggest_sample_adr(
        tmp_path,
        context="First paragraph.\\nSecond paragraph." + " word" * 40,
        decision="Choose this.\\nBecause reasons." + " word" * 30,
        consequences="Result one.\\nResult two." + " word" * 30,
    )
    assert "error" not in result
    md = result["markdown"]
    # Real newlines should be present; literal two-char \n should not
    assert "First paragraph.\nSecond paragraph." in md
    assert "First paragraph.\\nSecond paragraph." not in md


def test_adr_suggest_supersedes(tmp_path: Path) -> None:
    """Supersedes list is passed through to the generated ADR."""
    result = _suggest_sample_adr(tmp_path, supersedes=["ADR-007", "ADR-012"])
    assert "error" not in result
    adr = parse_adr(result["markdown"])
    assert adr.supersedes == ["ADR-007", "ADR-012"]


def test_adr_suggest_word_count(tmp_path: Path) -> None:
    """word_count reflects the exact count across context+decision+consequences."""
    ctx = "one two three four five"  # 5 words
    dec = "six seven eight nine ten"  # 5 words
    con = "eleven twelve thirteen fourteen fifteen"  # 5 words
    result = _suggest_sample_adr(tmp_path, context=ctx, decision=dec, consequences=con)
    assert "error" not in result
    assert result["word_count"] == 15


def test_adr_suggest_draft_id(tmp_path: Path) -> None:
    """draft_id is a slugified version of the title."""
    result = _suggest_sample_adr(tmp_path, title="Use ONNX Runtime")
    assert "error" not in result
    assert result["draft_id"] == "use-onnx-runtime"


def test_adr_suggest_draft_title_format(tmp_path: Path) -> None:
    """Preview markdown uses ADR-DRAFT: header, not ADR-000:."""
    result = _suggest_sample_adr(tmp_path)
    assert "error" not in result
    assert "ADR-DRAFT:" in result["markdown"]
    assert "ADR-000:" not in result["markdown"]


def test_adr_commit_markdown_in_response(tmp_path: Path) -> None:
    """Committed ADR returns the rendered markdown in the response."""
    result = _commit_sample_adr(tmp_path)
    assert "markdown" in result
    # The markdown should contain the title and be parseable
    adr = parse_adr(result["markdown"])
    assert adr.title == "Use Edges"


def test_adr_commit_content_warning(tmp_path: Path) -> None:
    """Short body text triggers a content_warning in the result."""
    result = _commit_sample_adr(
        tmp_path,
        context="Short context.",
        decision="Short decision.",
        consequences="Short consequences.",
    )
    assert "path" in result
    assert "content_warning" in result
    assert "words" in result["content_warning"].lower()


def test_adr_commit_no_content_warning(tmp_path: Path) -> None:
    """Body with >=100 words does not trigger content_warning."""
    result = _commit_sample_adr(tmp_path)  # _DEFAULTS has >=100 words
    assert "path" in result
    assert "content_warning" not in result


def test_adr_commit_source_log_warning(tmp_path: Path) -> None:
    """Committing two ADRs with the same source_log triggers a warning on the second."""
    r1 = _commit_sample_adr(tmp_path, title="First", source_log="rnd-dup#L5")
    assert "path" in r1
    assert "source_log_warning" not in r1

    r2 = _commit_sample_adr(tmp_path, title="Second", source_log="rnd-dup#L5")
    assert "path" in r2
    assert "source_log_warning" in r2


def test_adr_commit_no_source_log_warning(tmp_path: Path) -> None:
    """Two ADRs with different source_log values produce no warning."""
    r1 = _commit_sample_adr(tmp_path, title="First", source_log="rnd-aaa#L1")
    assert "path" in r1
    assert "source_log_warning" not in r1

    r2 = _commit_sample_adr(tmp_path, title="Second", source_log="rnd-bbb#L2")
    assert "path" in r2
    assert "source_log_warning" not in r2


def test_adr_commit_supersedes(tmp_path: Path) -> None:
    """Supersedes list is persisted in the committed ADR file."""
    result = _commit_sample_adr(tmp_path, supersedes=["ADR-001"])
    assert "path" in result
    md = (tmp_path / result["path"]).read_text(encoding="utf-8")
    adr = parse_adr(md)
    assert adr.supersedes == ["ADR-001"]


def test_adr_commit_unescape_newlines(tmp_path: Path) -> None:
    """Literal \\n sequences in body fields are unescaped before writing."""
    result = _commit_sample_adr(
        tmp_path,
        context="First line.\\nSecond line." + " word" * 40,
        decision="Decision A.\\nDecision B." + " word" * 30,
        consequences="Consequence X.\\nConsequence Y." + " word" * 30,
    )
    assert "path" in result
    md = (tmp_path / result["path"]).read_text(encoding="utf-8")
    assert "First line.\nSecond line." in md
    assert "First line.\\nSecond line." not in md
