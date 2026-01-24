/**
 * BrowsePage - Hierarchical music library browser
 *
 * Features:
 * - Library tab: Hierarchical Artist → Album → Track → Tag → Tag-search
 * - Flat entity tabs (Artists/Albums/Genres/Years) for direct browsing
 * - Tag-based exploration (exact string match, closest for numbers)
 */

import { Box, Tab, Tabs } from "@mui/material";
import { useState } from "react";

import { PageContainer } from "@shared/components/ui";

import type { EntityCollection } from "../../shared/types";

import { EntityBrowser } from "./components/EntityBrowser";
import { LibraryBrowser } from "./components/LibraryBrowser";

type BrowseTab = "library" | EntityCollection;

export function BrowsePage() {
  const [activeTab, setActiveTab] = useState<BrowseTab>("library");

  return (
    <PageContainer title="Browse Music">
      <Box sx={{ borderBottom: 1, borderColor: "divider", mb: 2 }}>
        <Tabs
          value={activeTab}
          onChange={(_, newValue) => setActiveTab(newValue as BrowseTab)}
        >
          <Tab label="Library" value="library" />
          <Tab label="Artists" value="artists" />
          <Tab label="Albums" value="albums" />
          <Tab label="Genres" value="genres" />
          <Tab label="Years" value="years" />
        </Tabs>
      </Box>

      {activeTab === "library" ? (
        <Box sx={{ height: "calc(100vh - 200px)" }}>
          <LibraryBrowser />
        </Box>
      ) : (
        <EntityBrowser collection={activeTab} />
      )}
    </PageContainer>
  );
}
