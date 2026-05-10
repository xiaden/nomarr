// Package main implements the Nomarr plugin for Navidrome.
//
// This plugin bridges Navidrome to Nomarr's ML-powered APIs:
//   - metadata.SimilarSongsByTrackProvider — Instant Mix via vector ANN search
//   - scrobbler.Scrobbler — forwards scrobble events to Nomarr for taste profiling
//   - scheduler.CallbackProvider — scheduled personal playlist generation and push
package main

import (
	"encoding/json"
	"fmt"
	"net/url"
	"strings"
	"unicode"

	"github.com/navidrome/navidrome/plugins/pdk/go/host"
	"github.com/navidrome/navidrome/plugins/pdk/go/metadata"
	"github.com/navidrome/navidrome/plugins/pdk/go/pdk"
	"github.com/navidrome/navidrome/plugins/pdk/go/scheduler"
	"github.com/navidrome/navidrome/plugins/pdk/go/scrobbler"
)

// nomarrPlugin implements metadata.SimilarSongsByTrackProvider,
// scrobbler.Scrobbler, and scheduler.CallbackProvider.
type nomarrPlugin struct{}

func init() {
	metadata.Register(&nomarrPlugin{})
	scrobbler.Register(&nomarrPlugin{})
	scheduler.Register(&nomarrPlugin{})

	// Register playlist generation scheduler if enabled.
	ppEnabled, ok := safeGetConfig("pp_enabled")
	if ok && ppEnabled == "true" {
		cron, ok := safeGetConfig("pp_schedule_cron")
		if !ok || cron == "" {
			cron = "0 3 * * *"
		}
		if _, err := host.SchedulerScheduleRecurring(cron, "", "nomarr-playlist-gen"); err != nil {
			safeLog(pdk.LogError, fmt.Sprintf("nomarr: failed to schedule playlist generation: %v", err))
		} else {
			safeLog(pdk.LogInfo, fmt.Sprintf("nomarr: playlist generation scheduled with cron: %s", cron))
		}
	} else {
		safeLog(pdk.LogDebug, "nomarr: personal playlists not enabled")
	}
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

// readConfig reads the shared nomarr_url and nomarr_api_key from plugin config.
// Returns empty strings and ok=false if either value is missing.
func readConfig() (nomarrURL string, apiKey string, ok bool) {
	nomarrURL, found := safeGetConfig("nomarr_url")
	if !found || nomarrURL == "" {
		pdk.Log(pdk.LogWarn, "nomarr: nomarr_url not configured")
		return "", "", false
	}
	apiKey, found = safeGetConfig("nomarr_api_key")
	if !found || apiKey == "" {
		pdk.Log(pdk.LogWarn, "nomarr: nomarr_api_key not configured")
		return "", "", false
	}
	return nomarrURL, apiKey, true
}

func safeGetConfig(key string) (value string, ok bool) {
	defer func() {
		if recovered := recover(); recovered != nil {
			fmt.Printf("nomarr: recovered panic from pdk.GetConfig(%q): %v\n", key, recovered)
			value = ""
			ok = false
		}
	}()
	return pdk.GetConfig(key)
}

func safeLog(level pdk.LogLevel, message string) {
	defer func() {
		if recovered := recover(); recovered != nil {
			fmt.Printf("nomarr: recovered panic from pdk.Log: %v\n", recovered)
		}
	}()
	pdk.Log(level, message)
}

// subsonicCallAs calls a Subsonic API endpoint on behalf of a specific user.
// It prepends /rest/ and appends ?u=<username> to the endpoint URI so the
// Subsonic server executes the call in the context of that user.
// Follows the LBZ plugin pattern.
func subsonicCallAs(endpoint string, username string) (string, error) {
	sep := "?"
	if strings.Contains(endpoint, "?") {
		sep = "&"
	}
	uri := fmt.Sprintf("/rest/%s%su=%s", endpoint, sep, url.QueryEscape(username))
	return host.SubsonicAPICall(uri)
}

// xmlDecodeEntities replaces XML character entities with their literal values.
func xmlDecodeEntities(s string) string {
	s = strings.ReplaceAll(s, "&amp;", "&")
	s = strings.ReplaceAll(s, "&lt;", "<")
	s = strings.ReplaceAll(s, "&gt;", ">")
	s = strings.ReplaceAll(s, "&quot;", "\"")
	s = strings.ReplaceAll(s, "&apos;", "'")
	return s
}

// xmlAttr extracts the value of a named attribute from an XML tag string.
// tag should be the full opening tag content (e.g., `<playlist id="123" name="My List"/>`).
// Returns the decoded value and true if found, or ("", false) otherwise.
func xmlAttr(tag string, attr string) (string, bool) {
	// Look for: attr="value" or attr='value'
	needle := attr + `="`
	idx := strings.Index(tag, needle)
	if idx >= 0 {
		start := idx + len(needle)
		end := strings.Index(tag[start:], `"`)
		if end >= 0 {
			return xmlDecodeEntities(tag[start : start+end]), true
		}
	}
	// Try single quotes
	needle = attr + "='"
	idx = strings.Index(tag, needle)
	if idx >= 0 {
		start := idx + len(needle)
		end := strings.Index(tag[start:], "'")
		if end >= 0 {
			return xmlDecodeEntities(tag[start : start+end]), true
		}
	}
	return "", false
}

// findExistingPlaylists queries the Subsonic getPlaylists API for a given user
// and returns a map of playlist name → playlist ID. This is used to determine
// whether to update an existing playlist or create a new one.
//
// On any failure (API error, parse error), returns an empty map with a warning
// log — callers degrade gracefully by creating all playlists as new.
//
// NOTE: TinyGo/WASM cannot use encoding/xml, so we parse with string operations.
func findExistingPlaylists(username string) map[string]string {
	result := make(map[string]string)

	resp, err := subsonicCallAs("getPlaylists", username)
	if err != nil {
		pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: getPlaylists failed for user %s: %v", username, err))
		return result
	}

	// Find all <playlist ...> tags and extract id + name attributes.
	// Handles both self-closing (<playlist .../>) and open (<playlist ...>...</playlist>) forms.
	remaining := resp
	for {
		idx := strings.Index(remaining, "<playlist ")
		if idx < 0 {
			break
		}
		remaining = remaining[idx:]

		// Find the end of the opening tag (either /> or >)
		endSelfClose := strings.Index(remaining, "/>")
		endOpen := strings.Index(remaining, ">")

		var tag string
		if endSelfClose >= 0 && (endOpen < 0 || endSelfClose <= endOpen) {
			// Self-closing tag: <playlist ... />
			tag = remaining[:endSelfClose+2]
			remaining = remaining[endSelfClose+2:]
		} else if endOpen >= 0 {
			// Open tag: <playlist ...>
			tag = remaining[:endOpen+1]
			remaining = remaining[endOpen+1:]
		} else {
			break
		}

		id, hasID := xmlAttr(tag, "id")
		name, hasName := xmlAttr(tag, "name")
		if hasID && hasName {
			result[name] = id
		}
	}

	pdk.Log(pdk.LogDebug, fmt.Sprintf("nomarr: found %d existing playlists for user %s", len(result), username))
	return result
}

// ---------------------------------------------------------------------------
// Similar-tracks types
// ---------------------------------------------------------------------------

// nomarrRequest is the JSON body sent to Nomarr's similar-tracks endpoint.
type nomarrRequest struct {
	Seed       nomarrSongDescriptor `json:"seed"`
	Count      int32                `json:"count"`
	BackboneID string               `json:"backbone_id"`
}

// nomarrSongDescriptor is a portable track descriptor in Nomarr's API response.
type nomarrSongDescriptor struct {
	Title         string  `json:"title"`
	Artist        string  `json:"artist"`
	Album         string  `json:"album"`
	AlbumArtist   string  `json:"album_artist"`
	DurationMs    *int    `json:"duration_ms,omitempty"`
	TrackNumber   *int    `json:"track_number,omitempty"`
	DiscNumber    *int    `json:"disc_number,omitempty"`
	Year          *int    `json:"year,omitempty"`
	NomarrFileKey string  `json:"nomarr_file_key,omitempty"`
	Score         float64 `json:"score"`
}

// nomarrResponse is the JSON response from Nomarr's similar-tracks endpoint.
type nomarrResponse struct {
	Songs []nomarrSongDescriptor `json:"songs"`
}

type subsonicSong struct {
	ID          string
	Title       string
	Artist      string
	Album       string
	AlbumArtist string
	DurationMs  *int
	TrackNumber *int
	DiscNumber  *int
	Year        *int
}

func parseIntPointer(value string) *int {
	if value == "" {
		return nil
	}
	parsed := 0
	hasDigit := false
	for _, ch := range value {
		if ch < '0' || ch > '9' {
			continue
		}
		hasDigit = true
		parsed = (parsed * 10) + int(ch-'0')
	}
	if !hasDigit {
		return nil
	}
	return &parsed
}

func parseDurationMs(value string) *int {
	seconds := parseIntPointer(value)
	if seconds == nil {
		return nil
	}
	millis := *seconds * 1000
	return &millis
}

func normalizeText(value string) string {
	trimmed := strings.TrimSpace(strings.ToLower(value))
	if trimmed == "" {
		return ""
	}
	var b strings.Builder
	lastWasSpace := false
	for _, ch := range trimmed {
		if unicode.IsLetter(ch) || unicode.IsDigit(ch) {
			b.WriteRune(ch)
			lastWasSpace = false
			continue
		}
		if !lastWasSpace {
			b.WriteRune(' ')
		}
		lastWasSpace = true
	}
	return strings.TrimSpace(b.String())
}

func durationWithinTolerance(lhs *int, rhs *int, toleranceMs int) bool {
	if lhs == nil || rhs == nil {
		return false
	}
	diff := *lhs - *rhs
	if diff < 0 {
		diff = -diff
	}
	return diff <= toleranceMs
}

func parseSubsonicSongs(xml string) []subsonicSong {
	songs := make([]subsonicSong, 0)
	remaining := xml
	for {
		idx := strings.Index(remaining, "<song ")
		if idx < 0 {
			break
		}
		remaining = remaining[idx:]
		endSelfClose := strings.Index(remaining, "/>")
		endOpen := strings.Index(remaining, ">")
		var tag string
		if endSelfClose >= 0 && (endOpen < 0 || endSelfClose <= endOpen) {
			tag = remaining[:endSelfClose+2]
			remaining = remaining[endSelfClose+2:]
		} else if endOpen >= 0 {
			tag = remaining[:endOpen+1]
			remaining = remaining[endOpen+1:]
		} else {
			break
		}

		id, ok := xmlAttr(tag, "id")
		if !ok || id == "" {
			continue
		}
		title, _ := xmlAttr(tag, "title")
		artist, _ := xmlAttr(tag, "artist")
		album, _ := xmlAttr(tag, "album")
		albumArtist, _ := xmlAttr(tag, "albumArtist")
		durationRaw, _ := xmlAttr(tag, "duration")
		trackRaw, _ := xmlAttr(tag, "track")
		discRaw, _ := xmlAttr(tag, "discNumber")
		yearRaw, _ := xmlAttr(tag, "year")
		songs = append(songs, subsonicSong{
			ID:          id,
			Title:       title,
			Artist:      artist,
			Album:       album,
			AlbumArtist: albumArtist,
			DurationMs:  parseDurationMs(durationRaw),
			TrackNumber: parseIntPointer(trackRaw),
			DiscNumber:  parseIntPointer(discRaw),
			Year:        parseIntPointer(yearRaw),
		})
	}
	return songs
}

func resolveDescriptorAgainstCandidates(descriptor nomarrSongDescriptor, candidates []subsonicSong) (subsonicSong, string) {
	// Deterministic metadata-only resolution:
	// strict title/artist/album(+duration), then title/album_artist/album(+track+disc),
	// then looser title+artist(+duration), then title+artist fallback.
	// Multiple matches return descriptor_ambiguous; no matches return descriptor_unresolved.
	empty := subsonicSong{}
	title := normalizeText(descriptor.Title)
	artist := normalizeText(descriptor.Artist)
	album := normalizeText(descriptor.Album)
	albumArtist := normalizeText(descriptor.AlbumArtist)

	step2 := make([]subsonicSong, 0)
	for _, candidate := range candidates {
		if normalizeText(candidate.Title) == title &&
			normalizeText(candidate.Artist) == artist &&
			normalizeText(candidate.Album) == album &&
			durationWithinTolerance(candidate.DurationMs, descriptor.DurationMs, 2000) {
			step2 = append(step2, candidate)
		}
	}
	if len(step2) == 1 {
		return step2[0], ""
	}
	if len(step2) > 1 {
		return empty, "descriptor_ambiguous"
	}

	step3 := make([]subsonicSong, 0)
	for _, candidate := range candidates {
		if normalizeText(candidate.Title) == title &&
			normalizeText(candidate.AlbumArtist) == albumArtist &&
			normalizeText(candidate.Album) == album &&
			candidate.TrackNumber != nil &&
			descriptor.TrackNumber != nil &&
			candidate.DiscNumber != nil &&
			descriptor.DiscNumber != nil &&
			*candidate.TrackNumber == *descriptor.TrackNumber &&
			*candidate.DiscNumber == *descriptor.DiscNumber {
			step3 = append(step3, candidate)
		}
	}
	if len(step3) == 1 {
		return step3[0], ""
	}
	if len(step3) > 1 {
		return empty, "descriptor_ambiguous"
	}

	step4 := make([]subsonicSong, 0)
	for _, candidate := range candidates {
		if normalizeText(candidate.Title) == title &&
			normalizeText(candidate.Artist) == artist &&
			durationWithinTolerance(candidate.DurationMs, descriptor.DurationMs, 2000) {
			step4 = append(step4, candidate)
		}
	}
	if len(step4) == 1 {
		return step4[0], ""
	}
	if len(step4) > 1 {
		return empty, "descriptor_ambiguous"
	}

	fallback := make([]subsonicSong, 0)
	for _, candidate := range candidates {
		if normalizeText(candidate.Title) == title && normalizeText(candidate.Artist) == artist {
			fallback = append(fallback, candidate)
		}
	}
	if len(fallback) == 1 {
		return fallback[0], ""
	}
	if len(fallback) > 1 {
		return empty, "descriptor_ambiguous"
	}

	return empty, "descriptor_unresolved"
}

func descriptorSearchQuery(descriptor nomarrSongDescriptor) string {
	if descriptor.Title == "" {
		return strings.TrimSpace(descriptor.Artist + " " + descriptor.Album)
	}
	if descriptor.Artist != "" {
		return strings.TrimSpace(descriptor.Title + " " + descriptor.Artist)
	}
	if descriptor.AlbumArtist != "" {
		return strings.TrimSpace(descriptor.Title + " " + descriptor.AlbumArtist)
	}
	return strings.TrimSpace(descriptor.Title + " " + descriptor.Album)
}

func fetchCandidatesForDescriptor(descriptor nomarrSongDescriptor) ([]subsonicSong, error) {
	query := descriptorSearchQuery(descriptor)
	if query == "" {
		return nil, nil
	}
	searchEndpoint := "search3?query=" + url.QueryEscape(query) + "&songCount=200"
	searchResp, err := host.SubsonicAPICall(searchEndpoint)
	if err != nil {
		return nil, fmt.Errorf("search3 failed for descriptor %q/%q: %w", descriptor.Title, descriptor.Artist, err)
	}
	return parseSubsonicSongs(searchResp), nil
}

// ---------------------------------------------------------------------------
// Scrobble types (Nomarr API payload)
// ---------------------------------------------------------------------------

// scrobbleTrack represents a single track in a scrobble event sent to Nomarr.
type scrobbleTrack struct {
	ID       string  `json:"id"`
	Title    string  `json:"title"`
	Duration float64 `json:"duration"`
}

// scrobbleRequest is the JSON body sent to Nomarr's scrobble endpoint.
type scrobbleRequest struct {
	Username  string        `json:"username"`
	Track     scrobbleTrack `json:"track"`
	Timestamp int64         `json:"timestamp"`
}

// ---------------------------------------------------------------------------
// Playlist generation types
// ---------------------------------------------------------------------------

// userConfig represents a single user entry from the plugin's "users" config array.
type userConfig struct {
	Username          string   `json:"username"`
	EnabledTypes      []string `json:"enabled_types,omitempty"`
	MaxSongs          *int     `json:"max_songs,omitempty"`
	MinSongs          *int     `json:"min_songs,omitempty"`
	MaxGenrePlaylists *int     `json:"max_genre_playlists,omitempty"`
}

// generatePlaylistsRequest is the JSON body sent to Nomarr's generate-playlists endpoint.
type generatePlaylistsRequest struct {
	UserID            string   `json:"user_id"`
	EnabledTypes      []string `json:"enabled_types,omitempty"`
	MaxSongs          *int     `json:"max_songs,omitempty"`
	MinSongs          *int     `json:"min_songs,omitempty"`
	BackboneID        string   `json:"backbone_id,omitempty"`
	MaxGenrePlaylists *int     `json:"max_genre_playlists,omitempty"`
}

// playlistResult is a single generated playlist in Nomarr's response.
type playlistResult struct {
	PlaylistType string                 `json:"playlist_type"`
	PlaylistName string                 `json:"playlist_name"`
	Songs        []nomarrSongDescriptor `json:"songs"`
	TrackCount   int                    `json:"track_count"`
}

// generatePlaylistsResponse is the JSON response from Nomarr's generate-playlists endpoint.
type generatePlaylistsResponse struct {
	Status    string           `json:"status"`
	Message   string           `json:"message"`
	Playlists []playlistResult `json:"playlists"`
}

type descriptorResolutionResult struct {
	ResolvedIDs     []string
	UnresolvedCount int
	AmbiguousCount  int
}

// resolveDescriptorsToSongIDs resolves a list of Nomarr track descriptors to
// Navidrome song IDs using the provided candidate-fetch function.
//
// Returns:
//   - descriptorResolutionResult: named counters and resolved song IDs
//   - error: fetch error from the candidate source
func resolveDescriptorsToSongIDs(
	descriptors []nomarrSongDescriptor,
	fetchCandidates func(nomarrSongDescriptor) ([]subsonicSong, error),
) (descriptorResolutionResult, error) {
	result := descriptorResolutionResult{
		ResolvedIDs: make([]string, 0, len(descriptors)),
	}

	resolvedIDs := make([]string, 0, len(descriptors))
	unresolvedCount := 0
	ambiguousCount := 0

	for _, descriptor := range descriptors {
		candidates, err := fetchCandidates(descriptor)
		if err != nil {
			return result, err
		}
		if len(candidates) == 0 {
			unresolvedCount++
			continue
		}

		candidate, status := resolveDescriptorAgainstCandidates(descriptor, candidates)
		if status == "descriptor_unresolved" {
			unresolvedCount++
			continue
		}
		if status == "descriptor_ambiguous" {
			ambiguousCount++
			continue
		}
		resolvedIDs = append(resolvedIDs, candidate.ID)
	}

	result.ResolvedIDs = resolvedIDs
	result.UnresolvedCount = unresolvedCount
	result.AmbiguousCount = ambiguousCount
	return result, nil
}

// ---------------------------------------------------------------------------
// SimilarSongsByTrackProvider implementation
// ---------------------------------------------------------------------------

// GetSimilarSongsByTrack returns tracks similar to the given track by querying
// Nomarr's similarity API. On any error, it returns an empty response so
// Navidrome can fall back to other agents (Last.fm, ListenBrainz, etc.).
func (p *nomarrPlugin) GetSimilarSongsByTrack(req metadata.SimilarSongsByTrackRequest) (*metadata.SimilarSongsResponse, error) {
	empty := &metadata.SimilarSongsResponse{}

	// Read shared config.
	nomarrURL, apiKey, ok := readConfig()
	if !ok {
		return empty, nil
	}

	backbone, found := pdk.GetConfig("backbone_id")
	if !found || backbone == "" {
		backbone = "effnet"
	}

	// Build the request to Nomarr's similarity endpoint.
	count := req.Count
	if count <= 0 {
		count = 50
	}

	seedResp, err := host.SubsonicAPICall("getSong?id=" + url.QueryEscape(req.ID))
	if err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: nomarr_unreachable failed to load seed song %s: %v", req.ID, err))
		return empty, fmt.Errorf("nomarr_unreachable")
	}
	seedSongs := parseSubsonicSongs(seedResp)
	if len(seedSongs) == 0 {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: descriptor_unresolved seed song %s not found via getSong", req.ID))
		return empty, fmt.Errorf("descriptor_unresolved")
	}
	seedSong := seedSongs[0]

	reqBody := nomarrRequest{
		Seed: nomarrSongDescriptor{
			Title:       seedSong.Title,
			Artist:      seedSong.Artist,
			Album:       seedSong.Album,
			AlbumArtist: seedSong.AlbumArtist,
			DurationMs:  seedSong.DurationMs,
			TrackNumber: seedSong.TrackNumber,
			DiscNumber:  seedSong.DiscNumber,
			Year:        seedSong.Year,
		},
		Count:      count,
		BackboneID: backbone,
	}
	bodyBytes, err := json.Marshal(reqBody)
	if err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to marshal request: %v", err))
		return empty, nil
	}

	endpoint := strings.TrimRight(nomarrURL, "/") + "/api/v1/navidrome/similar-track"

	pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: querying %s for song %s (count=%d, backbone=%s)", endpoint, req.ID, count, backbone))
	pdk.Log(pdk.LogDebug, fmt.Sprintf("nomarr: similar-track request body: %s", string(bodyBytes)))

	// Send HTTP POST via Navidrome host HTTP service.
	resp, err := host.HTTPSend(host.HTTPRequest{
		Method: "POST",
		URL:    endpoint,
		Headers: map[string]string{
			"Content-Type": "application/json",
			"X-API-Key":    apiKey,
		},
		Body:      bodyBytes,
		TimeoutMs: 30000,
	})
	if err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: nomarr_unreachable HTTP request failed: %v", err))
		return empty, fmt.Errorf("nomarr_unreachable")
	}

	// Check HTTP status.
	if resp.StatusCode != 200 {
		pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: API returned status %d: %s", resp.StatusCode, string(resp.Body)))
		return empty, fmt.Errorf("nomarr_unreachable")
	}

	// Parse Nomarr response.
	var nomarrResp nomarrResponse
	if err := json.Unmarshal(resp.Body, &nomarrResp); err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to parse response: %v", err))
		return empty, fmt.Errorf("nomarr_unreachable")
	}
	if len(nomarrResp.Songs) == 0 {
		pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: nomarr_no_results for seed %s", req.ID))
		return empty, fmt.Errorf("nomarr_no_results")
	}

	resolvedCount := 0
	unresolvedCount := 0
	ambiguousCount := 0

	// Resolve Nomarr descriptors to Navidrome SongRef IDs.
	songs := make([]metadata.SongRef, 0, len(nomarrResp.Songs))
	for _, descriptor := range nomarrResp.Songs {
		candidates, err := fetchCandidatesForDescriptor(descriptor)
		if err != nil {
			pdk.Log(
				pdk.LogError,
				fmt.Sprintf(
					"nomarr: nomarr_unreachable search3 failed for descriptor %q/%q: %v",
					descriptor.Title,
					descriptor.Artist,
					err,
				),
			)
			return empty, fmt.Errorf("nomarr_unreachable")
		}
		if len(candidates) == 0 {
			unresolvedCount++
			continue
		}

		candidate, status := resolveDescriptorAgainstCandidates(descriptor, candidates)
		if status == "descriptor_unresolved" {
			unresolvedCount++
			continue
		}
		if status == "descriptor_ambiguous" {
			ambiguousCount++
			continue
		}
		songs = append(songs, metadata.SongRef{
			ID:     candidate.ID,
			Name:   candidate.Title,
			Artist: candidate.Artist,
			Album:  candidate.Album,
		})
		resolvedCount++
	}
	if resolvedCount == 0 {
		pdk.Log(
			pdk.LogError,
			fmt.Sprintf(
				"nomarr: insufficient_resolved_results resolved=0 unresolved=%d ambiguous=%d",
				unresolvedCount,
				ambiguousCount,
			),
		)
		return empty, fmt.Errorf("insufficient_resolved_results")
	}

	pdk.Log(
		pdk.LogInfo,
		fmt.Sprintf(
			"nomarr: found %d similar tracks for song %s (resolved=%d unresolved=%d ambiguous=%d)",
			len(songs),
			req.ID,
			resolvedCount,
			unresolvedCount,
			ambiguousCount,
		),
	)

	return &metadata.SimilarSongsResponse{Songs: songs}, nil
}

