#!/usr/bin/env bash
# Full reproducible build: orchard-core (phased benchmark + steward bundle) then orchard-data (minimal deliverable).
# Run from Northroot-Labs workspace root. Requires repos/orchard-core and repos/orchard-data.
#
# Usage:
#   ./scripts/run_build_and_align.sh
#   ./scripts/run_build_and_align.sh --skip-full-pipeline   # use existing derived data, only build bundle + minimal
#   ./scripts/run_build_and_align.sh --data-root /path/to/orchard-data --core-root /path/to/orchard-core
#   ./scripts/run_build_and_align.sh --raw-input-root /path/to/raw_snapshot_root
set -euo pipefail
WORKSPACE_ROOT="${NORTHROOT_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"
DATA_ROOT="${DATA_ROOT:-$WORKSPACE_ROOT/repos/orchard-data}"
CORE_ROOT="${CORE_ROOT:-$WORKSPACE_ROOT/repos/orchard-core}"
SKIP_FULL=""
ALLOW_BENCHMARK_FAILURE=""
RAW_INPUT_ROOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-root) DATA_ROOT="$2"; shift 2 ;;
    --core-root) CORE_ROOT="$2"; shift 2 ;;
    --skip-full-pipeline) SKIP_FULL=1; shift ;;
    --allow-benchmark-failure) ALLOW_BENCHMARK_FAILURE=1; shift ;;
    --raw-input-root) RAW_INPUT_ROOT="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

DATA_ROOT="$(cd "$DATA_ROOT" && pwd)"
CORE_ROOT="$(cd "$CORE_ROOT" && pwd)"
export BUILD_DATE="${BUILD_DATE:-$(date -u +%Y%m%d)}"
SHORT_SHA=""
if command -v git &>/dev/null; then
  SHORT_SHA="$(git -C "$CORE_ROOT" rev-parse --short HEAD 2>/dev/null || true)"
fi
export CHECKPOINT_ID="${CHECKPOINT_ID:-cp-${BUILD_DATE}-${SHORT_SHA:-unknown}}"
export ORCHARD_DATA_ROOT="$DATA_ROOT"
export ORCHARD_USE_STAGED_LAYOUT=1
export CYCLE="${CYCLE:-2025}"
if [[ -n "$RAW_INPUT_ROOT" ]]; then
  RAW_INPUT_ROOT="$(cd "$RAW_INPUT_ROOT" && pwd)"
  export ORCHARD_RAW_INPUT_ROOT="$RAW_INPUT_ROOT"
fi

echo "BUILD_DATE=$BUILD_DATE CHECKPOINT_ID=$CHECKPOINT_ID"
echo "CORE_ROOT=$CORE_ROOT DATA_ROOT=$DATA_ROOT"
if [[ -n "${ORCHARD_RAW_INPUT_ROOT:-}" ]]; then
  echo "ORCHARD_RAW_INPUT_ROOT=$ORCHARD_RAW_INPUT_ROOT"
fi

# 1) Optional: fail-closed gate + benchmark from orchard-core; writes run logs to orchard_data/derived/runs/<checkpoint_id>/
if [[ -z "$SKIP_FULL" ]]; then
  echo "Running fail-closed preflight + benchmark (orchard-core)..."
  RUNNER_ARGS=(--data-root "$DATA_ROOT" --run-id "$CHECKPOINT_ID")
  if [[ -n "${ORCHARD_RAW_INPUT_ROOT:-}" ]]; then
    RUNNER_ARGS+=(--raw-input-root "$ORCHARD_RAW_INPUT_ROOT")
  fi
  if [[ -n "$ALLOW_BENCHMARK_FAILURE" ]]; then
    RUNNER_ARGS+=(--allow-benchmark-failure)
  fi
  (cd "$CORE_ROOT" && unset ORCHARD_USE_STAGED_LAYOUT && python run_stateful_pipeline.py "${RUNNER_ARGS[@]}")
  echo "Staging layout (legacy -> orchard_data/derived/)..."
  (cd "$CORE_ROOT" && python stage_data_layout.py)
fi

# 2) Steward bundle from orchard-core (reads staged cleaned/extracted, writes to DATA_ROOT/orchard_data/derived/deliverables/)
echo "Building steward bundle (orchard-core)..."
(cd "$CORE_ROOT" && python build_croptrak_steward_bundle.py)

# 3) Minimal deliverable from orchard-data
echo "Building minimal deliverable (orchard-data)..."
"$DATA_ROOT/scripts/run_build_minimal.sh" --cycle "$CYCLE"

echo "Done. Check $DATA_ROOT for minimal_deliverable_*.zip and *.manifest.json"
