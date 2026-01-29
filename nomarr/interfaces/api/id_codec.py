"""HTTP-safe encoding/decoding for ArangoDB _id values.

ArangoDB _id format: "collection/key" (e.g., "libraries/12345")
Encoded format: "collection:key" (e.g., "libraries:12345")

This encoding exists ONLY to make IDs URL-safe for FastAPI path parameters.
The colon is used because it's URL-safe and visually similar to a separator.

Usage:
- Interfaces decode incoming IDs immediately after parsing.
- Interfaces encode outgoing IDs before returning JSON.
- Services, workflows, and persistence never see encoded IDs.

Architecture:
- EncodedId: Pydantic-compatible type for automatic decoding in request models
- DecodedPathId: FastAPI Path parameter with automatic decoding
- encode_id(): For encoding single IDs in responses
- encode_ids(): For recursively encoding all _id/id fields in response data
"""

from typing import Annotated, Any

from fastapi import HTTPException
from pydantic import BeforeValidator


class InvalidIdFormatError(ValueError):
    """Raised when an ID has an invalid format for encoding/decoding."""



def encode_id(arango_id: str) -> str:
    """Encode an ArangoDB _id for HTTP transport.

    Converts "collection/key" to "collection:key".

    Args:
        arango_id: Real ArangoDB _id (e.g., "libraries/12345")

    Returns:
        URL-safe encoded ID (e.g., "libraries:12345")

    Raises:
        InvalidIdFormatError: If ID contains ":" or doesn't contain "/"

    """
    if ":" in arango_id:
        msg = f"Cannot encode ID containing ':': {arango_id}"
        raise InvalidIdFormatError(msg)
    if "/" not in arango_id:
        msg = f"Invalid ArangoDB _id format (missing '/'): {arango_id}"
        raise InvalidIdFormatError(msg)

    return arango_id.replace("/", ":")


def decode_id(encoded_id: str) -> str:
    """Decode an HTTP-encoded ID back to ArangoDB _id format.

    Converts "collection:key" to "collection/key".

    Args:
        encoded_id: URL-safe encoded ID (e.g., "libraries:12345")

    Returns:
        Real ArangoDB _id (e.g., "libraries/12345")

    Raises:
        InvalidIdFormatError: If ID contains "/" or doesn't contain ":"

    """
    if "/" in encoded_id:
        msg = f"Cannot decode ID containing '/': {encoded_id}"
        raise InvalidIdFormatError(msg)
    if ":" not in encoded_id:
        msg = f"Invalid encoded ID format (missing ':'): {encoded_id}"
        raise InvalidIdFormatError(msg)

    return encoded_id.replace(":", "/")


def _validate_and_decode_id(value: str) -> str:
    """Pydantic validator that decodes an encoded ID.

    Used with Annotated to create the EncodedId type.
    """
    if not isinstance(value, str):
        msg = f"ID must be a string, got {type(value).__name__}"
        raise ValueError(msg)
    return decode_id(value)


# Pydantic-compatible type for request body models.
# Automatically decodes "collection:key" to "collection/key" during validation.
EncodedId = Annotated[str, BeforeValidator(_validate_and_decode_id)]


def decode_path_id(encoded_id: str) -> str:
    """Decode a path parameter ID, raising HTTPException on invalid format.

    Use this at the start of route handlers for path parameters:

        @router.get("/{library_id}")
        async def get_library(library_id: str):
            library_id = decode_path_id(library_id)
            ...

    Args:
        encoded_id: Encoded ID from path parameter (e.g., "libraries:123")

    Returns:
        Decoded ArangoDB _id (e.g., "libraries/123")

    Raises:
        HTTPException: 400 if ID format is invalid

    """
    try:
        return decode_id(encoded_id)
    except InvalidIdFormatError:
        raise HTTPException(status_code=400, detail="Invalid ID format") from None


# Fields that should be encoded when found in response data
_ID_FIELD_NAMES = frozenset({"_id", "id", "library_id", "file_id", "job_id", "task_id"})


def encode_ids(data: Any) -> Any:
    """Recursively encode all ID fields in response data.

    Walks through dicts, lists, and Pydantic models to find and encode
    fields that look like ArangoDB _ids.

    Args:
        data: Response data (dict, list, Pydantic model, or primitive)

    Returns:
        Data with all ID fields encoded for HTTP transport

    Note:
        Only encodes string values containing "/" (valid ArangoDB _ids).
        Silently skips values that don't match the expected format.

    """
    if data is None:
        return None

    # Handle Pydantic models by converting to dict first
    if hasattr(data, "model_dump"):
        data = data.model_dump()

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key in _ID_FIELD_NAMES and isinstance(value, str) and "/" in value and ":" not in value:
                # This looks like an ArangoDB _id, encode it
                result[key] = encode_id(value)
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
