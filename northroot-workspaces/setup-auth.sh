#!/usr/bin/env bash
# Optional first-time auth bootstrap for workspace signing/session.
# This is intentionally non-default. Run explicitly when needed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_SH="$SCRIPT_DIR/bootstrap-signing.sh"
LOGIN_SH="$SCRIPT_DIR/workspace-login.sh"

usage() {
  cat <<'EOF'
Usage: setup-auth.sh <command> [args...]

Commands:
  status                         Show ssh-agent keys and workspace session status.
  bootstrap [bootstrap args]     Run bootstrap-signing.sh (key + signing config prep).
  login [login args]             Run workspace-login.sh (time-bounded session token).

Examples:
  ./northroot-workspaces/setup-auth.sh status
  ./northroot-workspaces/setup-auth.sh bootstrap --workspace-dir "$HOME/Northroot-Labs"
  ./northroot-workspaces/setup-auth.sh login --workspace-dir "$HOME/Northroot-Labs"
EOF
}

cmd="${1:-}"
[[ -n "$cmd" ]] || { usage; exit 1; }
shift || true

case "$cmd" in
  status)
    echo "ssh-agent identities:"
    ssh-add -l 2>&1 || true
    SESSION_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/northroot-workspaces/workspace-session.env"
    if [[ -f "$SESSION_FILE" ]]; then
      echo "workspace session file: $SESSION_FILE"
      # shellcheck disable=SC1090
      . "$SESSION_FILE"
      now="$(date +%s)"
      exp="${NORTHROOT_WORKSPACE_LOGIN_EXPIRES_AT:-0}"
      if [[ "$exp" -gt "$now" ]]; then
        echo "workspace session: active (expires $exp)"
      else
        echo "workspace session: expired"
      fi
    else
      echo "workspace session: not found ($SESSION_FILE)"
    fi
    ;;
  bootstrap)
    "$BOOTSTRAP_SH" "$@"
    ;;
  login)
    "$LOGIN_SH" "$@"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "unknown command: $cmd" >&2
    usage
    exit 1
    ;;
esac
