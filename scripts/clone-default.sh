#!/usr/bin/env bash
# Clone default working set into repos/ if not already present.
# Idempotent: skips existing clones. Run sync.sh afterward to pull.
# Usage: run from Northroot-Labs workspace root or set NORTHROOT_WORKSPACE.

set -e
WORKSPACE_ROOT="${NORTHROOT_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
REPOS_DIR="${WORKSPACE_ROOT}/repos"
MANIFEST="${WORKSPACE_ROOT}/repos.yaml"

if [[ ! -f "$MANIFEST" ]]; then
  echo "repos.yaml not found at $MANIFEST"
  exit 1
fi
mkdir -p "$REPOS_DIR"

# Parse default_working_set from repos.yaml (lines "  - name" under that key)
default_repos=()
in_section=0
while IFS= read -r line; do
  if [[ "$line" =~ ^default_working_set: ]]; then
    in_section=1
    continue
  fi
  if [[ $in_section -eq 1 ]]; then
    if [[ "$line" =~ ^[a-z] ]]; then
      break
    fi
    if [[ "$line" =~ ^[[:space:]]+-[[:space:]](.+)$ ]]; then
      name="${BASH_REMATCH[1]//[$'\r\n']}"; name="${name#"${name%%[![:space:]]*}"}"; name="${name%"${name##*[![:space:]]}"}"
      default_repos+=("$name")
    fi
  fi
done < "$MANIFEST"

for name in "${default_repos[@]}"; do
  dest="${REPOS_DIR}/${name}"
  if [[ -d "$dest/.git" ]]; then
    echo "skip (already cloned): $name"
    continue
  fi
  echo "clone: Northroot-Labs/${name} -> ${dest}"
  gh repo clone "Northroot-Labs/${name}" "$dest"
done
