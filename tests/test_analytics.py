"""
Tests for analytics module (library_tags based queries).
"""

import pytest

from nomarr.data.db import Database
from nomarr.services.analytics import (
    get_artist_tag_profile,
    get_mood_distribution,
    get_mood_value_co_occurrences,
    get_tag_correlation_matrix,
    get_tag_frequencies,
)


@pytest.fixture
def db_with_tags(temp_db: str) -> Database:
    """Create a database with sample library files and tags."""
    db = Database(temp_db)

    # Add sample files
    files = [
        {
            "path": "/music/artist1/album1/track1.mp3",
            "file_size": 5000000,
            "modified_time": 1234567890000,
            "duration_seconds": 180.0,
            "artist": "Artist One",
            "album": "Album One",
            "title": "Track One",
            "genre": "Electronic",
            "year": 2020,
            "track_number": 1,
        },
        {
            "path": "/music/artist1/album1/track2.mp3",
            "file_size": 5100000,
            "modified_time": 1234567891000,
            "duration_seconds": 200.0,
            "artist": "Artist One",
            "album": "Album One",
            "title": "Track Two",
            "genre": "Electronic",
            "year": 2020,
            "track_number": 2,
        },
        {
            "path": "/music/artist2/album2/track1.mp3",
            "file_size": 4800000,
            "modified_time": 1234567892000,
            "duration_seconds": 190.0,
            "artist": "Artist Two",
            "album": "Album Two",
            "title": "Track One",
            "genre": "Rock",
            "year": 2021,
            "track_number": 1,
        },
        {
            "path": "/music/artist2/album2/track2.mp3",
            "file_size": 4900000,
            "modified_time": 1234567893000,
            "duration_seconds": 210.0,
            "artist": "Artist Two",
            "album": "Album Two",
            "title": "Track Two",
            "genre": "Rock",
            "year": 2021,
            "track_number": 2,
        },
    ]

    for file_data in files:
        db.upsert_library_file(**file_data)

    # Add tags to files
    # File 1: Happy electronic track
    file1 = db.get_library_file("/music/artist1/album1/track1.mp3")
    db.upsert_file_tags(
        file1["id"],
        {
            "nom:danceability": "danceable",
            "nom:mood-strict": ["happy", "energetic"],  # Pass as list, upsert_file_tags will handle JSON encoding
            "nom:engagement_regression": 0.85,
            "nom:approachability_regression": 0.72,
            "nom:nsynth_acoustic_electronic": "electronic",
        },
    )

    # File 2: Relaxed electronic track
    file2 = db.get_library_file("/music/artist1/album1/track2.mp3")
    db.upsert_file_tags(
        file2["id"],
        {
            "nom:danceability": "not_danceable",
            "nom:mood-strict": ["relaxed", "calm"],
            "nom:engagement_regression": 0.45,
            "nom:approachability_regression": 0.80,
            "nom:nsynth_acoustic_electronic": "electronic",
        },
    )

    # File 3: Happy rock track
    file3 = db.get_library_file("/music/artist2/album2/track1.mp3")
    db.upsert_file_tags(
        file3["id"],
        {
            "nom:danceability": "danceable",
            "nom:mood-strict": ["happy", "energetic"],
            "nom:engagement_regression": 0.90,
            "nom:approachability_regression": 0.65,
            "nom:nsynth_acoustic_electronic": "acoustic",
        },
    )

    # File 4: Sad rock track
    file4 = db.get_library_file("/music/artist2/album2/track2.mp3")
    db.upsert_file_tags(
        file4["id"],
        {
            "nom:danceability": "not_danceable",
            "nom:mood-strict": ["sad", "melancholic"],
            "nom:mood-regular": ["sad", "calm"],
            "nom:engagement_regression": 0.35,
            "nom:approachability_regression": 0.55,
            "nom:nsynth_acoustic_electronic": "acoustic",
        },
    )

    return db


