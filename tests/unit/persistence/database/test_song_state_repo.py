"""Unit tests for SongStateRepository."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, insert, select

from nomarr.helpers.constants.file_states import (
    ALL_STATE_VERTICES,
    STATE_CALIBRATED,
    STATE_HYDRATED,
    STATE_NOT_HYDRATED,
    STATE_PROCESSED,
)
from nomarr.persistence.database.song_state_repo import SongStateRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_state import SongState


def _create_library_and_song(session) -> tuple[int, int]:
    """Helper: insert a library and song, return (library_id, song_id)."""
    lib_r = session.execute(
        insert(Library).values(
            name="State Lib",
            path="/state/lib",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    lib_id = lib_r.inserted_primary_key[0]
    song_r = session.execute(
        insert(Song).values(
            library_id=lib_id,
            path="/state/lib/test.mp3",
            normalized_path="/state/lib/test.mp3",
            file_size=1000,
            modified_time=1000,
            duration_seconds=180,
            needs_tagging=0,
            is_valid=1,
            tagged=0,
            created_at=1000,
        )
    )
    song_id = song_r.inserted_primary_key[0]
    return lib_id, song_id


@pytest.mark.unit
@pytest.mark.integration
class TestSongStateRepository:
    """Tests for SongStateRepository CRUD and query methods."""

    def test_get_song_states_returns_all_names(self, pg_session) -> None:
        """get_song_states should return every state assigned to a song."""
        repo = SongStateRepository(pg_session)
        repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)

        repo.assign_state(song_id, STATE_PROCESSED)
        assert repo.get_song_states(song_id) == {STATE_PROCESSED}

    def test_get_song_states_includes_assignments_on_other_axes(self, pg_session) -> None:
        """The single-song accessor should return all independent axes."""
        repo = SongStateRepository(pg_session)
        repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)

        repo.assign_state(song_id, STATE_CALIBRATED)
        repo.assign_state(song_id, STATE_PROCESSED)

        assert repo.get_song_states(song_id) == {STATE_CALIBRATED, STATE_PROCESSED}

    def test_get_song_states_nonexistent(self, pg_session) -> None:
        """get_song_states should return an empty set for song with no state."""
        repo = SongStateRepository(pg_session)
        result = repo.get_song_states(999999)
        assert result == set()

    def test_get_song_states_for_songs(self, pg_session) -> None:
        """get_song_states_for_songs should return dict of song_id -> state names."""
        repo = SongStateRepository(pg_session)
        repo.bootstrap_states([])

        # Create two songs
        lib_r = pg_session.execute(
            insert(Library).values(
                name="Batch Lib",
                path="/batch/lib",
                library_type="music",
                auto_tag=0,
                auto_curate=0,
                created_at=2000,
                updated_at=2000,
            )
        )
        lib_id = lib_r.inserted_primary_key[0]
        song1_r = pg_session.execute(
            insert(Song).values(
                library_id=lib_id,
                path="/batch/lib/test1.mp3",
                normalized_path="/batch/lib/test1.mp3",
                file_size=1000,
                modified_time=2000,
                duration_seconds=180,
                needs_tagging=0,
                is_valid=1,
                tagged=0,
                created_at=2000,
            )
        )
        song2_r = pg_session.execute(
            insert(Song).values(
                library_id=lib_id,
                path="/batch/lib/test2.mp3",
                normalized_path="/batch/lib/test2.mp3",
                file_size=1000,
                modified_time=2000,
                duration_seconds=180,
                needs_tagging=0,
                is_valid=1,
                tagged=0,
                created_at=2000,
            )
        )
        song1_id, song2_id = song1_r.inserted_primary_key[0], song2_r.inserted_primary_key[0]

        repo.assign_state(song1_id, STATE_PROCESSED)
        repo.assign_state(song2_id, "hydrated")

        result = repo.get_song_states_for_songs([song1_id, song2_id])
        assert song1_id in result
        assert song2_id in result
        assert STATE_PROCESSED in result[song1_id]
        assert "hydrated" in result[song2_id]

    def test_list_songs_in_state(self, pg_session) -> None:
        """list_songs_in_state should return song ids assigned to a state."""
        repo = SongStateRepository(pg_session)
        repo.bootstrap_states([])

        lib_r = pg_session.execute(
            insert(Library).values(
                name="List Lib",
                path="/list/lib",
                library_type="music",
                auto_tag=0,
                auto_curate=0,
                created_at=3000,
                updated_at=3000,
            )
        )
        lib_id = lib_r.inserted_primary_key[0]
        song1_r = pg_session.execute(
            insert(Song).values(
                library_id=lib_id,
                path="/list/lib/test1.mp3",
                normalized_path="/list/lib/test1.mp3",
                file_size=1000,
                modified_time=3000,
                duration_seconds=180,
                needs_tagging=0,
                is_valid=1,
                tagged=0,
                created_at=3000,
            )
        )
        song2_r = pg_session.execute(
            insert(Song).values(
                library_id=lib_id,
                path="/list/lib/test2.mp3",
                normalized_path="/list/lib/test2.mp3",
                file_size=1000,
                modified_time=3000,
                duration_seconds=180,
                needs_tagging=0,
                is_valid=1,
                tagged=0,
                created_at=3000,
            )
        )
        song1_id, song2_id = song1_r.inserted_primary_key[0], song2_r.inserted_primary_key[0]

        repo.assign_state(song1_id, STATE_PROCESSED)
        repo.assign_state(song2_id, STATE_PROCESSED)

        result = repo.list_songs_in_state(STATE_PROCESSED)
        assert song1_id in result
        assert song2_id in result

    def test_count_songs_in_state(self, pg_session) -> None:
        """count_songs_in_state should return count of songs in a state."""
        repo = SongStateRepository(pg_session)
        repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)

        repo.assign_state(song_id, STATE_PROCESSED)
        count = repo.count_songs_in_state(STATE_PROCESSED)
        assert count >= 1

    def test_assign_state(self, pg_session) -> None:
        """assign_state should create a song-state assignment."""
        repo = SongStateRepository(pg_session)
        repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)

        repo.assign_state(song_id, STATE_PROCESSED)
        assert repo.get_song_states(song_id) == {STATE_PROCESSED}

    def test_assign_states_is_idempotent(self, pg_session) -> None:
        """Batch assignment should tolerate duplicate rows and retries."""
        repo = SongStateRepository(pg_session)
        repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)

        repo.assign_states([song_id, song_id], STATE_PROCESSED)
        repo.assign_states([song_id], STATE_PROCESSED)

        assert repo.get_song_states(song_id) == {STATE_PROCESSED}

    def test_assign_state_unknown_raises(self, pg_session) -> None:
        """assign_state should raise ValueError for unknown state name."""
        repo = SongStateRepository(pg_session)
        repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)

        with pytest.raises(ValueError, match="Unknown song state"):
            repo.assign_state(song_id, "nonexistent_state")

    def test_ensure_song_state_fresh_song(self, pg_session) -> None:
        """ensure_song_state should assign state to a song with no state yet."""
        repo = SongStateRepository(pg_session)
        repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)

        repo.ensure_song_state(song_id, STATE_PROCESSED)
        assert repo.get_song_states(song_id) == {STATE_PROCESSED}

    def test_ensure_song_state_does_not_override(self, pg_session) -> None:
        """ensure_song_state should leave an existing assignment untouched."""
        repo = SongStateRepository(pg_session)
        repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)

        repo.assign_state(song_id, "hydrated")
        repo.ensure_song_state(song_id, STATE_PROCESSED)
        assert repo.get_song_states(song_id) == {"hydrated"}
        assert repo.get_song_states_for_songs([song_id])[song_id] == {"hydrated"}

    def test_remove_states_for_songs(self, pg_session) -> None:
        """remove_states_for_songs should delete assignments."""
        repo = SongStateRepository(pg_session)
        repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)

        repo.assign_state(song_id, STATE_PROCESSED)
        repo.remove_states_for_songs([song_id])

        assert repo.get_song_states(song_id) == set()

    def test_bootstrap_states_creates_canonical(self, pg_session) -> None:
        """bootstrap_states should seed the 16 canonical vertices and no legacy names."""
        repo = SongStateRepository(pg_session)
        # Clear existing states
        pg_session.execute(delete(SongState))
        pg_session.commit()

        repo.bootstrap_states([])

        # Verify the 16 canonical state vertices exist
        result = pg_session.execute(select(SongState))
        states = result.scalars().all()
        assert len(states) == 16
        names = {s.name for s in states}
        assert names == set(ALL_STATE_VERTICES)

        # Verify none of the legacy-only names remain ("written" is now a
        # canonical vertex, so it is legitimately present among the 16).
        legacy_only = {"pending", "tagged", "curated", "error"}
        assert names.isdisjoint(legacy_only)

    def test_bootstrap_states_assigns_processed(self, pg_session) -> None:
        """bootstrap_states([song_id]) should assign STATE_PROCESSED to that song."""
        repo = SongStateRepository(pg_session)
        # Clear existing states so the seed runs
        pg_session.execute(delete(SongState))
        pg_session.commit()
        _, song_id = _create_library_and_song(pg_session)

        repo.bootstrap_states([song_id])

        # The song should carry the processed state.
        assert repo.get_song_states(song_id) == {STATE_PROCESSED}

    def test_transition_to_hydrated_seeds_unseeded_states(self, pg_session) -> None:
        """Hydration should not no-op when the state lookup is empty."""
        repo = SongStateRepository(pg_session)
        pg_session.execute(delete(SongState))
        pg_session.commit()
        _, song_id = _create_library_and_song(pg_session)

        repo.transition_to_hydrated([song_id])

        assert repo.get_song_states(song_id) == {STATE_HYDRATED}
        assert pg_session.execute(select(SongState)).scalars().all()
        assert repo.get_song_states_for_songs([song_id])[song_id] == {STATE_HYDRATED}
        assert STATE_NOT_HYDRATED not in repo.get_song_states(song_id)

    def test_count_for_song_and_state(self, pg_session) -> None:
        """count_for_song_and_state should return count of assignments."""
        repo = SongStateRepository(pg_session)
        repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)

        repo.assign_state(song_id, STATE_PROCESSED)

        # Get state_id for STATE_PROCESSED
        result = pg_session.execute(select(SongState).where(SongState.name == STATE_PROCESSED))
        state = result.scalar_one()
        state_id = state.id

        count = repo.count_for_song_and_state(song_id, state_id)
        assert count == 1

    def test_truncate_assignments(self, pg_session) -> None:
        """truncate_assignments should remove all assignment rows."""
        repo = SongStateRepository(pg_session)
        repo.bootstrap_states([])
        _, song_id = _create_library_and_song(pg_session)

        repo.assign_state(song_id, STATE_PROCESSED)
        repo.truncate_assignments()

        count = repo.count_songs_in_state(STATE_PROCESSED)
        assert count == 0
