import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { generatePlaylist as apiGeneratePlaylist } from "@shared/api/navidrome";
import type { GeneratePlaylistResponse } from "@shared/api/navidrome";

import { useNavidromeData } from "./useNavidromeData";

// The consumer path (M-7): generatePlaylist must read the backend's
// `playlist_structure` field and surface it in state as `playlistStructure`.
vi.mock("@shared/api/navidrome", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@shared/api/navidrome")>();
  return {
    ...actual,
    getConfig: vi.fn(),
    getPreview: vi.fn(),
    previewPlaylist: vi.fn(),
    generatePlaylist: vi.fn(),
  };
});

vi.mock("../../../hooks/useNotification", () => ({
  useNotification: () => ({ showError: vi.fn() }),
}));

const validRootGroup = {
  id: "g1",
  logic: "all" as const,
  rules: [{ id: "r1", tagKey: "nom:mood", operator: "=" as const, value: "happy" }],
  groups: [],
};

describe("useNavidromeData", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("stores the generated playlist_structure response into playlistStructure state", async () => {
    const structure = { name: "My Playlist", all: [{ op: { mood: "happy" } }] };
    vi.mocked(apiGeneratePlaylist).mockResolvedValue({
      playlist_structure: structure,
    } as GeneratePlaylistResponse);

    const { result } = renderHook(() => useNavidromeData());

    act(() => {
      result.current.setPlaylistRootGroup(validRootGroup);
      result.current.setPlaylistName("My Playlist");
    });

    await act(async () => {
      await result.current.generatePlaylist();
    });

    expect(apiGeneratePlaylist).toHaveBeenCalledTimes(1);
    // The consumer reads `playlist_structure` (not the removed `content` field).
    expect(result.current.playlistStructure).toEqual({ playlist_structure: structure });
  });
});
