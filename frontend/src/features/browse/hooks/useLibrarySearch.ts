/**
 * useLibrarySearch - Hook for fuzzy library search with grouped results.
 *
 * Wraps the files `search()` API and groups results into categories:
 * - Artists: tracks grouped by artist name
 * - Albums: tracks grouped by album name
 * - Tracks: flat list of all matching tracks
 *
 * Includes 300ms debouncing so it can be driven directly by input changes.
 *
 * Supports field-specific prefix syntax to narrow results:
 *   a:term   - filter by artist name
 *   al:term  - filter by album name
 *   t:term   - filter by track title
 * Unprefixed words search across all fields (general `q`).
 * Prefixes can be mixed: "a:good charlotte t:change"
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { LibraryFile, SearchFilesParams } from "@shared/api/files";
import { search } from "@shared/api/files";

export interface GroupedSearchResults {
  /** Tracks grouped by artist name. Key = artist display name. */
  artists: Map<string, LibraryFile[]>;
  /** Tracks grouped by album name. Key = album display name. */
  albums: Map<string, LibraryFile[]>;
  /** Flat list of all matching tracks. */
  tracks: LibraryFile[];
}

export interface UseLibrarySearchResult {
  /** Grouped search results, null if no search performed yet. */
  results: GroupedSearchResults | null;
  /** Whether a search request is in flight. */
  loading: boolean;
  /** Error message if the last search failed. */
  error: string | null;
  /** The query string currently being searched (after debounce). */
  activeQuery: string;
}

/** Known field prefixes and their SearchFilesParams keys. */
const FIELD_PREFIXES: ReadonlyArray<{ prefix: string; key: keyof SearchFilesParams }> = [
  { prefix: "al:", key: "album" },   // Must come before "a:" to avoid partial match
  { prefix: "a:", key: "artist" },
  { prefix: "t:", key: "q" },         // Track title maps to general query
];

/**
 * Parse a search query string that may contain field-specific prefixes.
 *
 * Syntax:  `a:Artist Term  al:Album Term  t:Track Term  general words`
 *
 * Each prefix captures all text until the next known prefix or end-of-string.
 * Any text not preceded by a prefix goes into the general `q` field.
 *
 * @returns A `SearchFilesParams` with populated field filters.
 */
export function parseSearchQuery(raw: string): Omit<SearchFilesParams, "limit" | "offset"> {
  const trimmed = raw.trim();
  if (!trimmed) return {};

  // Build a regex that splits on any known prefix boundary.
  const prefixPattern = FIELD_PREFIXES.map((p) => p.prefix.replace(":", "\\:")).join("|");
  // Split while keeping the delimiter: e.g. ["free text ", "a:good char ", "t:change"]
  const parts = trimmed.split(new RegExp(`(?=${prefixPattern})`, "i"));

  const result: Record<string, string> = {};

  for (const part of parts) {
    const segment = part.trim();
    if (!segment) continue;

    let matched = false;
    for (const { prefix, key } of FIELD_PREFIXES) {
      if (segment.toLowerCase().startsWith(prefix)) {
        const value = segment.slice(prefix.length).trim();
        if (value) {
          // Append if multiple segments target the same field (rare but possible)
          result[key] = result[key] ? `${result[key]} ${value}` : value;
        }
        matched = true;
        break;
      }
    }

    if (!matched) {
      // Unprefixed text → general query
      result.q = result.q ? `${result.q} ${segment}` : segment;
    }
  }

  return result;
}

/**
 * Group an array of LibraryFile results by artist and album.
 */
function groupResults(files: LibraryFile[]): GroupedSearchResults {
  const artists = new Map<string, LibraryFile[]>();
  const albums = new Map<string, LibraryFile[]>();

  for (const file of files) {
    const artistName = file.artist || "Unknown Artist";
    const albumName = file.album || "Unknown Album";

    // Group by artist
    const artistGroup = artists.get(artistName);
    if (artistGroup) {
      artistGroup.push(file);
    } else {
      artists.set(artistName, [file]);
    }

    // Group by album
    const albumGroup = albums.get(albumName);
    if (albumGroup) {
      albumGroup.push(file);
    } else {
      albums.set(albumName, [file]);
    }
  }

  return { artists, albums, tracks: files };
}

/**
 * Hook for debounced library search with grouped results.
 *
 * @param query - The search query string. Changes are debounced by 300ms.
 * @param limit - Maximum number of results to fetch (default 200).
 * @returns Grouped search results, loading state, and error state.
 */
export function useLibrarySearch(
  query: string,
  limit = 200,
): UseLibrarySearchResult {
  const [results, setResults] = useState<GroupedSearchResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeQuery, setActiveQuery] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController>(null);

  const executeSearch = useCallback(
    async (q: string) => {
      // Cancel any in-flight request
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      if (!q.trim()) {
        setResults(null);
        setActiveQuery("");
        setLoading(false);
        setError(null);
        return;
      }

      setLoading(true);
      setError(null);
      setActiveQuery(q.trim());

      try {
        const params = parseSearchQuery(q);
        const response = await search({ ...params, limit });

        // Check if this request was superseded
        if (controller.signal.aborted) return;

        setResults(groupResults(response.files));
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(
          err instanceof Error ? err.message : "Search failed",
        );
        setResults(null);
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    },
    [limit],
  );

  // Debounce query changes by 300ms
  useEffect(() => {
    if (debounceRef.current !== null) clearTimeout(debounceRef.current);

    if (!query.trim()) {
      // Clear immediately when query is emptied
      setResults(null);
      setActiveQuery("");
      setLoading(false);
      setError(null);
      return;
    }

    setLoading(true); // Show loading immediately for responsiveness
    debounceRef.current = setTimeout(() => {
      executeSearch(query);
    }, 500);

    return () => {
      if (debounceRef.current !== null) clearTimeout(debounceRef.current);
    };
  }, [query, executeSearch]);

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  return useMemo(
    () => ({ results, loading, error, activeQuery }),
    [results, loading, error, activeQuery],
  );
}
