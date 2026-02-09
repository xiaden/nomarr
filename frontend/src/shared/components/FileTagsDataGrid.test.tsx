import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderWithProviders, screen, within } from "../../test/render";

import { FileTagsDataGrid } from "./FileTagsDataGrid";

// ──────────────────────────────────────────────────────────────────────
// Test fixtures
// ──────────────────────────────────────────────────────────────────────

const METADATA_TAG = { key: "artist", value: "Beatles", type: "string", is_nomarr: false };
const METADATA_TAG_2 = { key: "album", value: "Abbey Road", type: "string", is_nomarr: false };
const EXTENDED_TAG = { key: "composer", value: "Lennon/McCartney", type: "string", is_nomarr: false };
const EXTENDED_TAG_2 = { key: "bpm", value: "120", type: "string", is_nomarr: false };
const NOMARR_TAG = { key: "nom:mood-strict", value: "happy, energetic", type: "string", is_nomarr: true };
const NOMARR_TAG_2 = { key: "nom:effnet_engaging", value: "0.85", type: "string", is_nomarr: true };
const RAW_HEAD_TAG = {
  key: "nom:tonal_essentia21-beta6-dev_musicnn20200331_tonal20220825",
  value: "0.72",
  type: "float",
  is_nomarr: true,
};
const RAW_HEAD_TAG_2 = {
  key: "nom:happy_essentia21-beta6-dev_musicnn20200331_happy20220825",
  value: "0.91",
  type: "float",
  is_nomarr: true,
};

const ALL_TAGS = [
  METADATA_TAG,
  METADATA_TAG_2,
  EXTENDED_TAG,
  EXTENDED_TAG_2,
  NOMARR_TAG,
  NOMARR_TAG_2,
  RAW_HEAD_TAG,
  RAW_HEAD_TAG_2,
];

function getAccordionByLabel(label: string): HTMLElement {
  // Find the accordion summary containing the label text
  const heading = screen.getByText(label);
  // Walk up to the Accordion root (role=region is on the details, not the root)
  // The accordion root contains both the summary button and the details
  return heading.closest(".MuiAccordion-root")!;
}

// ──────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────

