import { renderHook, waitFor, act, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { getTagCoOccurrence } from "../../../../shared/api/analytics";
import { getMoodValues } from "../../../../shared/api/files";
import { renderWithProviders, screen } from "../../../../test/render";
import { TagCoOccurrenceGrid } from "../TagCoOccurrenceGrid";

import { useAxisState } from "./useAxisState";
import { fetchPresetTags } from "./usePresetData";

// Mock the API calls
vi.mock("../../../../shared/api/files", () => ({
  getUniqueTagKeys: vi.fn().mockResolvedValue({ tag_keys: ["genre", "year", "artist"], count: 3 }),
  getUniqueTagValues: vi.fn().mockImplementation((key: string) => {
    if (key === "genre") {
      return Promise.resolve({ tag_keys: ["Rock", "Pop", "Jazz"], count: 3 });
    }
    if (key === "year") {
      return Promise.resolve({ tag_keys: ["2020", "2021", "2022"], count: 3 });
    }
    return Promise.resolve({ tag_keys: [], count: 0 });
  }),
  getMoodValues: vi.fn().mockResolvedValue({ tag_keys: ["aggressive", "happy"], count: 2 }),
}));

vi.mock("../../../../shared/api/analytics", () => ({
  getTagCoOccurrence: vi.fn().mockResolvedValue({
    x: [
      { key: "genre", value: "Rock" },
      { key: "genre", value: "Pop" },
    ],
    y: [
      { key: "year", value: "2020" },
      { key: "year", value: "2021" },
    ],
    matrix: [
      [10, 5],
      [8, 12],
    ],
  }),
}));

describe("TagCoOccurrenceGrid", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("rendering", () => {
    it("renders section header", () => {
      renderWithProviders(<TagCoOccurrenceGrid />);
      expect(screen.getByText("Tag Co-Occurrence Grid")).toBeInTheDocument();
    });

    it("renders preset selectors for both axes", () => {
      renderWithProviders(<TagCoOccurrenceGrid />);
      expect(screen.getByText("X Axis:")).toBeInTheDocument();
      expect(screen.getByText("Y Axis:")).toBeInTheDocument();
    });

    it("renders all preset options", () => {
      renderWithProviders(<TagCoOccurrenceGrid />);
      // Each preset appears twice (X and Y axis selectors)
      const genreButtons = screen.getAllByText("Genre");
      const moodButtons = screen.getAllByText("Mood");
      const yearButtons = screen.getAllByText("Year");
      const manualButtons = screen.getAllByText("Manual");

      expect(genreButtons).toHaveLength(2);
      expect(moodButtons).toHaveLength(2);
      expect(yearButtons).toHaveLength(2);
      expect(manualButtons).toHaveLength(2);
    });

    it("renders swap button on Y axis row", () => {
      renderWithProviders(<TagCoOccurrenceGrid />);
      const swapButton = screen.getByRole("button", { name: /swap/i });
      expect(swapButton).toBeInTheDocument();
    });
  });

  describe("manual mode", () => {
    it("does not show manual selector when no axis is in manual mode", () => {
      renderWithProviders(<TagCoOccurrenceGrid />);

      // The accordion should not be visible initially
      expect(
        screen.queryByText("Advanced (Manual Tag Selection)")
      ).not.toBeInTheDocument();
    });
  });
});

describe("mood preset key", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("every tag returned by fetchPresetTags for mood has key === 'nom:mood-strict'", async () => {
    const tags = await fetchPresetTags("mood");

    expect(tags.length).toBeGreaterThan(0);
    expect(tags.every((t) => t.key === "nom:mood-strict")).toBe(true);
    expect(tags.some((t) => t.key === "nom:mood-*")).toBe(false);
  });
});

describe("cross-axis manual tags", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("allows the same tag to be added to both X and Y axes independently", async () => {
    const { result } = renderHook(() => useAxisState());

    // Wait for initial preset data to settle
    await waitFor(() => {
      expect(result.current.state.x.loading).toBe(false);
      expect(result.current.state.y.loading).toBe(false);
    });

    // Set both axes to manual mode
    act(() => {
      result.current.selectPreset("x", "manual");
    });
    act(() => {
      result.current.selectPreset("y", "manual");
    });

    // Add the same tag to both axes
    act(() => {
      result.current.addManualTag("x", { key: "genre", value: "Rock" });
    });
    act(() => {
      result.current.addManualTag("y", { key: "genre", value: "Rock" });
    });

    expect(result.current.state.x.tags).toContainEqual({ key: "genre", value: "Rock" });
    expect(result.current.state.y.tags).toContainEqual({ key: "genre", value: "Rock" });
  });
});


describe("preset switching", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("switching X axis to Mood fetches mood values and calls getTagCoOccurrence with nom:mood-strict tags", async () => {
    renderWithProviders(<TagCoOccurrenceGrid />);

    // Wait for initial genre/year data to settle and matrix to render
    await screen.findByRole("table");

    // Clear call history so we can assert on only post-switch calls
    vi.clearAllMocks();

    // Click the first Mood button (X axis — rendered before Y axis)
    fireEvent.click(screen.getAllByText("Mood")[0]);

    // Wait for mood values API to be called
    await waitFor(() => {
      expect(vi.mocked(getMoodValues)).toHaveBeenCalledTimes(1);
    });

    // Wait for co-occurrence matrix to be rebuilt with new tags
    await waitFor(() => {
      expect(vi.mocked(getTagCoOccurrence)).toHaveBeenCalled();
    });

    // Assert the most recent getTagCoOccurrence call used nom:mood-strict tags on X
    const calls = vi.mocked(getTagCoOccurrence).mock.calls;
    const lastCall = calls[calls.length - 1];
    expect(lastCall[0].x.every((tag) => tag.key === "nom:mood-strict")).toBe(true);
  });
});