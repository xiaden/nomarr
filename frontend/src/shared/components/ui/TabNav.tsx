/**
 * TabNav - Tab navigation component
 * Provides consistent tab styling across features
 */

import { Box, Button } from "@mui/material";
import type { ReactNode } from "react";

export interface Tab {
  id: string;
  label: ReactNode;
}

export interface TabNavProps {
  tabs: Tab[];
  activeTab: string;
  onTabChange: (tabId: string) => void;
}

export function TabNav({ tabs, activeTab, onTabChange }: TabNavProps) {
  return (
    <Box
      sx={{
        display: "flex",
        gap: 0,
        borderBottom: 1,
        borderColor: "divider",
        mb: 2.5,
      }}
    >
      {tabs.map((tab) => (
        <Button
          key={tab.id}
          onClick={() => onTabChange(tab.id)}
          sx={{
            px: 3,
            py: 1.5,
            backgroundColor: "transparent",
            border: "none",
            borderBottom: 2,
            borderColor: activeTab === tab.id ? "primary.main" : "transparent",
            borderRadius: 0,
            color: activeTab === tab.id ? "text.primary" : "text.secondary",
            fontSize: "1rem",
            textTransform: "none",
            transition: "color 0.2s, border-color 0.2s",
            "&:hover": {
              backgroundColor: "transparent",
              color: "text.primary",
            },
          }}
        >
          {tab.label}
        </Button>
      ))}
    </Box>
  );
}
