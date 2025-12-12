/**
 * Navidrome integration page.
 *
 * Features:
 * - Preview tags for Navidrome config
 * - Generate Navidrome TOML configuration
 * - Preview Smart Playlist queries
 * - Generate Smart Playlist (.nsp) files
 */

import { useState } from "react";

import { PageContainer, TabNav } from "@shared/components/ui";

import { ConfigTab } from "./components/ConfigTab";
import { PlaylistTab } from "./components/PlaylistTab";
import { useNavidromeData } from "./hooks/useNavidromeData";

export function NavidromePage() {
  const [activeTab, setActiveTab] = useState<"config" | "playlist">("config");
  const {
    configPreview,
    configText,
    configLoading,
    configError,
    playlistQuery,
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
    setPlaylistQuery,
    setPlaylistName,
    setPlaylistComment,
    setPlaylistLimit,
    setPlaylistSort,
  } = useNavidromeData();

  return (
    <PageContainer title="Navidrome Integration">
      <TabNav
        tabs={[
          { id: "config", label: "Config Generator" },
          { id: "playlist", label: "Playlist Generator" },
        ]}
        activeTab={activeTab}
        onTabChange={(id) => setActiveTab(id as "config" | "playlist")}
      />

      {/* Tab Content */}
      {activeTab === "config" && (
        <ConfigTab
          preview={configPreview}
          configText={configText}
          loading={configLoading}
          error={configError}
          onLoadPreview={loadConfigPreview}
          onGenerateConfig={generateConfig}
        />
      )}

      {activeTab === "playlist" && (
        <PlaylistTab
          query={playlistQuery}
          name={playlistName}
          comment={playlistComment}
          limit={playlistLimit}
          sort={playlistSort}
          preview={playlistPreview}
          content={playlistContent}
          loading={playlistLoading}
          error={playlistError}
          onQueryChange={setPlaylistQuery}
          onNameChange={setPlaylistName}
          onCommentChange={setPlaylistComment}
          onLimitChange={setPlaylistLimit}
          onSortChange={setPlaylistSort}
          onPreview={previewPlaylist}
          onGenerate={generatePlaylist}
        />
      )}
    </PageContainer>
  );
}
