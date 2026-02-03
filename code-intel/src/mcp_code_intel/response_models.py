"""Shared response models for file mutation MCP tools.

Provides consistent response structure across all file mutation tools:
- file_create_new
- file_replace
- file_insert_text
- file_copy_paste_text
- edit_move_text
"""

from pydantic import BaseModel, Field


class AppliedOp(BaseModel):
    """Result for a successfully applied operation."""

    index: int = Field(description="Original index of the operation in the batch")
    filepath: str = Field(description="Absolute path to the file that was modified")
    start_line: int = Field(description="First line of changed region (post-change, 1-indexed)")
    end_line: int = Field(description="Last line of changed region (post-change, 1-indexed)")
    new_context: list[str] = Field(
        description="Changed region ±2 lines with line number prefixes",
    )
    bytes_written: int | None = Field(None, description="Total bytes written to file")

    # Optional fields for specific operations
    target_filepath: str | None = Field(
        default=None, description="Target file path (for move operations)"
    )
    target_created: bool | None = Field(default=None, description="Whether target file was created")
    warnings: list[str] | None = Field(
        default=None, description="Non-fatal warnings for this operation"
    )


class FailedOp(BaseModel):
    """Result for a failed operation."""

    index: int = Field(description="Original index of the operation in the batch")
    filepath: str = Field(description="File path that caused the failure")
    reason: str = Field(description="Human-readable error message explaining the failure")


class BatchResponse(BaseModel):
    """Standard response for all file mutation tools."""

    status: str = Field(description="'applied' if all ops succeeded, 'failed' if any failed")
    applied_ops: list[AppliedOp] = Field(
        default_factory=list,
        description="List of successfully applied operations (empty if status='failed')",
    )
    failed_ops: list[FailedOp] = Field(
        default_factory=list,
        description="List of failed operations (empty if status='applied')",
    )

    def model_post_init(self, __context, /) -> None:
        """Validate response invariants."""
        if self.status == "applied" and self.failed_ops:
            msg = "status='applied' but failed_ops is not empty"
            raise ValueError(msg)
        if self.status == "failed" and not self.failed_ops:
            msg = "status='failed' but failed_ops is empty"
            raise ValueError(msg)
        if self.status == "failed" and self.applied_ops:
            msg = "status='failed' but applied_ops is not empty (atomic failure required)"
            raise ValueError(msg)


class FileOperationError(Exception):
    """Base exception for file operation errors."""


class BatchOperationError(FileOperationError):
    """Exception for batch operation failures with structured error info."""

    def __init__(self, failed_ops: list[FailedOp]) -> None:
        """Initialize with list of failed operations."""
        self.failed_ops = failed_ops
        super().__init__(f"Batch operation failed: {len(failed_ops)} errors")


class ValidationError(FileOperationError):
    """Exception for validation failures during operation setup."""


class ConflictError(FileOperationError):
    """Exception for conflicting operations in a batch."""
