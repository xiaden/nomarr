import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { search } from "@shared/api/files";

import { useLibrarySearch } from "./useLibrarySearch";

vi.mock("@shared/api/files", () => ({
  search: vi.fn(),
}));

const emptyResponse = { files: [], total: 0, limit: 200, offset: 0 };

describe("useLibrarySearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(search).mockReset();
  });

  it("does not apply an in-flight result after the query is cleared", async () => {
    let resolveSearch!: (response: typeof emptyResponse) => void;
    vi.mocked(search).mockReturnValue(
      new Promise((resolve) => {
        resolveSearch = resolve;
      }),
    );

    const { result, rerender } = renderHook(({ query }) => useLibrarySearch(query), {
      initialProps: { query: "first" },
    });

    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(result.current.loading).toBe(true);

    rerender({ query: "" });
    expect(result.current).toMatchObject({
      results: null,
      loading: false,
      activeQuery: "",
      error: null,
    });

    await act(async () => {
      resolveSearch(emptyResponse);
    });

    expect(result.current.results).toBeNull();
  });

  it("does not apply an old in-flight result after the query changes", async () => {
    let resolveFirst!: (response: typeof emptyResponse) => void;
    const firstSearch = new Promise<typeof emptyResponse>((resolve) => {
      resolveFirst = resolve;
    });
    vi.mocked(search).mockReturnValueOnce(firstSearch).mockResolvedValueOnce({
      ...emptyResponse,
      files: [
        {
          file_id:
            "nom1eyJsaWJyYXJ5X3V1aWQiOiIxMjNlNDU2Ny1lODliLTQyZDMtYTQ1Ni00MjY2MTQxNzQwMDAiLCJwYXRoIjoibmV3Lm1wMyJ9",
          path: "/new.mp3",
          library_uuid: "123e4567-e89b-42d3-a456-426614174000",
          tagged: true,
          skip_auto_tag: false,
          tags: [],
        },
      ],
    });

    const { result, rerender } = renderHook(({ query }) => useLibrarySearch(query), {
      initialProps: { query: "first" },
    });

    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    rerender({ query: "second" });

    await act(async () => {
      resolveFirst(emptyResponse);
    });
    expect(result.current.results).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(500);
      await Promise.resolve();
    });
    expect(result.current.results?.tracks[0].file_id).toBe(
      "nom1eyJsaWJyYXJ5X3V1aWQiOiIxMjNlNDU2Ny1lODliLTQyZDMtYTQ1Ni00MjY2MTQxNzQwMDAiLCJwYXRoIjoibmV3Lm1wMyJ9",
    );
    expect(result.current.results?.tracks[0].library_uuid).toBe("123e4567-e89b-42d3-a456-426614174000");
  });
});