// ---------------------------------------------------------------------------
// Scrobbler implementation
// ---------------------------------------------------------------------------

// IsAuthorized always returns true — Nomarr accepts all scrobbles from
// configured users. Auth is handled via the API key, not per-user.
func (p *nomarrPlugin) IsAuthorized(_ scrobbler.IsAuthorizedRequest) (bool, error) {
	_, _, ok := readConfig()
	if !ok {
		return false, nil
	}
	return true, nil
}

// NowPlaying is a no-op. Nomarr only needs completed scrobbles, not
// now-playing notifications.
func (p *nomarrPlugin) NowPlaying(_ scrobbler.NowPlayingRequest) error {
	return nil
}

// Scrobble forwards a scrobble event to Nomarr's ingestion API.
// Best-effort: on any error, logs and returns nil so the scrobble pipeline
// in Navidrome is never blocked.
func (p *nomarrPlugin) Scrobble(req scrobbler.ScrobbleRequest) error {
	nomarrURL, apiKey, ok := readConfig()
	if !ok {
		return nil
	}

	body := scrobbleRequest{
		Username: req.Username,
		Track: scrobbleTrack{
			ID:       req.Track.ID,
			Title:    req.Track.Title,
			Duration: float64(req.Track.Duration),
		},
		Timestamp: req.Timestamp,
	}
	bodyBytes, err := json.Marshal(body)
	if err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to marshal scrobble request: %v", err))
		return nil
	}

	endpoint := strings.TrimRight(nomarrURL, "/") + "/api/v1/navidrome/scrobble"

	pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: scrobbling track %s (%s) for user %s", req.Track.ID, req.Track.Title, req.Username))
	pdk.Log(pdk.LogDebug, fmt.Sprintf("nomarr: scrobble request body: %s", string(bodyBytes)))

	resp, err := host.HTTPSend(host.HTTPRequest{
		Method: "POST",
		URL:    endpoint,
		Headers: map[string]string{
			"Content-Type": "application/json",
			"X-API-Key":    apiKey,
		},
		Body:      bodyBytes,
		TimeoutMs: 10000,
	})
	if err != nil {
		pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: scrobble HTTP request failed: %v", err))
		return nil
	}

	if resp.StatusCode != 204 && resp.StatusCode != 200 {
		pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: scrobble API returned status %d: %s", resp.StatusCode, string(resp.Body)))
	}

	return nil
}

