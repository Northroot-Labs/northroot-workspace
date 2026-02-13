#!/usr/bin/env bash
# Install pinned Hyena CLI from GitHub release into repos/hyena-rs/bin/hyena.
# Reads CHECKPOINT_ID from repos/hyena-rs/release-pin.txt; verifies with checksums-pin.txt.
# See repos/docs/internal/ci/VERSIONING_STANDARD.md. Run from workspace root.
set -e
WORKSPACE_ROOT="${NORTHROOT_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
HYENA_RS="${WORKSPACE_ROOT}/repos/hyena-rs"
BIN_DIR="${HYENA_RS}/bin"
PIN_FILE="${HYENA_RS}/release-pin.txt"
CHECKSUMS_PIN="${HYENA_RS}/checksums-pin.txt"
REPO="Northroot-Labs/hyena-rs"

CHECKPOINT_ID=$(grep -E '^CHECKPOINT_ID=' "$PIN_FILE" 2>/dev/null | cut -d= -f2-)
if [[ -z "$CHECKPOINT_ID" ]]; then
  echo "Missing CHECKPOINT_ID in $PIN_FILE" >&2
  exit 1
fi

ARCH=$(uname -m)
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARTIFACT="hyena-${CHECKPOINT_ID}-${ARCH}-${OS}"

if [[ ! -f "$CHECKSUMS_PIN" ]]; then
  echo "Missing $CHECKSUMS_PIN" >&2
  exit 1
fi
if ! grep -q "$ARTIFACT" "$CHECKSUMS_PIN"; then
  echo "No pinned checksum for $ARTIFACT in $CHECKSUMS_PIN" >&2
  exit 1
fi

mkdir -p "$BIN_DIR"
cd "$BIN_DIR"
# GitHub release tag = checkpoint ID (e.g. cp-20260213-2da2357)
gh release download "$CHECKPOINT_ID" --repo "$REPO" --pattern "$ARTIFACT" --clobber
grep "$ARTIFACT" "$CHECKSUMS_PIN" | shasum -a 256 -c -
chmod +x "$ARTIFACT"
ln -sf "$ARTIFACT" hyena
echo "Installed $ARTIFACT -> $BIN_DIR/hyena"
