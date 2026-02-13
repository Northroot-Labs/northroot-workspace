#!/usr/bin/env bash
# Pull all repos in repos/ to match GitHub. Clone default set if repos/ empty.
# Usage: run from Northroot-Labs workspace root or set NORTHROOT_WORKSPACE.

set -e
WORKSPACE_ROOT="${NORTHROOT_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
REPOS_DIR="${WORKSPACE_ROOT}/repos"

if [[ ! -d "$REPOS_DIR" ]]; then
  mkdir -p "$REPOS_DIR"
fi
shopt -s nullglob
cloned=("$REPOS_DIR"/*)
if [[ ${#cloned[@]} -eq 0 ]] || [[ ! -d "${cloned[0]}/.git" ]]; then
  echo "No repos in repos/. Running clone-default.sh first."
  NORTHROOT_WORKSPACE="$WORKSPACE_ROOT" "$(dirname "$0")/clone-default.sh"
fi

for d in "$REPOS_DIR"/*; do
  [[ -d "$d" ]] || continue
  [[ -f "$d/.git/HEAD" ]] || continue
  name=$(basename "$d")
  echo "pull: $name"
  git -C "$d" fetch --prune
  git -C "$d" pull --rebase 2>/dev/null || git -C "$d" pull
done

echo "done."
