/**
 * BrowsePage - Search-first music library browser
 *
 * Features:
 * - Fuzzy search across the library (artists, albums, tracks)
 * - Grouped search results with artist, album, and track sections
 * - Click-through to hierarchical LibraryBrowser for drill-down
 * - Library management accordion
 */

import { ArrowBack, Search } from "@mui/icons-material";
import {
  Box,
  CircularProgress,
  IconButton,
  InputAdornment,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useCallback, useState } from "react";

import { AccordionSection, PageContainer } from "@shared/components/ui";

import { LibraryManagement } from "../library/components/LibraryManagement";

import { LibraryBrowser, type NavigationStep } from "./components/LibraryBrowser";
import { SearchResults } from "./components/SearchResults";
import { useLibrarySearch } from "./hooks/useLibrarySearch";

type BrowseView = "search" | "browser";

export function BrowsePage() {
  const [query, setQuery] = useState("");
  const [view, setView] = useState<BrowseView>("search");
  const [browserStep, setBrowserStep] = useState<NavigationStep | undefined>();

  const { results, loading, error } = useLibrarySearch(query);

  const handleNavigate = useCallback((step: NavigationStep) => {
    setBrowserStep(step);
    setView("browser");
  }, []);

  const handleBackToSearch = useCallback(() => {
    setView("search");
    setBrowserStep(undefined);
  }, []);

  return (
    <PageContainer title="Library">
      <AccordionSection
        sectionId="browse:library-management"
        title="Library Management"
      >
        <LibraryManagement />
      </AccordionSection>

      {view === "search" ? (
        <Stack spacing={2} sx={{ mt: 3 }}>
          {/* Search Input */}
          <TextField
            fullWidth
            placeholder="Search library... (a: artist, al: album, t: track)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            size="medium"
            slotProps={{
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <Search color="action" />
                  </InputAdornment>
                ),
                endAdornment: loading ? (
                  <InputAdornment position="end">
                    <CircularProgress size={20} />
                  </InputAdornment>
                ) : null,
              },
            }}
            autoFocus
          />
          <Typography variant="caption" color="text.disabled">
            Prefix with a: artist, al: album, t: track to narrow results
          </Typography>

          {/* Error */}
          {error && (
            <Typography color="error" variant="body2">
              {error}
            </Typography>
          )}

          {/* Empty state - no query yet */}
          {!query.trim() && !results && (
            <Box sx={{ textAlign: "center", py: 8 }}>
              <Search sx={{ fontSize: 64, color: "text.disabled", mb: 2 }} />
              <Typography variant="h6" color="text.secondary">
                Search your library
              </Typography>
              <Typography variant="body2" color="text.disabled">
                Type to search across all fields, or use prefixes to narrow results
              </Typography>
              <Typography variant="body2" color="text.disabled" sx={{ mt: 0.5, fontFamily: "monospace" }}>
                a:artist &nbsp; al:album &nbsp; t:track
              </Typography>
              <Typography variant="body2" color="text.disabled" sx={{ mt: 0.5, fontStyle: "italic" }}>
                Example: a:good charlotte t:change
              </Typography>
            </Box>
          )}

          {/* Search Results */}
          {results && (
            <SearchResults results={results} onNavigate={handleNavigate} />
          )}
        </Stack>
      ) : (
        <Stack spacing={1} sx={{ mt: 2 }}>
          {/* Back to search */}
          <Box>
            <IconButton onClick={handleBackToSearch} size="small">
              <ArrowBack />
            </IconButton>
            <Typography
              component="span"
              variant="body2"
              sx={{ ml: 0.5, cursor: "pointer", color: "text.secondary" }}
              onClick={handleBackToSearch}
            >
              Back to search
            </Typography>
          </Box>

          {/* Library Browser */}
          <Box sx={{ height: "calc(100vh - 200px)" }}>
            <LibraryBrowser initialStep={browserStep} />
          </Box>
        </Stack>
      )}
    </PageContainer>
  );
}
