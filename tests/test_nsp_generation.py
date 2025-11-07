"""
Tests for Navidrome Smart Playlist (.nsp) generation.
"""

import json

import pytest

from nomarr.data.db import Database
from nomarr.services.navidrome.playlist_generator import PlaylistGenerator


@pytest.fixture
def db_with_library(temp_db: str) -> tuple[Database, str]:
    """Create a database with sample library files and tags for playlist testing."""
    db = Database(temp_db)

    # Add sample files
    files = [
        {
            "path": "/music/Rock/Album1/Track1.mp3",
            "file_size": 5000000,
            "modified_time": 1234567890000,
            "duration_seconds": 180.0,
            "artist": "The Beatles",
            "album": "Abbey Road",
            "title": "Come Together",
            "genre": "Rock",
            "year": 1969,
            "track_number": 1,
        },
        {
            "path": "/music/Rock/Album1/Track2.mp3",
            "file_size": 5100000,
            "modified_time": 1234567891000,
            "duration_seconds": 200.0,
            "artist": "The Beatles",
            "album": "Abbey Road",
            "title": "Something",
            "genre": "Rock",
            "year": 1969,
            "track_number": 2,
        },
        {
            "path": "/music/Electronic/Album1/Track1.mp3",
            "file_size": 4800000,
            "modified_time": 1234567892000,
            "duration_seconds": 210.0,
            "artist": "Daft Punk",
            "album": "Discovery",
            "title": "One More Time",
            "genre": "Electronic",
            "year": 2001,
            "track_number": 1,
        },
    ]

    for file_data in files:
        db.upsert_library_file(**file_data)

    # Add tags for each file
    file1 = db.get_library_file("/music/Rock/Album1/Track1.mp3")
    assert file1 is not None
    db.upsert_file_tags(
        file1["id"],
        {
            "nom:mood_happy": "0.8",
            "nom:energy": "0.7",
            "nom:genre": "Rock",
            "nom:danceability": "0.5",
        },
    )

    file2 = db.get_library_file("/music/Rock/Album1/Track2.mp3")
    assert file2 is not None
    db.upsert_file_tags(
        file2["id"],
        {
            "nom:mood_happy": "0.8",
            "nom:energy": "0.7",
            "nom:genre": "Rock",
            "nom:danceability": "0.5",
        },
    )

    file3 = db.get_library_file("/music/Electronic/Album1/Track1.mp3")
    assert file3 is not None
    db.upsert_file_tags(
        file3["id"],
        {
            "nom:mood_happy": "0.9",
            "nom:energy": "0.9",
            "nom:genre": "Electronic",
            "nom:danceability": "0.95",
        },
    )

    return db, temp_db


def test_simple_query_to_nsp(temp_db: str):
    """Test that simple queries are correctly converted to .nsp format."""
    gen = PlaylistGenerator(temp_db, namespace="nom")

    query = "tag:mood_happy > 0.7"
    rules = gen.parse_query_to_nsp(query)

    assert rules == {"all": [{"gt": {"mood_happy": 0.7}}]}


def test_and_query_to_nsp(temp_db: str):
    """Test that AND queries are correctly converted to .nsp format."""
    gen = PlaylistGenerator(temp_db, namespace="nom")

    query = "tag:mood_happy > 0.7 AND tag:energy > 0.6"
    rules = gen.parse_query_to_nsp(query)

    assert rules == {"all": [{"gt": {"mood_happy": 0.7}}, {"gt": {"energy": 0.6}}]}


def test_or_query_to_nsp(temp_db: str):
    """Test that OR queries are correctly converted to .nsp format."""
    gen = PlaylistGenerator(temp_db, namespace="nom")

    query = "tag:genre = Rock OR tag:genre = Metal"
    rules = gen.parse_query_to_nsp(query)

    assert rules == {"any": [{"is": {"genre": "Rock"}}, {"is": {"genre": "Metal"}}]}


def test_contains_query_to_nsp(temp_db: str):
    """Test that contains queries are correctly converted to .nsp format."""
    gen = PlaylistGenerator(temp_db, namespace="nom")

    query = "tag:artist contains Beatles"
    rules = gen.parse_query_to_nsp(query)

    assert rules == {"all": [{"contains": {"artist": "Beatles"}}]}


def test_full_nsp_generation(temp_db: str):
    """Test full .nsp file generation with all parameters."""
    gen = PlaylistGenerator(temp_db, namespace="nom")

    nsp_content = gen.generate_nsp(
        query="tag:mood_happy > 0.7 AND tag:danceability > 0.8",
        playlist_name="Happy Dance",
        comment="High-energy dance tracks",
        sort="-rating,title",
        limit=50,
    )

    nsp_data = json.loads(nsp_content)

    assert nsp_data["name"] == "Happy Dance"
    assert nsp_data["comment"] == "High-energy dance tracks"
    assert nsp_data["sort"] == "-rating,title"
    assert nsp_data["limit"] == 50
    assert "all" in nsp_data
    assert len(nsp_data["all"]) == 2


def test_preview_playlist(db_with_library: tuple[Database, str]):
    """Test playlist preview functionality."""
    db, db_path = db_with_library
    gen = PlaylistGenerator(db_path, namespace="nom")

    # Preview happy tracks
    result = gen.preview_playlist("tag:mood_happy > 0.75", preview_limit=10)

    assert result["total_count"] == 3  # All 3 tracks have mood_happy > 0.75
    assert len(result["sample_tracks"]) == 3
    assert result["query"] == "tag:mood_happy > 0.75"

    # Check track structure
    track = result["sample_tracks"][0]
    assert "title" in track
    assert "artist" in track
    assert "album" in track
    assert "file_path" in track


def test_preview_with_and_condition(db_with_library: tuple[Database, str]):
    """Test playlist preview with AND condition."""
    db, db_path = db_with_library
    gen = PlaylistGenerator(db_path, namespace="nom")

    # Preview happy AND high danceability (should only match electronic track)
    result = gen.preview_playlist("tag:mood_happy > 0.85 AND tag:danceability > 0.9", preview_limit=10)

    assert result["total_count"] == 1
    assert len(result["sample_tracks"]) == 1
    assert "Daft Punk" in result["sample_tracks"][0]["artist"]


def test_namespace_stripping(temp_db: str):
    """Test that namespace is correctly stripped from field names."""
    gen = PlaylistGenerator(temp_db, namespace="nom")

    # Query with explicit namespace
    query = "tag:nom:mood_happy > 0.7"
    rules = gen.parse_query_to_nsp(query)

    # Field name should not have namespace
    assert rules == {"all": [{"gt": {"mood_happy": 0.7}}]}


def test_hyphen_to_underscore_conversion(temp_db: str):
    """Test that hyphens are converted to underscores in field names."""
    gen = PlaylistGenerator(temp_db, namespace="nom")

    query = "tag:mood-strict contains happy"
    rules = gen.parse_query_to_nsp(query)

    # Hyphens should be converted to underscores
    assert rules == {"all": [{"contains": {"mood_strict": "happy"}}]}
