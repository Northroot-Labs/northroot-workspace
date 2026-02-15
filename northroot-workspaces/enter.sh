#!/usr/bin/env bash
# Enter a workspace mode: set scope and optionally sync repos.
# Usage: ./northroot-workspaces/enter.sh <mode> [--sync]
# Reads metadata from repos/docs/internal/workspace/ (sync docs first if missing).
set -e

WORKSPACE_ROOT="${NORTHROOT_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
METADATA_DIR="${WORKSPACE_ROOT}/repos/docs/internal/workspace"
SCOPE_FILE="${WORKSPACE_ROOT}/WORKSPACE_SCOPE.md"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:-}"
DO_SYNC=""
[[ "${2:-}" == "--sync" ]] && DO_SYNC=1

if [[ -z "$MODE" ]]; then
  echo "Usage: $0 <mode> [--sync]"
  echo "Modes: narrow | clearlyops | broad | full"
  echo "  --sync   Pull remote for repos in this mode (and clone if missing for narrow/clearlyops)."
  exit 1
fi

if [[ ! -d "$METADATA_DIR" ]]; then
  echo "Metadata not found at ${METADATA_DIR}. Clone and sync docs first: ./scripts/clone-default.sh && ./scripts/sync.sh"
  exit 1
fi

# Parse modes.yaml for the requested mode (bash-friendly: no PyYAML)
get_mode_value() {
  local mode="$1"
  local key="$2"
  local file="${METADATA_DIR}/modes.yaml"
  local in_block=0
  local in_key=0
  local key_pattern="^    ${key}:"
  while IFS= read -r line; do
    if [[ "$line" =~ ^[[:space:]]{2}([a-z]+): ]]; then
      if [[ "${BASH_REMATCH[1]}" == "$mode" ]]; then
        in_block=1
        continue
      elif [[ $in_block -eq 1 ]]; then
        break
      fi
    fi
    if [[ $in_block -eq 1 ]]; then
      if [[ "$line" =~ $key_pattern ]]; then
        in_key=1
        continue
      fi
      if [[ $in_key -eq 1 ]]; then
        if [[ "$line" =~ ^[[:space:]]*-[[:space:]]+\"(.+)\" ]]; then
          echo "${BASH_REMATCH[1]}"
        elif [[ "$line" =~ ^[[:space:]]*-[[:space:]]+(.+)$ ]]; then
          echo "${BASH_REMATCH[1]}"
        elif [[ "$line" =~ ^[[:space:]]*[a-z] ]] && [[ ! "$line" =~ ^[[:space:]]*- ]]; then
          break
        fi
      fi
    fi
  done < "$file"
}

PATHS=()
while IFS= read -r p; do [[ -n "$p" ]] && PATHS+=("$p"); done < <(get_mode_value "$MODE" "in_scope_paths")
REPOS=()
while IFS= read -r r; do [[ -n "$r" ]] && REPOS+=("$r"); done < <(get_mode_value "$MODE" "repos")

if [[ ${#PATHS[@]} -eq 0 ]]; then
  echo "Unknown mode or no in_scope_paths: $MODE"
  exit 1
fi

# Optional: sync repos for this mode
if [[ -n "$DO_SYNC" ]]; then
  if [[ ${#REPOS[@]} -gt 0 ]]; then
    for r in "${REPOS[@]}"; do
      d="${WORKSPACE_ROOT}/repos/${r}"
      if [[ -d "$d/.git" ]]; then
        echo "pull: $r"
        git -C "$d" fetch --prune
        git -C "$d" pull --rebase 2>/dev/null || git -C "$d" pull || true
      else
        echo "clone: $r (use scripts/clone-default.sh or add to default_working_set and run clone-default.sh)"
        if command -v gh &>/dev/null; then
          gh repo clone "Northroot-Labs/${r}" "$d" || true
        fi
      fi
    done
  else
    "${WORKSPACE_ROOT}/scripts/sync.sh" || true
  fi
fi

# Build scope file
PATH_LIST=""
for p in "${PATHS[@]}"; do
  PATH_LIST="${PATH_LIST}  - \`${p}\`\n"
done

export NORTHROOT_WORKSPACE_MODE="$MODE"
export NORTHROOT_WORKSPACE="$WORKSPACE_ROOT"

cat > "$SCOPE_FILE" << SCOPE
# Workspace scoped context (editor-agnostic)

**Purpose:** Defines the current in-scope context so agents and tools stay focused when this scope is active. Read this file at session or task start. Any editor or runner can use it.

## Current scope: $MODE (runtime-enforced)

- **Mode:** \`$MODE\` (set by northroot-workspaces/enter.sh)
- **In-scope paths (only):**
$(printf '%b' "$PATH_LIST")
- **Behavior:** Restrict reads and edits to the in-scope paths above. Do not depend on or modify content under other \`repos/*\` unless the user explicitly expands scope.
- **To change scope:** Run \`./northroot-workspaces/enter.sh <mode> [--sync]\` from workspace root. Modes: narrow | clearlyops | broad | full.

## When this file applies

Active whenever working in this workspace. Scope is enforced at session start by reading this file (see root .cursorrules).
SCOPE

# Machine-readable scope for enforcement (exec.sh and other tools)
SCOPE_JSON="${WORKSPACE_ROOT}/scope.json"
# Build JSON array of in_scope_paths (bash-safe)
JSON_PATHS=""
for i in "${!PATHS[@]}"; do
  [[ $i -gt 0 ]] && JSON_PATHS="${JSON_PATHS},"
  JSON_PATHS="${JSON_PATHS}\"${PATHS[$i]}\""
done
printf '%s\n' "{\"workspace_root\": \"${WORKSPACE_ROOT}\", \"mode\": \"${MODE}\", \"in_scope_paths\": [${JSON_PATHS}]}" > "$SCOPE_JSON"

echo "Scope set to mode: $MODE"
echo "WORKSPACE_SCOPE.md and scope.json written. NORTHROOT_WORKSPACE_MODE=$MODE"
