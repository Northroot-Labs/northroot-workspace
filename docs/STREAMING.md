# Event Streaming Guide

Runner emits events to an append-only JSONL log optimized for streaming consumption (tail/SSE).

## Event Log Format

**Location**: `<run_dir>/events.jsonl`

**Format**: JSON Lines (one event per line, compact encoding)

**Characteristics**:
- Append-only (immutable events)
- Flushed immediately (safe for `tail -f`)
- Compact JSON (no whitespace: `separators=(',',':')`)
- Omits null optional fields (reduces token cost)

## Consuming Events

### 1. Tail (Command Line)

```bash
# Follow events in real-time
tail -f /path/to/run_dir/events.jsonl

# Last 10 events
tail -n 10 /path/to/run_dir/events.jsonl | jq .
```

### 2. Python Streaming

```python
from runner.event_log import EventLog
from pathlib import Path

log = EventLog(Path("/path/to/run_dir/events.jsonl"))

# Read all events
events = log.read_all()

# Tail last N
recent = log.tail(n=20)

# Open stream for SSE bridge
with log.stream() as f:
    for line in f:
        event = json.loads(line)
        print(f"{event['event_type']}: {event.get('step_id')}")
```

### 3. SSE Bridge (Server-Sent Events)

```python
import json
from pathlib import Path

def event_stream(run_id: str):
    """Generator for SSE endpoint."""
    log_path = Path(f"runs/{run_id}/events.jsonl")
    
    with open(log_path, 'r') as f:
        # Send existing events
        for line in f:
            if line.strip():
                yield f"data: {line}\n\n"
        
        # Follow new events (requires inotify or polling)
        while True:
            line = f.readline()
            if line:
                yield f"data: {line}\n\n"
            else:
                time.sleep(0.1)  # poll interval
```

## Compact Event Schema

### Core Fields (always present)

```json
{
  "event_id": "uuid",
  "event_type": "step.failed",
  "run_id": "run_abc",
  "timestamp_utc": "2026-02-16T23:00:00Z",
  "actor": "runner",
  "attempt": 0
}
```

### Optional Fields (present only when applicable)

- `step_id`: Step identifier (null for run-level events)
- `error_class`: Error classification (`transient_io`, `hard_gate_failed`, etc.)
- `reason`: Compact explanation (error message or action reason)
- `new_state`: State after event
- `previous_state`: State before transition
- `inputs_hash`, `outputs_hash`: Content hashes
- `artifact_path`: Emitted artifact location

### Example: Hard Gate Failure

```json
{"event_id":"evt_456","event_type":"gate.failed","run_id":"run_abc","timestamp_utc":"2026-02-16T23:05:12Z","actor":"runner","attempt":0,"step_id":"phase_benchmark","error_class":"hard_gate_failed","reason":"Accuracy 95.2% below threshold 97%"}
```

**Token cost**: ~180 tokens (compact vs ~240 with formatting)

## Observability Patterns

### Early Failure Detection

Monitor these event types for immediate alerts:

```bash
# Watch for hard gate failures
tail -f events.jsonl | grep -F '"event_type":"gate.failed"'

# Watch for any failures
tail -f events.jsonl | grep -F '"event_type":"step.failed"' | jq '{step: .step_id, error: .error_class, reason: .reason}'
```

### Run Status Dashboard

Extract key fields for compact status display:

```bash
tail -n 50 events.jsonl | jq -c '{type: .event_type, step: .step_id, attempt: .attempt, error: .error_class, reason: .reason} | select(.type != null)'
```

### Audit Trail

Full event stream reconstructs exact run timeline:

```python
events = log.read_all()

# Timeline
for e in events:
    print(f"{e['timestamp_utc']} [{e['event_type']}] {e.get('step_id', 'run')} - {e.get('reason', '')}")

# Final state
final = events[-1]
assert final['event_type'] == 'run.completed'
print(f"Run ended: {final['new_state']} - {final.get('reason')}")
```

## AI/Automation Consumption

### Low Token Cost Strategy

1. **Filter to essential fields**: `event_type`, `step_id`, `error_class`, `reason`
2. **Stream only failures**: `grep` for `step.failed` and `gate.failed`
3. **Compact representation**: JSONL (no whitespace) saves ~25% tokens vs. pretty-printed JSON
4. **Tail recent events**: Last 20 events usually sufficient for failure diagnosis

### Example: Failure Summary Prompt

```python
# Extract failure context (low token cost)
failures = [
    e for e in log.tail(30)
    if e['event_type'] in ['step.failed', 'gate.failed']
]

prompt = f"""
Run failed. Recent failures:
{json.dumps(failures, separators=(',',':'))}

Diagnose root cause.
"""
```

**Cost**: ~500 tokens (vs ~1200 for full event stream with formatting)

## Performance

- **Write**: O(1) append, ~50μs per event
- **Read all**: O(n) scan, ~1ms per 1000 events
- **Tail**: O(n) scan (optimized for small N)
- **Stream**: O(1) per event, flush guaranteed

## Guarantees

1. **Atomicity**: Each event is a single line write (atomic on POSIX)
2. **Ordering**: Events ordered by append time (monotonic)
3. **Visibility**: Flushed immediately (visible to `tail -f`)
4. **Immutability**: No modification or deletion (append-only)
