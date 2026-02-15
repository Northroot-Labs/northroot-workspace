#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BROKERED_TAG_SH="$SCRIPT_DIR/brokered-tag.sh"
BASELINE_SH="$SCRIPT_DIR/baseline.sh"
REGISTRY_JSON="$SCRIPT_DIR/baselines/registry.json"

usage() {
  cat <<'EOF'
Usage: checkpoint-promote.sh \
  --repo Northroot-Labs/<repo> \
  --tag <tag-name> \
  --run-id <id> \
  --delegated-by <human-id> \
  --mode human-cosign|delegated \
  [--target-ref <git-ref>] \
  [--co-signed-by <email>] \
  [--delegated-action <ticket/spec>] \
  [--scope <text>] \
  [--no-fetch] \
  [--bucket checkpoint|release_candidate|release|incident_hotfix|deprecated]

Creates a signed annotated checkpoint tag, updates baseline registry pin (tag+sha),
then runs baseline schema + verify-tags checks.

By default, performs online freshness checks via `git fetch --prune --tags origin`
and tags `origin/main` to avoid pinning stale local-only state.
EOF
}

fail() {
  echo "error: $1" >&2
  exit 1
}

REPO_FULL=""
TAG_NAME=""
RUN_ID=""
DELEGATED_BY=""
MODE=""
CO_SIGNED_BY=""
DELEGATED_ACTION=""
ACTION_SCOPE=""
BUCKET="checkpoint"
TARGET_REF="origin/main"
DO_FETCH=1

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO_FULL="${2:-}"; shift 2 ;;
    --tag) TAG_NAME="${2:-}"; shift 2 ;;
    --run-id) RUN_ID="${2:-}"; shift 2 ;;
    --delegated-by) DELEGATED_BY="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --target-ref) TARGET_REF="${2:-}"; shift 2 ;;
    --co-signed-by) CO_SIGNED_BY="${2:-}"; shift 2 ;;
    --delegated-action) DELEGATED_ACTION="${2:-}"; shift 2 ;;
    --scope) ACTION_SCOPE="${2:-}"; shift 2 ;;
    --no-fetch) DO_FETCH=0; shift ;;
    --bucket) BUCKET="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown arg: $1" ;;
  esac
done

[ -n "$REPO_FULL" ] || fail "--repo is required"
[ -n "$TAG_NAME" ] || fail "--tag is required"
[ -n "$RUN_ID" ] || fail "--run-id is required"
[ -n "$DELEGATED_BY" ] || fail "--delegated-by is required"
[ -n "$MODE" ] || fail "--mode is required"
[ -n "$TARGET_REF" ] || fail "--target-ref is required"
[ -x "$BROKERED_TAG_SH" ] || fail "missing executable $BROKERED_TAG_SH"
[ -x "$BASELINE_SH" ] || fail "missing executable $BASELINE_SH"
[ -f "$REGISTRY_JSON" ] || fail "missing $REGISTRY_JSON"

REPO_NAME="${REPO_FULL#Northroot-Labs/}"
[ "$REPO_NAME" != "$REPO_FULL" ] || fail "--repo must look like Northroot-Labs/<repo>"
REPO_DIR="$WORKSPACE_ROOT/repos/$REPO_NAME"
[ -d "$REPO_DIR/.git" ] || fail "local repo clone missing: $REPO_DIR"

case "$MODE" in
  human-cosign)
    [ -n "$CO_SIGNED_BY" ] || fail "--co-signed-by required for mode=human-cosign"
    ;;
  delegated)
    [ -n "$DELEGATED_ACTION" ] || fail "--delegated-action required for mode=delegated"
    ;;
  *)
    fail "--mode must be human-cosign or delegated"
    ;;
esac

if [ -z "$ACTION_SCOPE" ]; then
  ACTION_SCOPE="${TARGET_REF} ${BUCKET} pin"
fi

TAG_ARGS=(
  --tag "$TAG_NAME"
  --scope "$ACTION_SCOPE"
  --run-id "$RUN_ID"
  --delegated-by "$DELEGATED_BY"
  --mode "$MODE"
  --target-ref "$TARGET_REF"
  --title "Checkpoint before baseline checks"
)
if [ "$MODE" = "human-cosign" ]; then
  TAG_ARGS+=(--co-signed-by "$CO_SIGNED_BY")
else
  TAG_ARGS+=(--delegated-action "$DELEGATED_ACTION")
fi

(
  cd "$REPO_DIR"
  if [ "$DO_FETCH" -eq 1 ]; then
    git fetch --prune --tags origin
  fi
  git rev-parse --verify "$TARGET_REF" >/dev/null 2>&1 || fail "target ref not found after fetch: $TARGET_REF"
  "$BROKERED_TAG_SH" "${TAG_ARGS[@]}"
)

TAG_SHA="$(git -C "$REPO_DIR" rev-list -n 1 "$TAG_NAME")"
[ -n "$TAG_SHA" ] || fail "unable to resolve sha for tag $TAG_NAME"

python3 - "$REGISTRY_JSON" "$REPO_FULL" "$BUCKET" "$TAG_NAME" "$TAG_SHA" <<'PY'
import json
import sys
from pathlib import Path

registry_path = Path(sys.argv[1])
repo_full = sys.argv[2]
bucket = sys.argv[3]
tag = sys.argv[4]
sha = sys.argv[5]

with registry_path.open("r", encoding="utf-8") as f:
    data = json.load(f)

repos = data.get("repos", {})
if repo_full not in repos:
    raise SystemExit(f"repo not present in registry: {repo_full}")

pins = repos[repo_full].setdefault("pins", {})
pins[bucket] = {"tag": tag, "sha": sha}

with registry_path.open("w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY

"$BASELINE_SH" schema
"$BASELINE_SH" verify-tags

echo "Promoted baseline pin:"
echo "  repo:   $REPO_FULL"
echo "  bucket: $BUCKET"
echo "  tag:    $TAG_NAME"
echo "  sha:    $TAG_SHA"
