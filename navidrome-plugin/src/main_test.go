package main

import "testing"

func intPtr(v int) *int {
	return &v
}

func TestResolveDescriptorAgainstCandidates(t *testing.T) {
	descriptor := nomarrSongDescriptor{
		Title:      "Song",
		Artist:     "Artist",
		Album:      "Album",
		DurationMs: intPtr(200000),
	}

	t.Run("exact descriptor resolution", func(t *testing.T) {
		song, status := resolveDescriptorAgainstCandidates(descriptor, []subsonicSong{
			{ID: "1", Title: "Song", Artist: "Artist", Album: "Album", DurationMs: intPtr(200000)},
		})
		if status != "" {
			t.Fatalf("expected resolved status, got %q", status)
		}
		if song.ID != "1" {
			t.Fatalf("expected id 1, got %s", song.ID)
		}
	})

	t.Run("duplicate title artist across albums", func(t *testing.T) {
		song, status := resolveDescriptorAgainstCandidates(descriptor, []subsonicSong{
			{ID: "1", Title: "Song", Artist: "Artist", Album: "Album", DurationMs: intPtr(200000)},
			{ID: "2", Title: "Song", Artist: "Artist", Album: "Other Album", DurationMs: intPtr(200000)},
		})
		if status != "" {
			t.Fatalf("expected resolved status, got %q", status)
		}
		if song.ID != "1" {
			t.Fatalf("expected id 1, got %s", song.ID)
		}
	})

	t.Run("duplicate album editions remasters stay ambiguous", func(t *testing.T) {
		_, status := resolveDescriptorAgainstCandidates(descriptor, []subsonicSong{
			{ID: "1", Title: "Song", Artist: "Artist", Album: "Album", DurationMs: intPtr(200000)},
			{ID: "2", Title: "Song", Artist: "Artist", Album: "Album", DurationMs: intPtr(200000)},
		})
		if status != "descriptor_ambiguous" {
			t.Fatalf("expected descriptor_ambiguous, got %q", status)
		}
	})

	t.Run("duration mismatch tolerance", func(t *testing.T) {
		song, status := resolveDescriptorAgainstCandidates(descriptor, []subsonicSong{
			{ID: "1", Title: "Song", Artist: "Artist", Album: "Album", DurationMs: intPtr(201500)},
			{ID: "2", Title: "Song", Artist: "Artist", Album: "Album", DurationMs: intPtr(210000)},
		})
		if status != "" {
			t.Fatalf("expected resolved status, got %q", status)
		}
		if song.ID != "1" {
			t.Fatalf("expected id 1, got %s", song.ID)
		}
	})

	t.Run("unresolved descriptor", func(t *testing.T) {
		_, status := resolveDescriptorAgainstCandidates(descriptor, []subsonicSong{
			{ID: "1", Title: "Different", Artist: "Artist", Album: "Album", DurationMs: intPtr(200000)},
		})
		if status != "descriptor_unresolved" {
			t.Fatalf("expected descriptor_unresolved, got %q", status)
		}
	})

	t.Run("musicbrainz ambiguous", func(t *testing.T) {
		_, status := resolveDescriptorAgainstCandidates(
			nomarrSongDescriptor{MusicBrainzRecordingID: "mbid-1"},
			[]subsonicSong{
				{ID: "1", MusicBrainzRecordingID: "mbid-1"},
				{ID: "2", MusicBrainzRecordingID: "mbid-1"},
			},
		)
		if status != "descriptor_ambiguous" {
			t.Fatalf("expected descriptor_ambiguous, got %q", status)
		}
	})

	t.Run("partial result resolution", func(t *testing.T) {
		descriptors := []nomarrSongDescriptor{
			{Title: "Song", Artist: "Artist", Album: "Album", DurationMs: intPtr(200000)},
			{Title: "Missing", Artist: "Artist"},
		}
		candidates := []subsonicSong{
			{ID: "1", Title: "Song", Artist: "Artist", Album: "Album", DurationMs: intPtr(200000)},
		}
		resolved := 0
		unresolved := 0
		for _, descriptor := range descriptors {
			_, status := resolveDescriptorAgainstCandidates(descriptor, candidates)
			if status == "" {
				resolved++
			}
			if status == "descriptor_unresolved" {
				unresolved++
			}
		}
		if resolved != 1 || unresolved != 1 {
			t.Fatalf("expected partial resolution 1/1, got resolved=%d unresolved=%d", resolved, unresolved)
		}
	})
}
