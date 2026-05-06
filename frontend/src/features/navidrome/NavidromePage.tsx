/**
 * Navidrome integration page.
 *
 * Features:
 * - API settings (first)
 * - Generate Navidrome TOML configuration
 * - Build and generate Smart Playlist (.nsp) files
 * - Trigger personal playlist generation
 */

import { ExpandMore } from "@mui/icons-material";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  CircularProgress,
  Divider,
  Stack,
  Typography,
} from "@mui/material";
import React from "react";

import { triggerPersonalPlaylists, type TriggerPersonalPlaylistsResponse } from "@shared/api/navidrome";
import { PageContainer } from "@shared/components/ui";

import { ApiSettingsPanel } from "./components/ApiSettingsPanel";
import { ConfigTab } from "./components/ConfigTab";
import { PlaylistTab } from "./components/PlaylistTab";
import { useNavidromeData } from "./hooks/useNavidromeData";

export function NavidromePage() {
  const {
    configPreview,
    configText,
    configLoading,
    configError,
    playlistRootGroup,
    playlistName,
    playlistComment,
    playlistLimit,
    playlistSort,
    playlistPreview,
    playlistContent,
    playlistLoading,
    playlistError,
    loadConfigPreview,
    generateConfig,
    previewPlaylist,
    generatePlaylist,
    setPlaylistRootGroup,
    setPlaylistName,
    setPlaylistComment,
    setPlaylistLimit,
    setPlaylistSort,
  } = useNavidromeData();

  const [personalPlaylistsLoading, setPersonalPlaylistsLoading] = React.useState(false);
  const [personalPlaylistsResult, setPersonalPlaylistsResult] = React.useState<TriggerPersonalPlaylistsResponse | null>(null);
  const [personalPlaylistsError, setPersonalPlaylistsError] = React.useState<string | null>(null);

  const handleTriggerPersonalPlaylists = async () => {
    try {
      setPersonalPlaylistsLoading(true);
      setPersonalPlaylistsResult(null);
      setPersonalPlaylistsError(null);
      const result = await triggerPersonalPlaylists();
      setPersonalPlaylistsResult(result);
    } catch (err) {
      setPersonalPlaylistsError(err instanceof Error ? err.message : "Failed to generate playlists");
    } finally {
      setPersonalPlaylistsLoading(false);
    }
  };

  return (
    <PageContainer title="Navidrome">
      <Stack spacing={2}>
        {/* API Settings accordion — first */}
        <Accordion defaultExpanded disableGutters>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Typography variant="h6" sx={{ fontWeight: 600 }}>
              API Settings
            </Typography>
          </AccordionSummary>
          <AccordionDetails>
            <ApiSettingsPanel />
          </AccordionDetails>
        </Accordion>

        {/* Generate Config accordion */}
        <Accordion disableGutters>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Typography variant="h6" sx={{ fontWeight: 600 }}>
              Generate Config
            </Typography>
          </AccordionSummary>
          <AccordionDetails>
            <ConfigTab
              preview={configPreview}
              configText={configText}
              loading={configLoading}
              error={configError}
              onLoadPreview={loadConfigPreview}
              onGenerateConfig={generateConfig}
            />
          </AccordionDetails>
        </Accordion>

        {/* Playlist Maker accordion */}
        <Accordion disableGutters>
          <AccordionSummary expandIcon={<ExpandMore />}>
            <Typography variant="h6" sx={{ fontWeight: 600 }}>
              Playlist Maker
            </Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Stack spacing={2.5}>
              <PlaylistTab
                rootGroup={playlistRootGroup}
                name={playlistName}
                comment={playlistComment}
                limit={playlistLimit}
                sort={playlistSort}
                preview={playlistPreview}
                content={playlistContent}
                loading={playlistLoading}
                error={playlistError}
                onGroupChange={setPlaylistRootGroup}
                onNameChange={setPlaylistName}
                onCommentChange={setPlaylistComment}
                onLimitChange={setPlaylistLimit}
                onSortChange={setPlaylistSort}
                onPreview={previewPlaylist}
                onGenerate={generatePlaylist}
              />

              <Divider />

              {/* Personal playlists trigger */}
              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 0.5 }}>
                  Personal Playlists
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                  Generate taste-based playlists (Familiar, Discovery, Hidden Gems, Genre, Universal) for the configured Navidrome user and push them to Navidrome immediately.
                </Typography>
                <Button
                  variant="outlined"
                  onClick={() => void handleTriggerPersonalPlaylists()}
                  disabled={personalPlaylistsLoading}
                  startIcon={personalPlaylistsLoading ? <CircularProgress size={16} /> : undefined}
                >
                  {personalPlaylistsLoading ? "Generating…" : "Generate Now"}
                </Button>
                {personalPlaylistsResult && (
                  <Alert severity={personalPlaylistsResult.status === "ok" ? "success" : "info"} sx={{ mt: 1.5 }}>
                    {personalPlaylistsResult.status === "ok"
                      ? `Generated ${personalPlaylistsResult.playlists_generated} playlist(s), pushed ${personalPlaylistsResult.playlists_pushed} to Navidrome.`
                      : personalPlaylistsResult.message || "No playlists generated — not enough play history yet."}
                  </Alert>
                )}
                {personalPlaylistsError && (
                  <Alert severity="error" sx={{ mt: 1.5 }}>
                    {personalPlaylistsError}
                  </Alert>
                )}
              </Box>
            </Stack>
          </AccordionDetails>
        </Accordion>
      </Stack>
    </PageContainer>
  );
}

