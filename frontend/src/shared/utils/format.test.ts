import { describe, it, expect } from "vitest";

import { formatTrackDuration, formatTotalDuration } from "./format";

describe("formatTrackDuration", () => {
  it("formats whole minutes as M:SS", () => {
    expect(formatTrackDuration(125)).toBe("2:05");
  });

  it("pads single-digit seconds with zero", () => {
    expect(formatTrackDuration(67)).toBe("1:07");
  });

  it("handles exactly one minute", () => {
    expect(formatTrackDuration(60)).toBe("1:00");
  });

  it("returns dash for zero", () => {
    expect(formatTrackDuration(0)).toBe("-");
  });

  it("returns dash for negative values", () => {
    expect(formatTrackDuration(-30)).toBe("-");
  });

  it("returns dash for null", () => {
    expect(formatTrackDuration(null)).toBe("-");
  });

  it("returns dash for undefined", () => {
    expect(formatTrackDuration(undefined)).toBe("-");
  });

  it("formats sub-minute durations", () => {
    expect(formatTrackDuration(45)).toBe("0:45");
  });

  it("formats durations over an hour as M:SS", () => {
    expect(formatTrackDuration(3661)).toBe("61:01");
  });
});

describe("formatTotalDuration", () => {
  it("formats hours and minutes", () => {
    expect(formatTotalDuration(5430)).toBe("1h 30m");
  });

  it("handles zero seconds", () => {
    expect(formatTotalDuration(0)).toBe("0h 0m");
  });

  it("handles less than one hour", () => {
    expect(formatTotalDuration(2700)).toBe("0h 45m");
  });

  it("handles exactly one hour", () => {
    expect(formatTotalDuration(3600)).toBe("1h 0m");
  });

  it("handles large duration", () => {
    expect(formatTotalDuration(90061)).toBe("25h 1m");
  });
});
