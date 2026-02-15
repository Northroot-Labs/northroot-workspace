#!/usr/bin/env bash
# Baseline policy helper (annotated-tag pinning).
# Usage:
#   ./northroot-workspaces/baseline.sh schema
#   ./northroot-workspaces/baseline.sh verify-tags
#   ./northroot-workspaces/baseline.sh check-publish --repo Northroot-Labs/clearlyops --branch main --head HEAD
set -e

WORKSPACE_ROOT="${NORTHROOT_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
PY="${WORKSPACE_ROOT}/northroot-workspaces/baseline_verify.py"

if [[ ! -f "$PY" ]]; then
  echo "baseline.sh: missing verifier: $PY" >&2
  exit 1
fi

python3 "$PY" --workspace-root "$WORKSPACE_ROOT" "$@"
