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

func TestDescriptorSearchQueryUsesResultDescriptor(t *testing.T) {
	first := nomarrSongDescriptor{Title: "Seed Song", Artist: "Seed Artist"}
	second := nomarrSongDescriptor{Title: "Result Song", Artist: "Result Artist"}

	q1 := descriptorSearchQuery(first)
	q2 := descriptorSearchQuery(second)

	if q1 == q2 {
		t.Fatalf("expected per-descriptor search queries to differ, got %q", q1)
	}
	if q2 != "Result Song Result Artist" {
		t.Fatalf("unexpected descriptor query: %q", q2)
	}
}

func TestPerResultDescriptorResolutionUsesDescriptorSpecificCandidates(t *testing.T) {
	descriptors := []nomarrSongDescriptor{
		{Title: "Song A", Artist: "Artist A", Album: "Album A", DurationMs: intPtr(200000)},
		{Title: "Song B", Artist: "Artist B", Album: "Album B", DurationMs: intPtr(210000)},
	}
	candidateByQuery := map[string][]subsonicSong{
		"Song A Artist A": {
			{ID: "nd-a", Title: "Song A", Artist: "Artist A", Album: "Album A", DurationMs: intPtr(200000)},
		},
		"Song B Artist B": {
			{ID: "nd-b", Title: "Song B", Artist: "Artist B", Album: "Album B", DurationMs: intPtr(210000)},
		},
	}

	resolvedIDs := make([]string, 0, len(descriptors))
	for _, descriptor := range descriptors {
		query := descriptorSearchQuery(descriptor)
		candidates := candidateByQuery[query]
		resolved, status := resolveDescriptorAgainstCandidates(descriptor, candidates)
		if status != "" {
			t.Fatalf("expected descriptor %q to resolve, got status %q", descriptor.Title, status)
		}
		resolvedIDs = append(resolvedIDs, resolved.ID)
	}

	if len(resolvedIDs) != 2 || resolvedIDs[0] != "nd-a" || resolvedIDs[1] != "nd-b" {
		t.Fatalf("unexpected resolved IDs: %#v", resolvedIDs)
	}
}

func TestResultDescriptorDoesNotResolveFromSeedCandidatePool(t *testing.T) {
	seedDescriptor := nomarrSongDescriptor{Title: "Seed Song", Artist: "Seed Artist", Album: "Seed Album", DurationMs: intPtr(200000)}
	resultDescriptor := nomarrSongDescriptor{Title: "Result Song", Artist: "Result Artist", Album: "Result Album", DurationMs: intPtr(210000)}

	seedCandidates := []subsonicSong{
		{ID: "nd-seed", Title: "Seed Song", Artist: "Seed Artist", Album: "Seed Album", DurationMs: intPtr(200000)},
	}
	resultCandidates := []subsonicSong{
		{ID: "nd-result", Title: "Result Song", Artist: "Result Artist", Album: "Result Album", DurationMs: intPtr(210000)},
	}

	_, seedPoolStatus := resolveDescriptorAgainstCandidates(resultDescriptor, seedCandidates)
	if seedPoolStatus != "descriptor_unresolved" {
		t.Fatalf("expected unresolved against seed pool, got %q", seedPoolStatus)
	}

	resolved, resultPoolStatus := resolveDescriptorAgainstCandidates(resultDescriptor, resultCandidates)
	if resultPoolStatus != "" {
		t.Fatalf("expected resolved against result pool, got %q", resultPoolStatus)
	}
	if resolved.ID != "nd-result" {
		t.Fatalf("expected nd-result, got %q", resolved.ID)
	}

	// Guard sanity: seed still resolves in its own pool.
	seedResolved, seedStatus := resolveDescriptorAgainstCandidates(seedDescriptor, seedCandidates)
	if seedStatus != "" || seedResolved.ID != "nd-seed" {
		t.Fatalf("expected seed to resolve in seed pool, got status=%q id=%q", seedStatus, seedResolved.ID)
	}
}
