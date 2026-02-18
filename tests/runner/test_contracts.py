"""Test event contracts and compact schema."""

import json
from runner.contracts import (
    Event,
    EventType,
    Actor,
    ErrorClass,
    RunState,
    StepState,
    run_created,
    run_state_changed,
    step_started,
    step_succeeded,
    step_failed,
    gate_failed,
    StepDefinition,
)


def test_event_compact_schema():
    """Verify compact schema omits null fields."""
    event = Event(
        event_id="evt_123",
        event_type=EventType.STEP_STARTED,
        run_id="run_abc",
        timestamp_utc="2026-02-16T23:00:00Z",
        actor=Actor.RUNNER,
        step_id="preflight_contract_check",
        attempt=0,
    )
    
    data = event.to_dict()
    
    # Required compact fields present
    assert data["event_id"] == "evt_123"
    assert data["event_type"] == "step.started"
    assert data["run_id"] == "run_abc"
    assert data["step_id"] == "preflight_contract_check"
    assert data["attempt"] == 0
    assert data["actor"] == "runner"
    
    # Null optional fields omitted
    assert "error_class" not in data
    assert "reason" not in data
    assert "inputs_hash" not in data


def test_event_with_error_fields():
    """Verify error fields included when present."""
    event = step_failed(
        run_id="run_123",
        step_id="phase_benchmark",
        error_class=ErrorClass.HARD_GATE_FAILED,
        reason="Benchmark threshold not met: 95.2% < 97%",
        attempt=0,
    )
    
    data = event.to_dict()
    
    assert data["event_type"] == "step.failed"
    assert data["error_class"] == "hard_gate_failed"
    assert data["reason"] == "Benchmark threshold not met: 95.2% < 97%"
    assert data["new_state"] == "failed"


def test_event_serialization_compact():
    """Verify JSON serialization is compact (no spaces)."""
    event = step_started("run_123", "preflight_contract_check", attempt=0)
    
    line = json.dumps(event.to_dict(), separators=(',', ':'))
    
    # Compact: no spaces after separators
    assert ': ' not in line
    assert ', ' not in line
    
    # Can deserialize
    data = json.loads(line)
    assert data["step_id"] == "preflight_contract_check"


def test_run_created_event():
    """Test run creation event."""
    event = run_created("run_abc", reason="Manual trigger")
    
    data = event.to_dict()
    assert data["event_type"] == "run.created"
    assert data["run_id"] == "run_abc"
    assert data["new_state"] == "created"
    assert data["reason"] == "Manual trigger"


def test_run_state_changed_event():
    """Test run state transition event."""
    event = run_state_changed(
        "run_abc",
        RunState.CREATED,
        RunState.PREFLIGHT_VALIDATED,
        reason="Preflight checks passed",
    )
    
    data = event.to_dict()
    assert data["event_type"] == "run.state_changed"
    assert data["previous_state"] == "created"
    assert data["new_state"] == "preflight_validated"


def test_gate_failed_event():
    """Test hard gate failure event."""
    event = gate_failed(
        "run_123",
        "phase_benchmark",
        ErrorClass.HARD_GATE_FAILED,
        "Accuracy 95.2% below threshold 97%",
    )
    
    data = event.to_dict()
    assert data["event_type"] == "gate.failed"
    assert data["step_id"] == "phase_benchmark"
    assert data["error_class"] == "hard_gate_failed"
    assert "Accuracy" in data["reason"]


def test_step_definition_retry_policy():
    """Test step retry policy."""
    step = StepDefinition(
        step_id="stage_data_layout",
        name="Stage data layout",
        max_retries=3,
        retry_classes=[ErrorClass.TRANSIENT_IO],
    )
    
    # Transient error within retry limit
    assert step.allows_retry(ErrorClass.TRANSIENT_IO, 0) is True
    assert step.allows_retry(ErrorClass.TRANSIENT_IO, 2) is True
    
    # Exceeded max retries
    assert step.allows_retry(ErrorClass.TRANSIENT_IO, 3) is False
    
    # Non-retriable error class
    assert step.allows_retry(ErrorClass.CONTRACT_INPUT_MISSING, 0) is False


def test_hard_gate_no_retry():
    """Test hard gates don't retry by default."""
    step = StepDefinition(
        step_id="preflight_contract_check",
        name="Preflight check",
        is_hard_gate=True,
        max_retries=0,
    )
    
    assert step.allows_retry(ErrorClass.HARD_GATE_FAILED, 0) is False
    assert step.allows_retry(ErrorClass.VALIDATION_FAILED, 0) is False
