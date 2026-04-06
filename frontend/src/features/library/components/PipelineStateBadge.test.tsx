import { describe, expect, it } from "vitest";

import { renderWithProviders, screen } from "../../../test/render";

import { PipelineStateBadge } from "./PipelineStateBadge";

describe("PipelineStateBadge", () => {
  it.each([
    ["idle", "Idle", "MuiChip-colorDefault"],
    ["scanning", "Scanning", "MuiChip-colorInfo"],
    ["ml_running", "ML running", "MuiChip-colorInfo"],
    ["too_small", "Too small", "MuiChip-colorWarning"],
    ["awaiting_calibration", "Awaiting calibration", "MuiChip-colorInfo"],
    ["calibrating", "Calibrating", "MuiChip-colorInfo"],
    ["applying", "Applying", "MuiChip-colorInfo"],
    ["write_ready", "Write ready", "MuiChip-colorWarning"],
    ["writing", "Writing", "MuiChip-colorInfo"],
    ["done", "Done", "MuiChip-colorSuccess"],
  ])("renders %s with label %s and chip color %s", (state, label, colorClass) => {
    renderWithProviders(<PipelineStateBadge state={state} />);

    const badge = screen.getByTestId("pipeline-state-badge");

    expect(badge).toHaveTextContent(label);
    expect(badge).toHaveClass(colorClass);
  });
});