#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: brokered-tag.sh --tag NAME --scope TEXT --run-id ID --delegated-by HUMAN --mode human-cosign|delegated [--target-ref REF] [--co-signed-by TEXT] [--delegated-action TEXT] [--title TEXT]

Creates a signed annotated checkpoint tag with brokered metadata trailers.
EOF
}

fail() {
  echo "error: $1" >&2
  exit 1
}

TAG_NAME=""
ACTION_SCOPE=""
RUN_ID=""
DELEGATED_BY=""
MODE=""
CO_SIGNED_BY=""
DELEGATED_ACTION=""
TITLE="Checkpoint"
TARGET_REF="HEAD"

while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG_NAME="${2:-}"; shift 2 ;;
    --scope) ACTION_SCOPE="${2:-}"; shift 2 ;;
    --run-id) RUN_ID="${2:-}"; shift 2 ;;
    --delegated-by) DELEGATED_BY="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --target-ref) TARGET_REF="${2:-}"; shift 2 ;;
    --co-signed-by) CO_SIGNED_BY="${2:-}"; shift 2 ;;
    --delegated-action) DELEGATED_ACTION="${2:-}"; shift 2 ;;
    --title) TITLE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown arg: $1" ;;
  esac
done

[ -n "$TAG_NAME" ] || fail "--tag required"
[ -n "$ACTION_SCOPE" ] || fail "--scope required"
[ -n "$RUN_ID" ] || fail "--run-id required"
[ -n "$DELEGATED_BY" ] || fail "--delegated-by required"
[ -n "$MODE" ] || fail "--mode required"
[ -n "$TARGET_REF" ] || fail "--target-ref required"

SESSION_FILE="$(git config --path northroot.workspaceSessionFile || echo "${XDG_CONFIG_HOME:-$HOME/.config}/northroot-workspaces/workspace-session.env")"
[ -f "$SESSION_FILE" ] || fail "workspace login required (missing $SESSION_FILE)"

# shellcheck disable=SC1090
. "$SESSION_FILE"

[ "${NORTHROOT_WORKSPACE_LOGIN:-0}" = "1" ] || fail "workspace login required"
NOW="$(date +%s)"
[ "${NORTHROOT_WORKSPACE_LOGIN_EXPIRES_AT:-0}" -gt "$NOW" ] || fail "workspace login expired"

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

git rev-parse --verify "$TARGET_REF" >/dev/null 2>&1 || fail "target ref not found: $TARGET_REF"
if git rev-parse --verify "refs/tags/$TAG_NAME" >/dev/null 2>&1; then
  fail "tag already exists: $TAG_NAME"
fi

MESSAGE="$TITLE

Agent-Brokered: true
Delegation-Mode: $MODE
Delegated-By: $DELEGATED_BY
Broker-Run-Id: $RUN_ID
Action-Scope: $ACTION_SCOPE"

if [ "$MODE" = "human-cosign" ]; then
  MESSAGE="$MESSAGE
Co-Signed-By: $CO_SIGNED_BY"
else
  MESSAGE="$MESSAGE
Delegated-Action: $DELEGATED_ACTION"
fi

git tag -s "$TAG_NAME" "$TARGET_REF" -m "$MESSAGE"
echo "Created signed annotated tag: $TAG_NAME"