def test_get_tag_frequencies(db_with_tags: Database):
    """Test tag frequency counting."""
    result = get_tag_frequencies(db_with_tags, namespace="nom", limit=10)

    assert result["total_files"] == 4

    # Check essentia tags
    tag_dict = dict(result["essentia_tags"])
    assert "danceability" in tag_dict
    assert tag_dict["danceability"] == 4  # All 4 files have danceability
    assert "mood-strict" in tag_dict
    assert tag_dict["mood-strict"] == 4  # All 4 files have mood-strict
    assert "engagement_regression" in tag_dict
    assert tag_dict["engagement_regression"] == 4

    # Check standard tags
    artists = dict(result["standard_tags"]["artists"])
    assert artists["Artist One"] == 2
    assert artists["Artist Two"] == 2

    genres = dict(result["standard_tags"]["genres"])
    assert genres["Electronic"] == 2
    assert genres["Rock"] == 2


@pytest.mark.skip(reason="Function signature changed - analyzes mood VALUES not tag keys")
def test_get_mood_value_co_occurrences(db_with_tags: Database):
    """Test co-occurrence statistics."""
    result = get_mood_value_co_occurrences(db_with_tags, "danceability", namespace="nom", limit=10)

    assert result["tag"] == "danceability"
    assert result["tag_count"] == 4  # All 4 files have danceability tag

    # Check co-occurring tags
    co_tags = {tag: count for tag, count, _ in result["essentia_co_occurrences"]}
    assert "mood-strict" in co_tags
    assert co_tags["mood-strict"] == 4  # All files with danceability also have mood-strict
    assert "engagement_regression" in co_tags

    # Check artist co-occurrences
    co_artists = {artist: count for artist, count, _ in result["artist_co_occurrences"]}
    assert co_artists["Artist One"] == 2
    assert co_artists["Artist Two"] == 2

    # Check genre co-occurrences
    co_genres = {genre: count for genre, count, _ in result["genre_co_occurrences"]}
    assert co_genres["Electronic"] == 2
    assert co_genres["Rock"] == 2


@pytest.mark.skip(reason="Function signature changed - analyzes mood VALUES not tag keys")
def test_get_mood_value_co_occurrences_no_standard(db_with_tags: Database):
    """Test co-occurrence statistics without standard metadata."""
    result = get_mood_value_co_occurrences(
        db_with_tags, "danceability", namespace="nom", limit=10, include_standard=False
    )

    assert result["tag"] == "danceability"
    assert result["tag_count"] == 4

    # Standard metadata should be empty
    assert result["artist_co_occurrences"] == []
    assert result["genre_co_occurrences"] == []
    assert result["album_co_occurrences"] == []

    # Essentia tags should still be there
    assert len(result["essentia_co_occurrences"]) > 0


@pytest.mark.skip(reason="Function signature changed - analyzes mood VALUES not tag keys")
def test_get_mood_value_co_occurrences_nonexistent_tag(db_with_tags: Database):
    """Test co-occurrence for a tag that doesn't exist."""
    result = get_mood_value_co_occurrences(db_with_tags, "nonexistent_tag", namespace="nom")

    assert result["tag"] == "nonexistent_tag"
    assert result["tag_count"] == 0
    assert result["essentia_co_occurrences"] == []
    assert result["artist_co_occurrences"] == []


def test_get_tag_correlation_matrix(db_with_tags: Database):
    """Test VALUE-based correlation matrix computation (new API)."""
    result = get_tag_correlation_matrix(db_with_tags, namespace="nom", top_n=3)

    # New API returns mood_correlations, mood_genre_correlations, mood_tier_correlations
    assert "mood_correlations" in result
    assert "mood_genre_correlations" in result
    assert "mood_tier_correlations" in result

    # Each should be a dict mapping moods to their correlations
    assert isinstance(result["mood_correlations"], dict)
    assert isinstance(result["mood_genre_correlations"], dict)
    assert isinstance(result["mood_tier_correlations"], dict)


