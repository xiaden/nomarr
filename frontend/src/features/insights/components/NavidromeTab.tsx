/**
 * Navidrome integration tab - config and playlist generation.
 */

import { useState } from "react";

import { TabNav } from "@shared/components/ui";

import { ConfigTab } from "../../navidrome/components/ConfigTab";
import { PlaylistTab } from "../../navidrome/components/PlaylistTab";
import { useNavidromeData } from "../../navidrome/hooks/useNavidromeData";

export function NavidromeTab() {
  const [activeSubTab, setActiveSubTab] = useState<"config" | "playlist">("config");
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
    <>
      <TabNav
        tabs={[
          { id: "config", label: "Config Generator" },
          { id: "playlist", label: "Playlist Generator" },
        ]}
        activeTab={activeSubTab}
        onTabChange={(id) => setActiveSubTab(id as "config" | "playlist")}
      />

      {/* Sub-tab Content */}
      {activeSubTab === "config" && (
        <ConfigTab
          preview={configPreview}
          configText={configText}
          loading={configLoading}
          error={configError}
          onLoadPreview={loadConfigPreview}
          onGenerateConfig={generateConfig}
        />
      )}

      {activeSubTab === "playlist" && (
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
    </>
  );
}