# Pipeline Runner — Fail-Closed, Event-Sourced Orchestration

Deterministic pipeline runner with fail-closed semantics, event sourcing, and resumability.

## Features

- **Fail-closed by default**: Hard gate failures block downstream steps
- **Event-sourced**: Append-only JSONL event log for full auditability
- **Resumable**: Reconstruct state from events and continue from last checkpoint
- **Retry policies**: Exponential backoff for transient errors, bounded retries
- **Streaming-friendly**: Events flushed for `tail -f` and SSE consumption
- **Compact events**: Optimized for low token cost in AI/automation consumers

## Architecture

### State Machine

**Run states**:
- `created` → `preflight_validated` → `executing` → `succeeded` | `failed` | `blocked`
- Terminal: `succeeded`, `failed`, `rolled_back`

**Step states**:
- `pending` → `running` → `succeeded` | `failed` | `compensated` | `skipped`

### Event Types

Core events (compact schema):
- `run.created`, `run.state_changed`, `run.completed`
- `step.started`, `step.succeeded`, `step.failed`, `step.retried`
- `gate.failed` (hard gate failure)
- `artifact.emitted`

Required fields: `event_id`, `event_type`, `run_id`, `timestamp_utc`, `actor`, `attempt`

Optional fields: `step_id`, `error_class`, `reason`, `inputs_hash`, `outputs_hash`

### Pipeline DAG

Ordered steps with upstream/downstream dependencies:
1. `preflight_contract_check` (hard gate)
2. `phase_benchmark` (hard gate)
3. `stage_data_layout`
4. `build_steward_bundle`
5. `validate_bundle_quality` (hard gate)
6. `build_minimal_deliverable`
7. `verify_artifacts` (hard gate)
8. `publish_internal` (manual-gated)

## Usage

### Programmatic API

```python
from pathlib import Path
from runner.executor import PipelineExecutor
from runner.contracts import StepDefinition, ErrorClass

# Define steps
def preflight_check(ctx, step_id):
    # Validation logic
    if not inputs_valid:
        return False, ErrorClass.CONTRACT_INPUT_MISSING, "Missing input file"
    return True, None, None

step_functions = {
    "preflight_contract_check": preflight_check,
    # ... more steps
}

# Execute
run_dir = Path("runs/run_abc")
executor = PipelineExecutor(run_dir, step_functions)

ctx = executor.start("run_abc", reason="Manual trigger")
final_state = executor.execute(ctx)

print(f"Run ended: {final_state.value}")
```

### Resume After Interruption

```python
from runner.resume import resume_run

# Reconstruct state from event log
ctx = resume_run(Path("runs/run_abc"))

# Continue execution
executor = PipelineExecutor(run_dir, step_functions)
final_state = executor.resume(ctx)
```

### CLI

```bash
# Check run status
runner status runs/run_abc

# View events (streaming)
runner events runs/run_abc --tail 20
runner events runs/run_abc --follow

# Generate summary
runner summary runs/run_abc
runner summary runs/run_abc --json

# Check resumability
runner resume runs/run_abc
```

## Event Log

**Location**: `<run_dir>/events.jsonl`

**Format**: JSON Lines (one event per line)

**Characteristics**:
- Append-only (immutable)
- Flushed after each write (visible to `tail -f`)
- Compact encoding (no whitespace)
- Omits null fields

**Example event**:

```json
{"event_id":"evt_456","event_type":"gate.failed","run_id":"run_abc","timestamp_utc":"2026-02-16T23:05:12Z","actor":"runner","attempt":0,"step_id":"phase_benchmark","error_class":"hard_gate_failed","reason":"Accuracy 95.2% below threshold 97%"}
```

**Consumption patterns**:

```bash
# Watch for failures
tail -f events.jsonl | grep '"event_type":"step.failed"'

# Extract compact status
tail -n 50 events.jsonl | jq -c '{type:.event_type,step:.step_id,error:.error_class,reason:.reason}'
```

## Retry Policy

