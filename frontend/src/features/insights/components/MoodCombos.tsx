/**
 * MoodCombos - Display top co-occurring mood pairs grouped by tier.
 *
 * Each tier (strict / regular / loose) is shown in its own sub-accordion
 * so all three can be browsed without any full re-fetch.
 */

import { Box, Chip, Typography } from "@mui/material";

import { AccordionSubsection } from "@shared/components/ui";

import type { MoodPairItem } from "../../../shared/api/analytics";


const TIER_META: { key: string; label: string; defaultExpanded: boolean }[] = [
  { key: "strict",  label: "Strict",  defaultExpanded: true },
  { key: "regular", label: "Regular", defaultExpanded: false },
  { key: "loose",   label: "Loose",   defaultExpanded: false },
];

interface MoodCombosProps {
  pairsByTier: Record<string, MoodPairItem[]>;
  parentId: string;
}

function TierPairs({
  pairs,
  tier,
  parentId,
  defaultExpanded,
}: {
  pairs: MoodPairItem[];
  tier: string;
  parentId: string;
  defaultExpanded: boolean;
}) {
  const label = TIER_META.find((t) => t.key === tier)?.label ?? tier;
  const count = pairs.length;

  return (
    <AccordionSubsection
      subsectionId={`combos-${tier}`}
      parentId={parentId}
      title={label}
      defaultExpanded={defaultExpanded}
      secondary={
        <Typography variant="body2" color="text.secondary">
          {count} pair{count !== 1 ? "s" : ""}
        </Typography>
      }
    >
      {pairs.length === 0 ? (
        <Typography color="text.secondary">No combinations found</Typography>
      ) : (
        <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
          {pairs.map((pair, index) => (
            <Chip
              key={`${pair.mood1}-${pair.mood2}`}
              label={
                <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                  <Typography
                    variant="body2"
                    component="span"
                    sx={{ textTransform: "capitalize" }}
                  >
                    {pair.mood1}
                  </Typography>
                  <Typography variant="body2" component="span" color="text.secondary">
                    +
                  </Typography>
                  <Typography
                    variant="body2"
                    component="span"
                    sx={{ textTransform: "capitalize" }}
                  >
                    {pair.mood2}
                  </Typography>
                  <Typography
                    variant="body2"
                    component="span"
                    color="text.secondary"
                    sx={{ ml: 0.5 }}
                  >
                    ({pair.count})
                  </Typography>
                </Box>
              }
              variant={index < 3 ? "filled" : "outlined"}
              color={index < 3 ? "primary" : "default"}
              size="small"
            />
          ))}
        </Box>
      )}
    </AccordionSubsection>
  );
}

export function MoodCombos({ pairsByTier, parentId }: MoodCombosProps) {
  return (
    <AccordionSubsection
      subsectionId="combos"
      parentId={parentId}
      title="Mood Combos"
      defaultExpanded={false}
      secondary={
        <Typography variant="body2" color="text.secondary">
          Top pairs
        </Typography>
      }
    >
      {TIER_META.map(({ key, defaultExpanded }) => (
        <TierPairs
          key={key}
          tier={key}
          pairs={pairsByTier[key] ?? []}
          parentId={`${parentId}:combos`}
          defaultExpanded={defaultExpanded}
        />
      ))}
    </AccordionSubsection>
  );
}
