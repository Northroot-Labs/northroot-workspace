#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR="${NORTHROOT_WORKSPACE_DIR:-$HOME/Northroot-Labs}"
KEY_PATH="${NORTHROOT_SIGNING_KEY_PATH:-$HOME/.ssh/northroot_workspaces_signing}"
TTL_HOURS="${NORTHROOT_SIGNING_TTL_HOURS:-8}"
SESSION_TTL_HOURS="${NORTHROOT_WORKSPACE_SESSION_TTL_HOURS:-8}"
INSTALL_GLOBAL_INCLUDE=0
UPLOAD_GH_SIGNING_KEY=0

usage() {
  cat <<'EOF'
Usage: bootstrap-signing.sh [--workspace-dir PATH] [--key-path PATH] [--ttl-hours N] [--session-ttl-hours N] [--install-global-include] [--upload-gh-signing-key]

Bootstraps workspace-scoped SSH commit/tag signing for Northroot-Labs.
EOF
}

fail() {
  echo "error: $1" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --workspace-dir) WORKSPACE_DIR="${2:-}"; shift 2 ;;
    --key-path) KEY_PATH="${2:-}"; shift 2 ;;
    --ttl-hours) TTL_HOURS="${2:-}"; shift 2 ;;
    --session-ttl-hours) SESSION_TTL_HOURS="${2:-}"; shift 2 ;;
    --install-global-include) INSTALL_GLOBAL_INCLUDE=1; shift ;;
    --upload-gh-signing-key) UPLOAD_GH_SIGNING_KEY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown arg: $1" ;;
  esac
done

require_cmd git
require_cmd ssh-keygen
require_cmd ssh-add

[ -d "$WORKSPACE_DIR" ] || fail "workspace dir not found: $WORKSPACE_DIR"
mkdir -p "$(dirname "$KEY_PATH")"

if [ ! -f "$KEY_PATH" ]; then
  COMMENT="northroot-workspaces-signing-$(date +%Y%m%d)"
  echo "Generating signing key: $KEY_PATH"
  ssh-keygen -t ed25519 -a 64 -f "$KEY_PATH" -C "$COMMENT"
fi

if [ "$(uname -s)" = "Darwin" ]; then
  ssh-add --apple-use-keychain "$KEY_PATH"
else
  ssh-add "$KEY_PATH"
fi
ssh-add -t "${TTL_HOURS}h" "$KEY_PATH" >/dev/null

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/northroot-workspaces"
mkdir -p "$CONFIG_DIR"
SESSION_FILE="$CONFIG_DIR/workspace-session.env"

WORKSPACE_REAL="$(cd "$WORKSPACE_DIR" && pwd -P)"
GITCONFIG_WORKSPACE="$HOME/.gitconfig-northroot-workspaces"
cat > "$GITCONFIG_WORKSPACE" <<EOF
[gpg]
    format = ssh
[user]
    signingkey = ${KEY_PATH}.pub
[commit]
    gpgsign = true
[tag]
    gpgSign = true
[northroot]
    workspace = $WORKSPACE_REAL
    workspaceSessionFile = $SESSION_FILE
EOF

if [ "$INSTALL_GLOBAL_INCLUDE" -eq 1 ]; then
  touch "$HOME/.gitconfig"
  if ! grep -F "path = ~/.gitconfig-northroot-workspaces" "$HOME/.gitconfig" >/dev/null 2>&1; then
    {
      echo
      echo "[includeIf \"gitdir:${WORKSPACE_REAL%/}/\"]"
      echo "    path = ~/.gitconfig-northroot-workspaces"
    } >> "$HOME/.gitconfig"
  fi
fi

if [ "$UPLOAD_GH_SIGNING_KEY" -eq 1 ] && command -v gh >/dev/null 2>&1; then
  if gh auth status >/dev/null 2>&1; then
    TITLE="northroot-workspaces-signing-$(date +%Y%m%d)"
    gh api /user/ssh_signing_keys -f title="$TITLE" -f key="$(< "${KEY_PATH}.pub")" >/dev/null 2>&1 || true
  fi
fi

echo
echo "Bootstrap complete."
echo "Git config: $GITCONFIG_WORKSPACE"
if [ "$INSTALL_GLOBAL_INCLUDE" -eq 0 ]; then
  echo "Global gitconfig NOT modified (recommended for isolation)."
  echo "If needed, opt in with:"
  echo "  ./northroot-workspaces/bootstrap-signing.sh --install-global-include"
fi
echo "Next: run workspace login to mint session token."
echo "  ./northroot-workspaces/workspace-login.sh --workspace-dir \"$WORKSPACE_DIR\" --key-path \"$KEY_PATH\" --ttl-hours \"$TTL_HOURS\" --session-ttl-hours \"$SESSION_TTL_HOURS\""