// ---------------------------------------------------------------------------
// Scheduler callback implementation
// ---------------------------------------------------------------------------

// OnCallback handles scheduled task callbacks. Dispatches by schedule ID.
func (p *nomarrPlugin) OnCallback(req scheduler.SchedulerCallbackRequest) error {
	if req.ScheduleID == "nomarr-playlist-gen" {
		generateAndPushPlaylists()
	} else {
		pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: unknown schedule callback: %s", req.ScheduleID))
	}
	return nil
}

// ---------------------------------------------------------------------------
// Playlist generation
// ---------------------------------------------------------------------------

// generateAndPushPlaylists calls Nomarr's generate-playlists API for each
// configured user and pushes the resulting playlists into Navidrome via the
// Subsonic createPlaylist API. Users are read from the "users" config key as a
// JSON array of userConfig objects. If a user fails at any step, the error is
// logged and iteration continues with the next user (error isolation).
func generateAndPushPlaylists() {
	nomarrURL, apiKey, ok := readConfig()
	if !ok {
		return
	}

	// Read and parse the users config array.
	usersJSON, ok := pdk.GetConfig("users")
	if !ok || usersJSON == "" {
		pdk.Log(pdk.LogWarn, "nomarr: no users configured, skipping playlist generation")
		return
	}

	var users []userConfig
	if err := json.Unmarshal([]byte(usersJSON), &users); err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to parse users config: %v", err))
		return
	}

	if len(users) == 0 {
		pdk.Log(pdk.LogWarn, "nomarr: users array is empty, skipping playlist generation")
		return
	}

	endpoint := strings.TrimRight(nomarrURL, "/") + "/api/v1/navidrome/playlist/generate"

	for _, user := range users {
		if user.Username == "" {
			pdk.Log(pdk.LogWarn, "nomarr: skipping user entry with empty username")
			continue
		}

		pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: requesting playlist generation for user %s", user.Username))

		// Build per-user request — only include optional fields when set.
		reqBody := generatePlaylistsRequest{
			UserID:            user.Username,
			EnabledTypes:      user.EnabledTypes,
			MaxSongs:          user.MaxSongs,
			MinSongs:          user.MinSongs,
			MaxGenrePlaylists: user.MaxGenrePlaylists,
		}

		bodyBytes, err := json.Marshal(reqBody)
		if err != nil {
			pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to marshal request for user %s: %v", user.Username, err))
			continue
		}

		pdk.Log(pdk.LogDebug, fmt.Sprintf("nomarr: generate-playlists request body for user %s: %s", user.Username, string(bodyBytes)))

		resp, err := host.HTTPSend(host.HTTPRequest{
			Method: "POST",
			URL:    endpoint,
			Headers: map[string]string{
				"Content-Type": "application/json",
				"X-API-Key":    apiKey,
			},
			Body:      bodyBytes,
			TimeoutMs: 60000,
		})
		if err != nil {
			pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: generate-playlists HTTP request failed for user %s: %v", user.Username, err))
			continue
		}

		pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: generate-playlists API responded with status %d for user %s", resp.StatusCode, user.Username))

		if resp.StatusCode != 200 {
			pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: generate-playlists API returned status %d for user %s: %s", resp.StatusCode, user.Username, string(resp.Body)))
			continue
		}

		var genResp generatePlaylistsResponse
		if err := json.Unmarshal(resp.Body, &genResp); err != nil {
			pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to parse generate-playlists response for user %s: %v", user.Username, err))
			continue
		}

		pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: received %d playlists for user %s", len(genResp.Playlists), user.Username))

		switch genResp.Status {
		case "no_data":
			pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: no playlists generated for user %s (no_data)", user.Username))
			continue
		case "misconfigured":
			pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: misconfigured for user %s: %s", user.Username, genResp.Message))
			continue
		}

		// Fetch existing playlists to determine create vs. update.
		existingPlaylists := findExistingPlaylists(user.Username)
		var created, updated, skippedEmpty int

		// Push each playlist into Navidrome via Subsonic createPlaylist API.
		for _, pl := range genResp.Playlists {
			resolution, err := resolveDescriptorsToSongIDs(
				pl.Songs,
				fetchCandidatesForDescriptor,
			)
			if err != nil {
				pdk.Log(
					pdk.LogError,
					fmt.Sprintf(
						"nomarr: nomarr_unreachable search3 failed while resolving playlist %q for user %s: %v",
						pl.PlaylistName,
						user.Username,
						err,
					),
				)
				continue
			}

			if len(resolution.ResolvedIDs) == 0 {
				pdk.Log(
					pdk.LogWarn,
					fmt.Sprintf(
						"nomarr: skipping empty playlist %q for user %s after descriptor resolution (unresolved=%d ambiguous=%d)",
						pl.PlaylistName,
						user.Username,
						resolution.UnresolvedCount,
						resolution.AmbiguousCount,
					),
				)
				skippedEmpty++
				continue
			}

			var uri string
			var action string

			if playlistID, exists := existingPlaylists[pl.PlaylistName]; exists {
				// Playlist exists — update it by ID.
				uri = "createPlaylist?playlistId=" + url.QueryEscape(playlistID)
				action = "update"
			} else {
				// New playlist — create by name.
				uri = "createPlaylist?name=" + url.QueryEscape(pl.PlaylistName)
				action = "create"
			}

			for _, songID := range resolution.ResolvedIDs {
				uri += "&songId=" + url.QueryEscape(songID)
			}

			if _, err := subsonicCallAs(uri, user.Username); err != nil {
				pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to %s playlist %q for user %s: %v", action, pl.PlaylistName, user.Username, err))
				continue
			}

			if action == "create" {
				created++
			} else if action == "update" {
				updated++
			}

			pdk.Log(
				pdk.LogInfo,
				fmt.Sprintf(
					"nomarr: %s playlist %q (%s, %d/%d tracks resolved, unresolved=%d ambiguous=%d) for user %s",
					action,
					pl.PlaylistName,
					pl.PlaylistType,
					len(resolution.ResolvedIDs),
					len(pl.Songs),
					resolution.UnresolvedCount,
					resolution.AmbiguousCount,
					user.Username,
				),
			)
		}

		pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: playlists for user %s: %d created, %d updated, %d skipped (empty)", user.Username, created, updated, skippedEmpty))
	}
}

func main() {}
