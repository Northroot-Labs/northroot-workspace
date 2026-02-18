"""Test event log streaming and append-only semantics."""

import json
import tempfile
from pathlib import Path

from runner.contracts import step_started, step_succeeded, step_failed, ErrorClass
from runner.event_log import EventLog


def test_event_log_append():
    """Test event log append operation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "run_123" / "events.jsonl"
        log = EventLog(log_path)
        
        # Directory created
        assert log_path.parent.exists()
        assert log_path.exists()
        
        # Append events
        event1 = step_started("run_123", "preflight_contract_check", attempt=0)
        event2 = step_succeeded("run_123", "preflight_contract_check", attempt=0)
        
        log.append(event1)
        log.append(event2)
        
        # Read raw file
        lines = log_path.read_text().strip().split('\n')
        assert len(lines) == 2
        
        # Verify JSONL format
        data1 = json.loads(lines[0])
        assert data1["step_id"] == "preflight_contract_check"
        assert data1["event_type"] == "step.started"


def test_event_log_compact_jsonl():
    """Test JSONL lines are compact (no spaces)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "events.jsonl"
        log = EventLog(log_path)
        
        event = step_failed(
            "run_123",
            "phase_benchmark",
            ErrorClass.HARD_GATE_FAILED,
            "Benchmark failed",
            attempt=0,
        )
        log.append(event)
        
        line = log_path.read_text().strip()
        
        # Compact: no spaces after separators
        assert ': ' not in line
        assert ', ' not in line
        
        # Valid JSON
        data = json.loads(line)
        assert data["error_class"] == "hard_gate_failed"


def test_event_log_streaming_safe():
    """Test append is streaming-safe (flushed)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "events.jsonl"
        log = EventLog(log_path)
        
        # Append event
        event = step_started("run_123", "preflight_contract_check")
        log.append(event)
        
        # Should be immediately visible (flushed)
        # Simulate tail -f by opening in read mode
        with open(log_path, 'r') as f:
            line = f.readline()
            data = json.loads(line)
            assert data["step_id"] == "preflight_contract_check"


def test_event_log_read_all():
    """Test reading all events from log."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "events.jsonl"
        log = EventLog(log_path)
        
        # Append multiple events
        for i in range(5):
            event = step_started("run_123", f"step_{i}")
            log.append(event)
        
        # Read all
        events = log.read_all()
        assert len(events) == 5
        assert events[0]["step_id"] == "step_0"
        assert events[4]["step_id"] == "step_4"


def test_event_log_tail():
    """Test tail functionality (last N events)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "events.jsonl"
        log = EventLog(log_path)
        
        # Append 10 events
        for i in range(10):
            event = step_started("run_123", f"step_{i}")
            log.append(event)
        
        # Tail last 3
        tail = log.tail(n=3)
        assert len(tail) == 3
        assert tail[0]["step_id"] == "step_7"
        assert tail[2]["step_id"] == "step_9"


def test_event_log_empty():
    """Test reading empty log."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "events.jsonl"
        log = EventLog(log_path)
        
        events = log.read_all()
        assert events == []
        
        tail = log.tail(n=5)
        assert tail == []


def test_event_log_stream_handle():
    """Test stream() returns file handle for SSE bridge."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "events.jsonl"
        log = EventLog(log_path)
        
        # Append events
        log.append(step_started("run_123", "step_1"))
        log.append(step_succeeded("run_123", "step_1"))
        
        # Open stream
        handle = log.stream(follow=False)
        
        try:
            # Read first line
            line = handle.readline()
            data = json.loads(line)
            assert data["event_type"] == "step.started"
            
            # Read second line
            line = handle.readline()
            data = json.loads(line)
            assert data["event_type"] == "step.succeeded"
        finally:
            handle.close()


def test_event_log_append_only_immutable():
    """Test events are append-only (no modification of existing events)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "events.jsonl"
        log = EventLog(log_path)
        
        # Append initial event
        event1 = step_started("run_123", "step_1")
        log.append(event1)
        
        # Read initial content
        initial_content = log_path.read_text()
        
        # Append another event
        event2 = step_succeeded("run_123", "step_1")
        log.append(event2)
        
        # Verify first event unchanged
        current_content = log_path.read_text()
        assert current_content.startswith(initial_content)
        
        # Verify append-only
        lines = current_content.strip().split('\n')
        assert len(lines) == 2
