"""DTO mapping functions for LibraryService.

This module contains functions to convert raw database dictionaries
to typed DTOs for service responses. Kept separate from components
to maintain clean layer boundaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.library_dto import FileTag, LibraryFileWithTags
from nomarr.helpers.dto.queue_dto import Job

if TYPE_CHECKING:
    pass


def map_file_with_tags_to_dto(file_dict: dict[str, Any]) -> LibraryFileWithTags:
    """
    Convert a raw file dictionary (with tags) to LibraryFileWithTags DTO.

    Args:
        file_dict: Dictionary from search_library_files_with_tags query
                   Must contain '_id', 'path', 'library_id', 'tagged', and 'tags' keys

    Returns:
        LibraryFileWithTags DTO
    """
    return LibraryFileWithTags(
        _id=file_dict["_id"],
        path=file_dict["path"],
        library_id=file_dict["library_id"],
        file_size=file_dict.get("file_size"),
        modified_time=file_dict.get("modified_time"),
        duration_seconds=file_dict.get("duration_seconds"),
        artist=file_dict.get("artist"),
        album=file_dict.get("album"),
        title=file_dict.get("title"),
        calibration=file_dict.get("calibration"),
        scanned_at=file_dict.get("scanned_at"),
        last_tagged_at=file_dict.get("last_tagged_at"),
        tagged=file_dict["tagged"],
        tagged_version=file_dict.get("tagged_version"),
        skip_auto_tag=file_dict.get("skip_auto_tag", 0),
        created_at=file_dict.get("created_at"),
        updated_at=file_dict.get("updated_at"),
        tags=[
            FileTag(
                key=tag["key"],
                value=tag["value"],
                type=tag["type"],
                is_nomarr=tag["is_nomarr"],
            )
            for tag in file_dict["tags"]
        ],
    )


def map_queue_job_to_dto(job_dict: dict[str, Any]) -> Job:
    """
    Convert a raw queue job dictionary to Job DTO.

    Args:
        job_dict: Dictionary from list_jobs query
                  Must contain '_id', 'path', 'status', 'started_at' keys

    Returns:
        Job DTO
    """
    return Job(
        _id=job_dict["_id"],
        path=job_dict["path"],
        status=job_dict["status"],
        created_at=job_dict.get("created_at", 0),
        started_at=job_dict["started_at"],
        finished_at=job_dict.get("completed_at"),  # Map completed_at → finished_at
        error_message=job_dict.get("error_message"),
        force=job_dict.get("force", False),
    )