**Error classes**:
- `transient_io`: Retry with exponential backoff (configurable max retries)
- `contract_input_missing`: No retry (immediate failure)
- `hard_gate_failed`: No retry (unless manual override)
- `validation_failed`: No retry

**Backoff**: Exponential with jitter (base 2s, max 60s, 10% jitter)

**Example**:

```python
StepDefinition(
    "stage_data_layout",
    "Stage data layout",
    max_retries=3,
    retry_classes=[ErrorClass.TRANSIENT_IO],
)
```

## Fail-Closed Semantics

**Hard gate failure** → All downstream steps skipped → Run `failed`

```
preflight ✓ → benchmark ✗ (hard gate) → [stage_data ⊘, build ⊘, ...] → FAILED
```

**Non-hard-gate failure** → Continue to next step (logged but not blocking)

**Override** (future): Explicit flag + `run.override_applied` event with reason

## Run Summary

**Programmatic**:

```python
from runner.summary import generate_summary

summary = generate_summary(Path("runs/run_abc"))
print(summary.to_text())  # Human-readable
data = summary.to_dict()  # Machine-readable
```

**Example output**:

```
Run Summary: run_abc
============================================================
Status: ✗ FAILED
Created: 2026-02-16T23:00:00Z
Completed: 2026-02-16T23:05:12Z
Duration: 312.45s

Steps: 8 total (2 completed, 1 failed, 5 skipped)
Retries: 0
Hard gate failures: phase_benchmark

Steps:
------------------------------------------------------------
  ✓ preflight_contract_check        succeeded
  ✗ phase_benchmark                 failed
      Error: Accuracy 95.2% below threshold 97%
  ⊘ stage_data_layout               skipped
  ...
```

## Testing

```bash
# Run all tests
pytest tests/runner/ -v

# Coverage breakdown
pytest tests/runner/test_contracts.py       # 8 tests
pytest tests/runner/test_state_machine.py   # 16 tests
pytest tests/runner/test_event_log.py       # 8 tests
pytest tests/runner/test_executor.py        # 7 tests
pytest tests/runner/test_resume.py          # 13 tests
pytest tests/runner/test_summary.py         # 8 tests
pytest tests/runner/test_cli.py             # 8 tests
```

**Total: 68 tests passing**

## Design Decisions

1. **Compact events**: Null fields omitted to reduce token cost (~25% savings for AI consumers)
2. **Streaming-first**: Events flushed immediately for real-time monitoring
3. **Resume guards**: Prevent invalid resumption (terminal states, hard gate failures)
4. **Event replay**: Full state reconstruction from event log (no hidden state)
5. **Fail-closed**: Invalid transitions raise exceptions; unknown states blocked
6. **Explicit retry**: Retry policy at step definition level with error classification
7. **No magic**: All state transitions logged; no implicit compensation

## Future Extensions

- **Compensation handlers**: Per-step rollback logic
- **Manual gates**: Pause for approval with `run.blocked` → `run.executing` transition
- **Artifact tracking**: Hash verification and quarantine for incomplete outputs
- **Distributed tracing**: Span IDs for cross-service correlation
- **Override policies**: Manual override with mandatory reason and approval event
- **Metrics export**: Prometheus metrics for run duration, retry counts, failure rates

## Files

```
runner/
├── __init__.py           # Package init
├── contracts.py          # Event & step schemas (compact)
├── state_machine.py      # Transition guards & retry policy
├── event_log.py          # Append-only JSONL writer
├── executor.py           # Pipeline orchestration
├── resume.py             # State reconstruction & resume guards
├── summary.py            # Run summary generation
├── cli.py                # CLI interface
└── README.md             # This file

tests/runner/
├── test_contracts.py
├── test_state_machine.py
├── test_event_log.py
├── test_executor.py
├── test_resume.py
├── test_summary.py
└── test_cli.py

docs/
└── STREAMING.md          # Streaming patterns & AI consumption
```

## References

- **PR**: Design and implement fail-closed pipeline runner
- **Streaming guide**: `docs/STREAMING.md`
- **Event contract**: `runner/contracts.py`