describe("FileTagsDataGrid", () => {
  describe("tag grouping", () => {
    it("renders 4 groups when all tag types present", () => {
      renderWithProviders(<FileTagsDataGrid tags={ALL_TAGS} />);

      expect(screen.getByText("Metadata")).toBeInTheDocument();
      expect(screen.getByText("Nomarr Tags")).toBeInTheDocument();
      expect(screen.getByText("Raw Head Outputs")).toBeInTheDocument();
      expect(screen.getByText("Extended Metadata")).toBeInTheDocument();
    });

    it("hides groups with no tags", () => {
      renderWithProviders(<FileTagsDataGrid tags={[METADATA_TAG]} />);

      expect(screen.getByText("Metadata")).toBeInTheDocument();
      expect(screen.queryByText("Nomarr Tags")).not.toBeInTheDocument();
      expect(screen.queryByText("Raw Head Outputs")).not.toBeInTheDocument();
      expect(screen.queryByText("Extended Metadata")).not.toBeInTheDocument();
    });

    it("classifies whitelisted keys as Metadata", () => {
      renderWithProviders(<FileTagsDataGrid tags={[METADATA_TAG, METADATA_TAG_2]} />);

      const accordion = getAccordionByLabel("Metadata");
      expect(within(accordion).getByText("artist")).toBeInTheDocument();
      expect(within(accordion).getByText("album")).toBeInTheDocument();
    });

    it("classifies non-whitelisted non-nom keys as Extended Metadata", () => {
      renderWithProviders(<FileTagsDataGrid tags={[EXTENDED_TAG]} />);

      const accordion = getAccordionByLabel("Extended Metadata");
      expect(within(accordion).getByText("composer")).toBeInTheDocument();
    });

    it("classifies nom: keys without _essentia as Nomarr Tags", () => {
      renderWithProviders(<FileTagsDataGrid tags={[NOMARR_TAG]} />);

      const accordion = getAccordionByLabel("Nomarr Tags");
      expect(within(accordion).getByText("nom:mood-strict")).toBeInTheDocument();
    });

    it("classifies nom: keys with _essentia as Raw Head Outputs", () => {
      renderWithProviders(<FileTagsDataGrid tags={[RAW_HEAD_TAG]} />);

      const accordion = getAccordionByLabel("Raw Head Outputs");
      expect(within(accordion).getByText(RAW_HEAD_TAG.key)).toBeInTheDocument();
    });

    it("sorts tags alphabetically within each group", () => {
      // album should come before artist alphabetically
      renderWithProviders(<FileTagsDataGrid tags={[METADATA_TAG, METADATA_TAG_2]} />);

      const accordion = getAccordionByLabel("Metadata");
      const cells = within(accordion).getAllByRole("cell");
      // First row key cell should be "album" (before "artist")
      expect(cells[0]).toHaveTextContent("album");
    });

    it("shows tag count per group in accordion summary", () => {
      renderWithProviders(<FileTagsDataGrid tags={[METADATA_TAG, NOMARR_TAG, RAW_HEAD_TAG]} />);

      // Each group with 1 tag shows (1)
      const metadataAccordion = getAccordionByLabel("Metadata");
      expect(within(metadataAccordion).getByText("(1)")).toBeInTheDocument();

      const nomarrAccordion = getAccordionByLabel("Nomarr Tags");
      expect(within(nomarrAccordion).getByText("(1)")).toBeInTheDocument();
    });
  });

  describe("accordion behavior", () => {
    it("expands Metadata and Nomarr Tags by default", () => {
      renderWithProviders(<FileTagsDataGrid tags={ALL_TAGS} />);

      // Expanded accordions have visible content
      const metadataAccordion = getAccordionByLabel("Metadata");
      expect(within(metadataAccordion).getByText("Beatles")).toBeInTheDocument();

      const nomarrAccordion = getAccordionByLabel("Nomarr Tags");
      expect(within(nomarrAccordion).getByText("happy, energetic")).toBeInTheDocument();
    });

    it("collapses Raw Head Outputs by default", () => {
      renderWithProviders(<FileTagsDataGrid tags={ALL_TAGS} />);

      const accordion = getAccordionByLabel("Raw Head Outputs");
      // The expand button should have aria-expanded=false
      const button = within(accordion).getByRole("button");
      expect(button).toHaveAttribute("aria-expanded", "false");
    });

    it("collapses Extended Metadata by default", () => {
      renderWithProviders(<FileTagsDataGrid tags={ALL_TAGS} />);

      const accordion = getAccordionByLabel("Extended Metadata");
      const button = within(accordion).getByRole("button");
      expect(button).toHaveAttribute("aria-expanded", "false");
    });
  });

  describe("quick filter", () => {
    it("filters tags by key match", async () => {
      const user = userEvent.setup();
      renderWithProviders(<FileTagsDataGrid tags={ALL_TAGS} />);

      const filterInput = screen.getByPlaceholderText("Filter tags...");
      await user.type(filterInput, "artist");

      // Only Metadata group should remain (with "artist" key)
      expect(screen.getByText("Metadata")).toBeInTheDocument();
      expect(screen.queryByText("Nomarr Tags")).not.toBeInTheDocument();
      expect(screen.queryByText("Raw Head Outputs")).not.toBeInTheDocument();
      expect(screen.queryByText("Extended Metadata")).not.toBeInTheDocument();
    });

    it("filters tags by value match", async () => {
      const user = userEvent.setup();
      renderWithProviders(<FileTagsDataGrid tags={ALL_TAGS} />);

      const filterInput = screen.getByPlaceholderText("Filter tags...");
      await user.type(filterInput, "Beatles");

      expect(screen.getByText("Metadata")).toBeInTheDocument();
      // Only one tag matches
      const accordion = getAccordionByLabel("Metadata");
      expect(within(accordion).getByText("Beatles")).toBeInTheDocument();
    });

    it("shows empty message when filter matches nothing", async () => {
      const user = userEvent.setup();
      renderWithProviders(<FileTagsDataGrid tags={ALL_TAGS} />);

      const filterInput = screen.getByPlaceholderText("Filter tags...");
      await user.type(filterInput, "zzz_nonexistent");

      expect(screen.getByText("No tags match the current filter")).toBeInTheDocument();
    });
  });

  describe("nomarr-only toggle", () => {
    it("hides non-nomarr groups when enabled", async () => {
      const user = userEvent.setup();
      renderWithProviders(<FileTagsDataGrid tags={ALL_TAGS} />);

      // MUI Switch renders as a checkbox input inside the switch
      const toggle = screen.getByLabelText(/nomarr only/i);
      await user.click(toggle);

      // Metadata and Extended should disappear
      expect(screen.queryByText("Metadata")).not.toBeInTheDocument();
      expect(screen.queryByText("Extended Metadata")).not.toBeInTheDocument();

      // Nomarr groups should remain
      expect(screen.getByText("Nomarr Tags")).toBeInTheDocument();
      expect(screen.getByText("Raw Head Outputs")).toBeInTheDocument();
    });
  });

  describe("empty state", () => {
    it("shows empty message when no tags", () => {
      renderWithProviders(<FileTagsDataGrid tags={[]} />);

      expect(screen.getByText("No tags found")).toBeInTheDocument();
    });
  });

  describe("total count", () => {
    it("shows total tag count in header", () => {
      renderWithProviders(<FileTagsDataGrid tags={ALL_TAGS} />);

      expect(screen.getByText(`Tags (${ALL_TAGS.length})`)).toBeInTheDocument();
    });
  });
});
