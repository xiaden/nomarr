/**
 * Navidrome integration page.
 *
 * Features:
 * - Generate Navidrome TOML configuration
 * - Build and generate Smart Playlist (.nsp) files
 */

import { ExpandMore } from "@mui/icons-material";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Stack,
  Typography,
} from "@mui/material";

import { PageContainer } from "@shared/components/ui";

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

  return (
    <PageContainer title="Navidrome">
      <Stack spacing={2}>
        {/* Generate Config accordion */}
        <Accordion defaultExpanded disableGutters>
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
          </AccordionDetails>
        </Accordion>
      </Stack>
    </PageContainer>
  );
}
