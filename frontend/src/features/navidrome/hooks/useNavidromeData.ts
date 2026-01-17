/**
 * Custom hook for Navidrome integration data and actions.
 * Handles config generation and playlist generation.
 */

import { useState } from "react";

import { useNotification } from "../../../hooks/useNotification";
import {
    generatePlaylist as apiGeneratePlaylist,
    previewPlaylist as apiPreviewPlaylist,
    getConfig,
    getPreview,
} from "../../../shared/api/navidrome";

interface TagPreview {
  tag_key: string;
  type: string;
  is_multivalue: boolean;
  summary: string;
  total_count: number;
}

export function useNavidromeData() {
  const { showError } = useNotification();

  // Config state
  const [configPreview, setConfigPreview] = useState<TagPreview[] | null>(null);
  const [configText, setConfigText] = useState<string | null>(null);
  const [configLoading, setConfigLoading] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);

  // Playlist state
  const [playlistQuery, setPlaylistQuery] = useState("");
  const [playlistName, setPlaylistName] = useState("My Playlist");
  const [playlistComment, setPlaylistComment] = useState("");
  const [playlistLimit, setPlaylistLimit] = useState<number | undefined>(undefined);
  const [playlistSort, setPlaylistSort] = useState("");
  const [playlistPreview, setPlaylistPreview] = useState<Record<string, unknown> | null>(null);
  const [playlistContent, setPlaylistContent] = useState<string | null>(null);
  const [playlistLoading, setPlaylistLoading] = useState(false);
  const [playlistError, setPlaylistError] = useState<string | null>(null);

  // Config actions
  const loadConfigPreview = async () => {
    try {
      setConfigLoading(true);
      setConfigError(null);
      const data = await getPreview();
      setConfigPreview(data.tags);
    } catch (err) {
      setConfigError(err instanceof Error ? err.message : "Failed to load preview");
    } finally {
      setConfigLoading(false);
    }
  };

  const generateConfig = async () => {
    try {
      setConfigLoading(true);
      setConfigError(null);
      const data = await getConfig();
      setConfigText(data.config);
    } catch (err) {
      setConfigError(err instanceof Error ? err.message : "Failed to generate config");
    } finally {
      setConfigLoading(false);
    }
  };

  // Playlist actions
  const previewPlaylist = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!playlistQuery.trim()) return;

    try {
      setPlaylistLoading(true);
      setPlaylistError(null);
      const data = await apiPreviewPlaylist(playlistQuery, 10);
      setPlaylistPreview(data);
    } catch (err) {
      setPlaylistError(err instanceof Error ? err.message : "Failed to preview playlist");
    } finally {
      setPlaylistLoading(false);
    }
  };

  const generatePlaylist = async () => {
    if (!playlistQuery.trim()) {
      showError("Query is required");
      return;
    }
    if (!playlistName.trim()) {
      showError("Playlist name is required");
      return;
    }

    try {
      setPlaylistLoading(true);
      setPlaylistError(null);
      const data = await apiGeneratePlaylist({
        query: playlistQuery,
        playlist_name: playlistName,
        comment: playlistComment,
        limit: playlistLimit,
        sort: playlistSort || undefined,
      });
      setPlaylistContent(data.content);
    } catch (err) {
      setPlaylistError(err instanceof Error ? err.message : "Failed to generate playlist");
    } finally {
      setPlaylistLoading(false);
    }
  };

  return {
    // Config state
    configPreview,
    configText,
    configLoading,
    configError,
    // Playlist state
    playlistQuery,
    playlistName,
    playlistComment,
    playlistLimit,
    playlistSort,
    playlistPreview,
    playlistContent,
    playlistLoading,
    playlistError,
    // Config actions
    loadConfigPreview,
    generateConfig,
    // Playlist actions
    previewPlaylist,
    generatePlaylist,
    setPlaylistQuery,
    setPlaylistName,
    setPlaylistComment,
    setPlaylistLimit,
    setPlaylistSort,
  };
}
