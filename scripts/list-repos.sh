#!/usr/bin/env bash
# List Northroot-Labs org repos (source of truth: GitHub) and local status.
# Usage: run from Northroot-Labs workspace root or pass NORTHROOT_WORKSPACE.

set -e
WORKSPACE_ROOT="${NORTHROOT_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
REPOS_DIR="${WORKSPACE_ROOT}/repos"

echo "=== GitHub (source of truth) ==="
gh repo list Northroot-Labs --limit 100

echo ""
echo "=== Local mirror (${REPOS_DIR}) ==="
if [[ ! -d "$REPOS_DIR" ]]; then
  echo "repos/ missing. Run scripts/clone-default.sh first."
  exit 0
fi
for d in "$REPOS_DIR"/*; do
  [[ -d "$d" ]] || continue
  name="$(basename "$d")"
  if [[ -f "$d/.git/HEAD" ]]; then
    branch=$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
    status=$(git -C "$d" status -sb 2>/dev/null | head -1)
    echo "  ${name}: ${branch}  ${status}"
  else
    echo "  ${name}: not a git repo"
  fi
done
