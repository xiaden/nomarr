/**
 * InsightsDocumentation - Inline reference for Insights tab labels and concepts.
 *
 * Collapsed by default so it stays out of the way but is always at hand.
 * Covers: mood tiers, label glossary, how the analysis works.
 */

import {
  Box,
  Chip,
  Divider,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";

import { AccordionSection } from "@shared/components/ui";
import { AccordionSubsection } from "@shared/components/ui";

// ──────────────────────────────────────────────────────────────────────
// Data
// ──────────────────────────────────────────────────────────────────────

/** All human-readable labels that can appear in insight views, grouped. */
const LABEL_GROUPS: {
  group: string;
  description: string;
  pairs: { label: string; opposite?: string; meaning: string }[];
}[] = [
  {
    group: "Mood & Emotion",
    description:
      "Derived from multi-segment classifier heads trained on mood-annotated music. " +
      "Each pair is a softmax output — one label rises as the other falls.",
    pairs: [
      {
        label: "peppy",
        opposite: "sombre",
        meaning: "Upbeat, positive energy (peppy) vs. melancholic, downbeat tone (sombre).",
      },
      {
        label: "aggressive",
        opposite: "relaxed",
        meaning: "Intense, high-energy, driving feel (aggressive) vs. calm, peaceful, low-key (relaxed).",
      },
      {
        label: "party-like",
        opposite: "not party-like",
        meaning: "Energetic crowd-ready sound (party-like) vs. more introspective or ambient (not party-like).",
      },
    ],
  },
  {
    group: "Rhythm & Danceability",
    description: "How well the track invites movement.",
    pairs: [
      {
        label: "easy to dance to",
        opposite: "hard to dance to",
        meaning:
          "Strong groove, predictable beat, danceable structure vs. irregular or complex rhythmic feel.",
      },
    ],
  },
  {
    group: "Timbre & Texture",
    description:
      "Tonal colour and spectral character of the recording. " +
      "Bright/dark is a softmax pair — their calibrated scores always sum to 1.",
    pairs: [
      {
        label: "bright timbre",
        opposite: "dark timbre",
        meaning:
          "Bright timbre: prominent high frequencies, airy or metallic texture. " +
          "Dark timbre: emphasised low-mids/bass, warm or muffled character.",
      },
      {
        label: "synth-like",
        opposite: "acoustic-like",
        meaning:
          "Synthesiser-heavy, electronic tones (synth-like) vs. natural, organic, acoustic instrumentation (acoustic-like).",
      },
      {
        label: "tonal",
        opposite: "atonal",
        meaning: "Clear pitch centre or key (tonal) vs. dissonant, noise-like, or pitch-less content (atonal).",
      },
    ],
  },
  {
    group: "Vocals",
    description: "Presence and character of the human voice in the track.",
    pairs: [
      {
        label: "has vocals",
        opposite: "instrumental only",
        meaning:
          "At least one segment has a detected singing or speaking voice (has vocals) " +
          "vs. purely instrumental throughout (instrumental only).",
      },
      {
        label: "low-pitch vocal",
        opposite: "high-pitch vocal",
        meaning:
          "Predominantly lower-register vocals — typically male voices (low-pitch vocal) " +
          "vs. higher-register vocals — typically female voices (high-pitch vocal).",
      },
    ],
  },
  {
    group: "Mainstream Appeal",
    description:
      "Derived from regression heads (approachability, engagement). " +
      "Unlike classifiers, these are continuous values on a 0–1 scale; a label only appears " +
      "when the value is confidently above or below the midpoint.",
    pairs: [
      {
        label: "mainstream",
        opposite: "fringe",
        meaning:
          "Sounds likely to have broad listener appeal (mainstream) vs. unconventional, niche, or experimental (fringe).",
      },
      {
        label: "engaging",
        opposite: "mellow",
        meaning:
          "Active, attention-grabbing energy (engaging) vs. laid-back, background-friendly character (mellow).",
      },
    ],
  },
];

const TIER_ROWS: { tier: string; badge: string; description: string; threshold: string }[] = [
  {
    tier: "Strict",
    badge: "strict",
    description: "Highest-confidence assignments only. A label appears here only when the " +
      "model is very sure — low variance across segments, strong calibrated score.",
    threshold: "Very stable, high intensity",
  },
  {
    tier: "Regular",
    badge: "regular",
    description: "Includes all strict assignments plus medium-confidence ones. Broader coverage " +
      "at the cost of some false positives. Good starting point for filtering.",
    threshold: "Stable, moderate intensity",
  },
  {
    tier: "Loose",
    badge: "loose",
    description: "Includes all strict and regular assignments plus low-confidence hints. " +
      "Maximum recall — useful for discovery but may include speculative labels.",
    threshold: "Any passing score",
  },
];

// ──────────────────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────────────────

function TierTable() {
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell sx={{ fontWeight: 600, width: "12%" }}>Tier</TableCell>
          <TableCell sx={{ fontWeight: 600, width: "60%" }}>Meaning</TableCell>
          <TableCell sx={{ fontWeight: 600 }}>Confidence gate</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {TIER_ROWS.map((row) => (
          <TableRow key={row.tier}>
            <TableCell>
              <Chip label={row.badge} size="small" variant="outlined" sx={{ textTransform: "capitalize" }} />
            </TableCell>
            <TableCell>
              <Typography variant="body2">{row.description}</Typography>
            </TableCell>
            <TableCell>
              <Typography variant="body2" color="text.secondary">{row.threshold}</Typography>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function LabelGlossary() {
  return (
    <Box>
      {LABEL_GROUPS.map((group, gi) => (
        <Box key={group.group} sx={{ mb: gi < LABEL_GROUPS.length - 1 ? 3 : 0 }}>
          <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
            {group.group}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            {group.description}
          </Typography>
          {group.pairs.map((pair) => (
            <Box key={pair.label} sx={{ mb: 1.5 }}>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 0.5 }}>
                <Chip label={pair.label} size="small" color="primary" variant="outlined" />
                {pair.opposite && (
                  <>
                    <Typography variant="body2" color="text.disabled">↔</Typography>
                    <Chip label={pair.opposite} size="small" variant="outlined" />
                  </>
                )}
              </Box>
              <Typography variant="body2" color="text.secondary" sx={{ pl: 0.5 }}>
                {pair.meaning}
              </Typography>
            </Box>
          ))}
          {gi < LABEL_GROUPS.length - 1 && <Divider sx={{ mt: 2 }} />}
        </Box>
      ))}
    </Box>
  );
}

function HowItWorks() {
  return (
    <Box sx={{ "& p": { mb: 1.5 } }}>
      <Typography variant="body2">
        Nomarr splits each audio file into short overlapping segments and runs each through an
        EfficientNet embedder. The embeddings are fed into multiple specialised heads — each trained
        to predict a different audio attribute (mood, timbre, vocals, etc.).
      </Typography>
      <Typography variant="body2">
        Predictions from all segments are aggregated (mean + variance). High variance means the
        track has mixed character — e.g., has both calm and loud sections — and yields a lower-tier
        or no assignment. Low variance with a strong score yields a high-tier assignment.
      </Typography>
      <Typography variant="body2">
        The <strong>Calibration</strong> step normalises each head&apos;s output against your
        library&apos;s distribution. After calibration, a score of 0.5 means &ldquo;average for
        this library&rdquo;, not a global absolute. The P5/P95 range from your collection becomes
        the effective 0–1 display range.
      </Typography>
      <Typography variant="body2">
        Aggregated mood tags are then written into three tiers — strict ⊂ regular ⊂ loose — so you
        can choose the confidence level that fits your use case. Mood combos show which labels
        commonly appear together on the same track.
      </Typography>
    </Box>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Main component
// ──────────────────────────────────────────────────────────────────────

export function InsightsDocumentation() {
  return (
    <AccordionSection
      sectionId="insights-docs"
      title="About Insights"
      defaultExpanded={false}
      secondary={
        <Typography variant="body2" color="text.secondary">
          Label reference
        </Typography>
      }
    >
      <AccordionSubsection
        subsectionId="tiers"
        parentId="insights-docs"
        title="Mood Tiers"
        defaultExpanded={true}
      >
        <TierTable />
      </AccordionSubsection>

      <AccordionSubsection
        subsectionId="glossary"
        parentId="insights-docs"
        title="Label Glossary"
        defaultExpanded={false}
      >
        <LabelGlossary />
      </AccordionSubsection>

      <AccordionSubsection
        subsectionId="how-it-works"
        parentId="insights-docs"
        title="How It Works"
        defaultExpanded={false}
      >
        <HowItWorks />
      </AccordionSubsection>
    </AccordionSection>
  );
}
