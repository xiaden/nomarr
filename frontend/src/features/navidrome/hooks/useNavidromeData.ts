/**
 * Custom hook for Navidrome integration data and actions.
 * Handles config generation and playlist generation.
 */

import { useRef, useState } from "react";

import { useNotification } from "../../../hooks/useNotification";
import {
    generatePlaylist as apiGeneratePlaylist,
    previewPlaylist as apiPreviewPlaylist,
    getConfig,
    getPreview,
    type PlaylistPreviewResponse,
} from "../../../shared/api/navidrome";
import {
  buildQueryString,
  createRule,
  createRuleGroup,
  validateGroupDepth,
  type RuleGroup,
} from "../components/ruleUtils";

interface TagPreview {
  tag_key: string;
  type: string;
  is_multivalue: boolean;
  summary: string;
  total_count: number;
  short_name: string;
  field_name: string;
  is_versioned: boolean;
}

export function useNavidromeData() {
  const { showError } = useNotification();

  // Config state
  const [configPreview, setConfigPreview] = useState<TagPreview[] | null>(null);
  const [configText, setConfigText] = useState<string | null>(null);
  const [configLoading, setConfigLoading] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);

  // Playlist state — structured rule groups instead of flat rules
  const [playlistRootGroup, setPlaylistRootGroup] = useState<RuleGroup>(() => {
    const rootGroup = createRuleGroup("all");
    rootGroup.rules = [createRule()];
    return rootGroup;
  });
  const [playlistName, setPlaylistName] = useState("My Playlist");
  const [playlistComment, setPlaylistComment] = useState("");
  const [playlistLimit, setPlaylistLimit] = useState<number | undefined>(undefined);
  const [playlistSort, setPlaylistSort] = useState("");
  const [playlistPreview, setPlaylistPreview] = useState<PlaylistPreviewResponse | null>(null);
  const [playlistContent, setPlaylistContent] = useState<string | null>(null);
  const [playlistLoading, setPlaylistLoading] = useState(false);
  const [playlistError, setPlaylistError] = useState<string | null>(null);
  const playlistRequestVersion = useRef(0);

  const invalidatePlaylistResults = () => {
    playlistRequestVersion.current += 1;
    setPlaylistPreview(null);
    setPlaylistContent(null);
  };

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
  const previewPlaylist = async () => {
    const depthError = validateGroupDepth(playlistRootGroup);
    if (depthError) {
      showError(depthError);
      return;
    }
    const query = buildQueryString(playlistRootGroup);
    if (!query.trim()) {
      showError("Add at least one complete rule");
      return;
    }

    try {
      setPlaylistLoading(true);
      setPlaylistError(null);
      const requestVersion = playlistRequestVersion.current;
      const data = await apiPreviewPlaylist(query, 10);
      if (requestVersion === playlistRequestVersion.current) {
        setPlaylistPreview(data);
      }
    } catch (err) {
      setPlaylistError(err instanceof Error ? err.message : "Failed to preview playlist");
    } finally {
      setPlaylistLoading(false);
    }
  };

  const generatePlaylist = async () => {
    const depthError = validateGroupDepth(playlistRootGroup);
    if (depthError) {
      showError(depthError);
      return;
    }
    const query = buildQueryString(playlistRootGroup);
    if (!query.trim()) {
      showError("Add at least one complete rule");
      return;
    }
    if (!playlistName.trim()) {
      showError("Playlist name is required");
      return;
    }

    try {
      setPlaylistLoading(true);
      setPlaylistError(null);
      const requestVersion = playlistRequestVersion.current;
      const data = await apiGeneratePlaylist({
        query,
        playlist_name: playlistName,
        comment: playlistComment,
        limit: playlistLimit,
        sort: playlistSort || undefined,
      });
      if (requestVersion === playlistRequestVersion.current) {
        setPlaylistContent(data.content);
      }
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
    playlistRootGroup,
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
    setPlaylistRootGroup: (group: RuleGroup) => {
      invalidatePlaylistResults();
      setPlaylistRootGroup(group);
    },
    setPlaylistName: (name: string) => {
      invalidatePlaylistResults();
      setPlaylistName(name);
    },
    setPlaylistComment: (comment: string) => {
      invalidatePlaylistResults();
      setPlaylistComment(comment);
    },
    setPlaylistLimit: (limit: number | undefined) => {
      invalidatePlaylistResults();
      setPlaylistLimit(limit);
    },
    setPlaylistSort: (sort: string) => {
      invalidatePlaylistResults();
      setPlaylistSort(sort);
    },
  };
}
