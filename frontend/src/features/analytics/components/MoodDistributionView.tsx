/**
 * MoodDistribution - Display mood tag distribution with visual bars
 */

import { Stack } from "@mui/material";

import { Panel, ProgressBar, SectionHeader } from "@shared/components/ui";

interface MoodDistribution {
  mood: string;
  count: number;
  percentage: number;
}

interface MoodDistributionProps {
  data: MoodDistribution[];
}

export function MoodDistributionView({ data }: MoodDistributionProps) {
  return (
    <Panel>
      <SectionHeader title="Mood Distribution" />
      <Stack spacing={1.25}>
        {data.map((mood) => (
          <ProgressBar
            key={mood.mood}
            label={mood.mood}
            value={mood.count}
            percentage={mood.percentage}
          />
        ))}
      </Stack>
    </Panel>
  );
}
