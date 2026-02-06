r"""Create new files with atomic batch operations.

MCP tool for creating new files with automatic parent directory creation.
Ensures atomicity: all files created or none on any failure.

Design Principles:
- Fail fast: validates all ops before any file creation
- Atomic: complete rollback on any failure
- mkdir -p behavior: creates parent directories automatically
- Context validation: returns first ~52 lines with line numbers

Examples
--------
Single file creation:
>>> file_create_new([
...     {"path": "services/new_service.py", "content": "# New service\\n"}
... ])

Batch creation with nested directories:
>>> file_create_new([
...     {"path": "a/b/c/file1.py", "content": ""},
...     {"path": "x/y/file2.py", "content": "# File 2\\n"}
... ])

Empty file creation:
>>> file_create_new([{"path": "utils/__init__.py"}])

"""

import contextlib
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from mcp_code_intel.helpers.file_helpers import (
    atomic_write,
    resolve_path_for_create,
)
from mcp_code_intel.response_models import (
    AppliedOp,
    BatchResponse,
    FailedOp,
)


class CreateOp(BaseModel):
    """Operation for creating a new file."""

    path: str = Field(description="File path to create (workspace-relative or absolute)")
    content: str = Field(default="", description="Initial file content (default: empty)")


def _validate_operations(
    ops: list[dict],
    workspace_root: Path,
) -> tuple[list[tuple[int, CreateOp, Path]], list[FailedOp]]:
    """Validate all create operations before execution."""
    failed_ops: list[FailedOp] = []
    validated_ops: list[tuple[int, CreateOp, Path]] = []
    seen_paths: set[Path] = set()

    for idx, op_dict in enumerate(ops):
        try:
            create_op = CreateOp.model_validate(op_dict)
        except PydanticValidationError as e:
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=op_dict.get("path", "<unknown>"),
                    reason=f"Invalid operation: {e}",
                ),
            )
            continue

        # Resolve path
        result = resolve_path_for_create(create_op.path, workspace_root)
        if isinstance(result, dict):  # Error
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=create_op.path,
                    reason=result["error"],
                ),
            )
            continue

        resolved_path: Path = result

        # Check for duplicates in batch
        if resolved_path in seen_paths:
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=str(resolved_path),
                    reason="Duplicate file path in batch",
                ),
            )
            continue

        # Check file doesn't already exist
        if resolved_path.exists():
            failed_ops.append(
                FailedOp(
                    index=idx,
                    filepath=str(resolved_path),
                    reason="File already exists",
                ),
            )
            continue

        seen_paths.add(resolved_path)
        validated_ops.append((idx, create_op, resolved_path))

    return validated_ops, failed_ops


def _create_files_atomically(
    validated_ops: list[tuple[int, CreateOp, Path]],
) -> list[FailedOp] | None:
    """Create all files atomically, rolling back on any failure."""
    created_files: list[Path] = []

    try:
        for _, create_op, resolved_path in validated_ops:
            # Create parent directories
            resolved_path.parent.mkdir(parents=True, exist_ok=True)

            # Write content (atomic_write validates internally)
            write_result = atomic_write(resolved_path, create_op.content)
            if write_result is not None:
                # Write failed, trigger rollback via exception
                error_msg = write_result["error"]
                msg = f"Write failed for {resolved_path}: {error_msg}"
                raise OSError(msg) from None  # noqa: TRY301

            created_files.append(resolved_path)

    except (OSError, PermissionError) as e:
        # Rollback: delete any created files
        for created in created_files:
            with contextlib.suppress(OSError):
                created.unlink(missing_ok=True)

        # Return failure
        return [
            FailedOp(
                index=0,
                filepath=str(validated_ops[0][2]) if validated_ops else "<unknown>",
                reason=f"File creation failed: {e}",
            ),
        ]

    else:
        return None  # Success


def _build_success_response(
    validated_ops: list[tuple[int, CreateOp, Path]],
) -> list[AppliedOp]:
    """Build success response for all created files."""
    applied_ops: list[AppliedOp] = []

    for idx, _create_op, resolved_path in validated_ops:
        # Read created file to extract metadata
        content = resolved_path.read_bytes().decode("utf-8")
        lines = content.split("\n")
        line_count = len(lines)
        bytes_written = len(content.encode("utf-8"))

        # Simple validation context: "Created <path> (<bytes> bytes, <lines> lines)"
        validation_msg = f"Created {resolved_path.name} ({bytes_written} bytes, {line_count} lines)"

        applied_ops.append(
            AppliedOp(
                index=idx,
                filepath=str(resolved_path),
                start_line=1,
                end_line=line_count,
                new_context=validation_msg,
                bytes_written=bytes_written,
            ),
        )

    return applied_ops


def edit_file_create(files: list[dict], workspace_root: Path) -> dict:
    """Create new files atomically with automatic parent directory creation.

    Args:
        files: List of file dicts with 'path' and 'content'
        workspace_root: Workspace root path for resolution and security

    Returns:
        BatchResponse dict with status and operation results

    Behavior:
        - Creates parent directories automatically (mkdir -p always on)
        - Fails if any target file already exists
        - Atomic: all files created or none (complete rollback on failure)
        - Returns simple validation message with bytes and line count for each file

    """
    # Phase 1: Validate all operations
    validated_ops, failed_ops = _validate_operations(files, workspace_root)

    if failed_ops:
        return BatchResponse(
            status="failed",
            failed_ops=failed_ops,
        ).model_dump(exclude_none=True)

    # Phase 2: Create files atomically
    creation_errors = _create_files_atomically(validated_ops)

    if creation_errors:
        return BatchResponse(
            status="failed",
            failed_ops=creation_errors,
        ).model_dump(exclude_none=True)

    # Phase 3: Build success response
    applied_ops = _build_success_response(validated_ops)

    return BatchResponse(
        status="applied",
        applied_ops=applied_ops,
    ).model_dump(exclude_none=True)
