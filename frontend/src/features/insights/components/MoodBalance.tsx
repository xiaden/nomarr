/**
 * MoodBalance - Display mood distribution per tier.
 *
 * Shows how moods are distributed within each tier.
 */

import { Box, Typography } from "@mui/material";

import type { MoodBalanceItem } from "../../../shared/api/analytics";

import { AccordionSubsection } from "./AccordionSubsection";

interface MoodBalanceProps {
  balance: Record<string, MoodBalanceItem[]>;
  parentId: string;
}

const TIER_LABELS: Record<string, string> = {
  strict: "Strict",
  relaxed: "Relaxed",
  genre: "Genre",
};

export function MoodBalance({ balance, parentId }: MoodBalanceProps) {
  const tierEntries = Object.entries(balance);

  if (tierEntries.length === 0) {
    return (
      <AccordionSubsection
        subsectionId="balance"
        parentId={parentId}
        title="Mood Balance"
      >
        <Typography color="text.secondary">No mood data available</Typography>
      </AccordionSubsection>
    );
  }

  return (
    <AccordionSubsection
      subsectionId="balance"
      parentId={parentId}
      title="Mood Balance"
      defaultExpanded={false}
    >
      <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {tierEntries.map(([tier, moods]) => {
          const maxCount = Math.max(...moods.map((m) => m.count), 1);

          return (
            <Box key={tier}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                {TIER_LABELS[tier] || tier} Tier
              </Typography>
              <Box sx={{ maxHeight: 150, overflow: "auto" }}>
                {moods.map((item) => (
                  <Box
                    key={`${tier}-${item.mood}`}
                    sx={{
                      display: "flex",
                      alignItems: "center",
                      mb: 0.5,
                    }}
                  >
                    <Typography
                      variant="body2"
                      sx={{
                        width: 80,
                        flexShrink: 0,
                        textTransform: "capitalize",
                      }}
                    >
                      {item.mood}
                    </Typography>
                    <Box
                      sx={{
                        height: 12,
                        width: `${(item.count / maxCount) * 100}%`,
                        minWidth: 2,
                        bgcolor: "secondary.main",
                        borderRadius: 0.5,
                      }}
                    />
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{ ml: 1, flexShrink: 0 }}
                    >
                      {item.count}
                    </Typography>
                  </Box>
                ))}
              </Box>
            </Box>
          );
        })}
      </Box>
    </AccordionSubsection>
  );
}
