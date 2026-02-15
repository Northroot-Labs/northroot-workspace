#!/usr/bin/env bash
# Run a command with scope enforcement: cwd and path args must be under in_scope_paths.
# Usage: ./northroot-workspaces/exec.sh [--] <command> [args...]
# Fails closed if scope.json is missing or any path is out of scope.
set -e

WORKSPACE_ROOT="${NORTHROOT_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
SCOPE_JSON="${WORKSPACE_ROOT}/scope.json"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Resolve scope: require scope.json
if [[ ! -f "$SCOPE_JSON" ]]; then
  echo "northroot-workspaces/exec.sh: scope not set. Run: ./northroot-workspaces/enter.sh <mode>" >&2
  exit 1
fi

# Absolute in-scope paths (one per line)
SCOPE_ABSOLUTE=()
while IFS= read -r line; do
  [[ -n "$line" ]] && SCOPE_ABSOLUTE+=("$line")
done < <(python3 - "$SCOPE_JSON" << 'PY'
import json, os, sys
with open(sys.argv[1]) as f:
  d = json.load(f)
root = os.path.normpath(d["workspace_root"])
for rel in d["in_scope_paths"]:
  print(os.path.normpath(os.path.join(root, rel)))
PY
)

# Check path is under at least one in-scope root (resolve with Python for portability)
is_under_scope() {
  local path="$1"
  path="$(python3 - "$path" << 'PY'
import os, sys
print(os.path.normpath(os.path.abspath(sys.argv[1])))
PY
)"
  [[ -z "$path" ]] && return 1
  local scope
  for scope in "${SCOPE_ABSOLUTE[@]}"; do
    if [[ "$path" == "$scope" ]] || [[ "$path" == "$scope"/* ]]; then
      return 0
    fi
  done
  return 1
}

# 1. Check cwd
CWD="$(pwd)"
if ! is_under_scope "$CWD"; then
  echo "northroot-workspaces/exec.sh: cwd '$CWD' is out of scope. Run from an in-scope path or change scope with enter.sh" >&2
  exit 1
fi

# 2. Parse command line: find path-like args (-C <path>, or args that look like repos/...)
ARGS=()
SKIP_NEXT=0
for i in "$@"; do
  [[ "$i" == "--" ]] && continue
  if [[ $SKIP_NEXT -eq 1 ]]; then
    if ! is_under_scope "$i"; then
      echo "northroot-workspaces/exec.sh: path '$i' is out of scope" >&2
      exit 1
    fi
    SKIP_NEXT=0
    ARGS+=("$i")
    continue
  fi
  if [[ "$i" == "-C" ]] || [[ "$i" == "-c" ]]; then
    SKIP_NEXT=1
    ARGS+=("$i")
    continue
  fi
  # Path-like: under workspace and looks like a path
  if [[ "$i" == repos/* ]] || [[ "$i" == /* ]] || [[ "$i" == ./* ]] || [[ "$i" == ../* ]]; then
    if [[ -e "$WORKSPACE_ROOT/$i" ]] || [[ -e "$i" ]]; then
      tocheck="$i"
      [[ "$i" != /* ]] && tocheck="$WORKSPACE_ROOT/$i"
      if ! is_under_scope "$tocheck"; then
        echo "northroot-workspaces/exec.sh: path '$i' is out of scope" >&2
        exit 1
      fi
    fi
  fi
  ARGS+=("$i")
done

# 3. Run command
exec "${ARGS[@]}"
