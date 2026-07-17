#!/bin/bash
set -euo pipefail

# check-arango-fields.sh — Enforce ArangoDB field name boundaries
# Scans non-persistence Python code for _id/_key references and checks
# against .arango-field-allowlist.yaml. Exits 1 if new violations found.
#
# Usage: bash scripts/check-arango-fields.sh (from repo root)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ALLOWLIST="$REPO_ROOT/.arango-field-allowlist.yaml"
PINNED_RG_VERSION="14.1.1"

# --- P3-S2: Version check ---
if ! command -v rg &>/dev/null; then
    echo "ERROR: ripgrep (rg) is not installed."
    echo "Install ripgrep ${PINNED_RG_VERSION} from https://github.com/BurntSushi/ripgrep/releases"
    exit 1
fi

RG_VERSION=$(rg --version | head -1 | awk '{print $2}')
if [[ "$RG_VERSION" != "$PINNED_RG_VERSION" ]]; then
    echo "ERROR: ripgrep version mismatch."
    echo "  Expected: ${PINNED_RG_VERSION}"
    echo "  Found:    ${RG_VERSION}"
    echo "Install ripgrep ${PINNED_RG_VERSION} from https://github.com/BurntSushi/ripgrep/releases"
    exit 1
fi

# --- Check allowlist exists ---
if [[ ! -f "$ALLOWLIST" ]]; then
    echo "ERROR: Allowlist file not found: $ALLOWLIST"
    echo "Run Phase 2 of the import enforcement plan to create it."
    exit 1
fi

# --- P3-S3: Run ripgrep scan with JSON output ---
# rg exits 1 when no matches found — that's a clean pass for us
RG_STDERR_LOG="/tmp/rg-stderr-$$.log"
trap 'rm -f "$RG_STDERR_LOG"' EXIT

RG_OUTPUT=$(rg --glob '!nomarr/persistence/**' --glob '!tests/**' --type py --json \
    '\b_id\b|\b_key\b' nomarr/ 2>"$RG_STDERR_LOG") || true

# Check for genuine stderr errors (corrupted files, permission issues, etc.)
if [[ -s "$RG_STDERR_LOG" ]]; then
    echo "ERROR: ripgrep reported errors:" >&2
    cat "$RG_STDERR_LOG" >&2
    exit 1
fi

# --- Handle empty scan ---
if [[ -z "$RG_OUTPUT" ]]; then
    echo "No ArangoDB field name references found. Clean pass!"
    exit 0
fi

# --- P3-S4 + P3-S5: Filter matches against allowlist and report ---
RESULT=$(echo "$RG_OUTPUT" | python3 "$SCRIPT_DIR/_filter_arango_matches.py" \
    --allowlist "$ALLOWLIST") || {
    echo "$RESULT"
    exit 1
}

echo "$RESULT"
exit 0
