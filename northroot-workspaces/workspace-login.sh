#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR="${NORTHROOT_WORKSPACE_DIR:-$HOME/Northroot-Labs}"
KEY_PATH="${NORTHROOT_SIGNING_KEY_PATH:-$HOME/.ssh/northroot_workspaces_signing}"
TTL_HOURS="${NORTHROOT_SIGNING_TTL_HOURS:-8}"
SESSION_TTL_HOURS="${NORTHROOT_WORKSPACE_SESSION_TTL_HOURS:-8}"

usage() {
  cat <<'EOF'
Usage: workspace-login.sh [--workspace-dir PATH] [--key-path PATH] [--ttl-hours N] [--session-ttl-hours N]

Unlocks SSH signing key and mints a bounded workspace session for brokered tag operations.
EOF
}

fail() {
  echo "error: $1" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --workspace-dir) WORKSPACE_DIR="${2:-}"; shift 2 ;;
    --key-path) KEY_PATH="${2:-}"; shift 2 ;;
    --ttl-hours) TTL_HOURS="${2:-}"; shift 2 ;;
    --session-ttl-hours) SESSION_TTL_HOURS="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown arg: $1" ;;
  esac
done

[ -d "$WORKSPACE_DIR" ] || fail "workspace dir not found: $WORKSPACE_DIR"
[ -f "$KEY_PATH" ] || fail "key not found: $KEY_PATH"

if [ "$(uname -s)" = "Darwin" ]; then
  ssh-add --apple-use-keychain "$KEY_PATH"
else
  ssh-add "$KEY_PATH"
fi
ssh-add -t "${TTL_HOURS}h" "$KEY_PATH" >/dev/null

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/northroot-workspaces"
SESSION_FILE="$CONFIG_DIR/workspace-session.env"
mkdir -p "$CONFIG_DIR"

NOW="$(date +%s)"
EXPIRES="$((NOW + (SESSION_TTL_HOURS * 3600)))"
WORKSPACE_REAL="$(cd "$WORKSPACE_DIR" && pwd -P)"

umask 077
cat > "$SESSION_FILE" <<EOF
NORTHROOT_WORKSPACE_LOGIN=1
NORTHROOT_WORKSPACE_LOGIN_ISSUED_AT=$NOW
NORTHROOT_WORKSPACE_LOGIN_EXPIRES_AT=$EXPIRES
NORTHROOT_WORKSPACE_LOGIN_USER=$USER
NORTHROOT_WORKSPACE_LOGIN_WORKSPACE=$WORKSPACE_REAL
EOF

echo "Workspace login granted."
echo "Session file: $SESSION_FILE"
echo "Expires epoch: $EXPIRES"
