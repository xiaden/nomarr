"""HTTP-safe encoding/decoding for database primary key IDs.

PostgreSQL uses integer primary keys which are natively URL-safe, so
encoding is a pass-through that ensures integer type.

Usage:
- Interfaces decode incoming IDs immediately after parsing.
- Interfaces encode outgoing IDs before returning JSON.
- Services, workflows, and persistence never see encoded IDs.

Architecture:
- EncodedId: Pydantic-compatible type for automatic decoding in request models
- DecodedPathId: FastAPI Path parameter with automatic decoding
- encode_id(): For encoding single IDs in responses (pass-through for integers)
- encode_ids(): For recursively encoding all id fields in response data (pass-through)
"""

from typing import Annotated, Any

from fastapi import HTTPException
from pydantic import BeforeValidator


class InvalidIdFormatError(ValueError):
    """Raised when an ID has an invalid format for encoding/decoding."""


def encode_id(id_value: int | str) -> int:
    """Encode a database primary key for HTTP transport.

    PostgreSQL integer IDs are natively URL-safe, so this is a pass-through
    that ensures the result is an integer.

    Args:
        id_value: Primary key value (integer or string representation)

    Returns:
        Integer primary key

    Raises:
        InvalidIdFormatError: If value cannot be converted to int

    """
    if isinstance(id_value, int):
        return id_value
    try:
        return int(id_value)
    except (ValueError, TypeError):
        msg = f"Invalid ID format (not an integer): {id_value}"
        raise InvalidIdFormatError(msg) from None


def decode_id(id_value: int | str) -> int:
    """Decode an HTTP-provided ID to a database primary key.

    PostgreSQL integer IDs are natively URL-safe, so this is a pass-through
    that ensures the result is an integer.

    Args:
        id_value: ID from HTTP request (integer or string representation)

    Returns:
        Integer primary key

    Raises:
        InvalidIdFormatError: If value cannot be converted to int

    """
    if isinstance(id_value, int):
        return id_value
    try:
        return int(id_value)
    except (ValueError, TypeError):
        msg = f"Invalid ID format (not an integer): {id_value}"
        raise InvalidIdFormatError(msg) from None


def _validate_and_decode_id(value: Any) -> int:
    """Pydantic validator that decodes an ID to an integer.

    Used with Annotated to create the EncodedId type.
    """
    return decode_id(value)


# Pydantic-compatible type for request body models.
# Automatically converts to integer during validation.
EncodedId = Annotated[int, BeforeValidator(_validate_and_decode_id)]


def decode_path_id(path_id: str | int) -> int:
    """Decode a path parameter ID, raising HTTPException on invalid format.

    Use this at the start of route handlers for path parameters:

        @router.get("/{library_id}")
        async def get_library(library_id: int):
            library_id = decode_path_id(library_id)
            ...

    Args:
        path_id: ID from path parameter

    Returns:
        Integer primary key

    Raises:
        HTTPException: 400 if ID format is invalid

    """
    try:
        return decode_id(path_id)
    except InvalidIdFormatError:
        raise HTTPException(status_code=400, detail="Invalid ID format") from None


# Fields that should be encoded when found in response data
_ID_FIELD_NAMES = frozenset({"_id", "id", "library_id", "file_id", "job_id", "task_id"})


def encode_ids(data: Any) -> Any:
    """Recursively process all ID fields in response data.

    Walks through dicts, lists, and Pydantic models.  Integer ID values
    pass through unchanged (PostgreSQL IDs are natively URL-safe).

    Args:
        data: Response data (dict, list, Pydantic model, or primitive)

    Returns:
        Data with all ID fields as integers

    Note:
        String values in ID fields are converted to int when possible.
        Silently skips values that cannot be converted.

    """
    if data is None:
        return None

    # Handle Pydantic models by converting to dict first
    if hasattr(data, "model_dump"):
        data = data.model_dump()

    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for key, value in data.items():
            if key in _ID_FIELD_NAMES and isinstance(value, str):
                try:
                    result[key] = int(value)
                except (ValueError, TypeError):
                    result[key] = value
            elif isinstance(value, list | dict):
                # Recurse into nested structures
                result[key] = encode_ids(value)
            else:
                result[key] = value
        return result

    if isinstance(data, list):
        return [encode_ids(item) for item in data]

    # Primitives pass through unchanged
    return data
