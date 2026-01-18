"""Helpers for normalizing document IDs from URL path parameters.

API routes receive document keys (e.g., "3613") from URL paths.
The rest of the codebase expects full ArangoDB _id format (e.g., "libraries/3613").

These helpers translate at the interface boundary so services/workflows/persistence
always receive consistent _id format.
"""


def to_library_id(key: str) -> str:
    """Convert a library key to full _id format.

    Args:
        key: Library key from URL (e.g., "3613") or already full _id

    Returns:
        Full _id format (e.g., "libraries/3613")
    """
    if key.startswith("libraries/"):
        return key
    return f"libraries/{key}"


def to_file_id(key: str) -> str:
    """Convert a file key to full _id format.

    Args:
        key: File key from URL or already full _id

    Returns:
        Full _id format (e.g., "files/abc123")
    """
    if key.startswith("files/"):
        return key
    return f"files/{key}"


def to_job_id(key: str) -> str:
    """Convert a job key to full _id format.

    Args:
        key: Job key from URL or already full _id

    Returns:
        Full _id format (e.g., "queue/abc123")
    """
    if key.startswith("queue/"):
        return key
    return f"queue/{key}"