def test_get_mood_distribution(db_with_tags: Database):
    """Test mood distribution analysis."""
    result = get_mood_distribution(db_with_tags, namespace="nom")

    # Check mood-strict
    assert "happy" in result["mood_strict"]
    assert result["mood_strict"]["happy"] == 2  # Files 1 and 3
    assert "energetic" in result["mood_strict"]
    assert result["mood_strict"]["energetic"] == 2  # Files 1 and 3
    assert "relaxed" in result["mood_strict"]
    assert result["mood_strict"]["relaxed"] == 1  # File 2
    assert "sad" in result["mood_strict"]
    assert result["mood_strict"]["sad"] == 1  # File 4

    # Check mood-regular (only file 4 has this)
    assert "sad" in result["mood_regular"]
    assert result["mood_regular"]["sad"] == 1
    assert "calm" in result["mood_regular"]
    assert result["mood_regular"]["calm"] == 1

    # Check top moods (combined)
    top_moods_dict = dict(result["top_moods"])
    assert "happy" in top_moods_dict
    assert top_moods_dict["happy"] == 2  # 2 from mood-strict
    assert "sad" in top_moods_dict
    assert top_moods_dict["sad"] == 2  # 1 from mood-strict + 1 from mood-regular


def test_get_artist_tag_profile(db_with_tags: Database):
    """Test artist tag profile analysis."""
    result = get_artist_tag_profile(db_with_tags, "Artist One", namespace="nom", limit=10)

    assert result["artist"] == "Artist One"
    assert result["file_count"] == 2

    # Check top tags
    tag_dict = {tag: (count, avg_val) for tag, count, avg_val in result["top_tags"]}
    assert "danceability" in tag_dict
    assert tag_dict["danceability"][0] == 2  # Both files have it

    # Check engagement regression average
    assert "engagement_regression" in tag_dict
    assert tag_dict["engagement_regression"][0] == 2
    # Average of 0.85 and 0.45 = 0.65
    assert abs(tag_dict["engagement_regression"][1] - 0.65) < 0.01

    # Check moods
    mood_dict = dict(result["moods"])
    assert "happy" in mood_dict
    assert mood_dict["happy"] == 1  # File 1
    assert "energetic" in mood_dict
    assert mood_dict["energetic"] == 1  # File 1
    assert "relaxed" in mood_dict
    assert mood_dict["relaxed"] == 1  # File 2

    # Avg tags per file (excluding mood tags)
    # File 1: danceability, engagement_regression, approachability_regression, nsynth_acoustic_electronic = 4
    # File 2: danceability, engagement_regression, approachability_regression, nsynth_acoustic_electronic = 4
    # Total = 8, avg = 4.0
    assert result["avg_tags_per_file"] == 4.0


def test_get_artist_tag_profile_nonexistent_artist(db_with_tags: Database):
    """Test artist profile for an artist that doesn't exist."""
    result = get_artist_tag_profile(db_with_tags, "Nonexistent Artist", namespace="nom")

    assert result["artist"] == "Nonexistent Artist"
    assert result["file_count"] == 0
    assert result["top_tags"] == []
    assert result["moods"] == []
    assert result["avg_tags_per_file"] == 0.0


def test_analytics_with_empty_database(temp_db: str):
    """Test analytics functions with empty database."""
    db = Database(temp_db)

    # Tag frequencies
    result = get_tag_frequencies(db, namespace="nom")
    assert result["total_files"] == 0
    assert result["essentia_tags"] == []

    # Correlation matrix (new API returns mood/genre/tier correlations)
    result = get_tag_correlation_matrix(db, namespace="nom")
    assert result["mood_correlations"] == {}
    assert result["mood_genre_correlations"] == {}
    assert result["mood_tier_correlations"] == {}

    # Mood distribution
    result = get_mood_distribution(db, namespace="nom")
    assert result["mood_strict"] == {}
    assert result["mood_regular"] == {}
    assert result["mood_loose"] == {}
    assert result["top_moods"] == []

    # Artist profile
    result = get_artist_tag_profile(db, "Any Artist", namespace="nom")
    assert result["file_count"] == 0
