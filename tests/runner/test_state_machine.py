"""Test state machine transition guards."""

import pytest
from runner.contracts import RunState, StepState, ErrorClass, StepDefinition, PIPELINE_STEPS
from runner.state_machine import (
    RunStateMachine,
    StepStateMachine,
    RetryPolicy,
    PipelineDAG,
)


# ─── Run State Machine Tests ────────────────────────────────────────────────

def test_run_state_valid_transitions():
    """Test valid run state transitions."""
    sm = RunStateMachine()
    
    # Happy path
    assert sm.can_transition(RunState.CREATED, RunState.PREFLIGHT_VALIDATED)
    assert sm.can_transition(RunState.PREFLIGHT_VALIDATED, RunState.EXECUTING)
    assert sm.can_transition(RunState.EXECUTING, RunState.SUCCEEDED)
    
    # Failure path
    assert sm.can_transition(RunState.CREATED, RunState.FAILED)
    assert sm.can_transition(RunState.EXECUTING, RunState.FAILED)
    
    # Blocked -> resume
    assert sm.can_transition(RunState.EXECUTING, RunState.BLOCKED)
    assert sm.can_transition(RunState.BLOCKED, RunState.EXECUTING)


def test_run_state_invalid_transitions():
    """Test invalid run state transitions (fail-closed)."""
    sm = RunStateMachine()
    
    # Cannot skip states
    assert not sm.can_transition(RunState.CREATED, RunState.EXECUTING)
    assert not sm.can_transition(RunState.CREATED, RunState.SUCCEEDED)
    
    # Terminal states
    assert not sm.can_transition(RunState.SUCCEEDED, RunState.EXECUTING)
    assert not sm.can_transition(RunState.ROLLED_BACK, RunState.EXECUTING)
    
    # Cannot go backwards (except compensation)
    assert not sm.can_transition(RunState.EXECUTING, RunState.CREATED)


def test_run_state_validate_raises():
    """Test validation raises on invalid transitions."""
    sm = RunStateMachine()
    
    with pytest.raises(ValueError, match="Invalid run state transition"):
        sm.validate_transition(RunState.CREATED, RunState.SUCCEEDED)


# ─── Step State Machine Tests ───────────────────────────────────────────────

def test_step_state_valid_transitions():
    """Test valid step state transitions."""
    sm = StepStateMachine()
    
    # Normal execution
    assert sm.can_transition(StepState.PENDING, StepState.RUNNING)
    assert sm.can_transition(StepState.RUNNING, StepState.SUCCEEDED)
    
    # Failure -> retry
    assert sm.can_transition(StepState.RUNNING, StepState.FAILED)
    assert sm.can_transition(StepState.FAILED, StepState.RUNNING)
    
    # Skip downstream after hard gate failure
    assert sm.can_transition(StepState.PENDING, StepState.SKIPPED)


def test_step_state_terminal():
    """Test terminal step states."""
    sm = StepStateMachine()
    
    assert not sm.can_transition(StepState.SUCCEEDED, StepState.RUNNING)
    assert not sm.can_transition(StepState.SKIPPED, StepState.RUNNING)
    assert not sm.can_transition(StepState.COMPENSATED, StepState.RUNNING)


# ─── Retry Policy Tests ──────────────────────────────────────────────────────

def test_retry_policy_transient_io():
    """Test transient I/O retry policy."""
    step = StepDefinition(
        step_id="stage_data_layout",
        name="Stage data layout",
        max_retries=3,
        retry_classes=[ErrorClass.TRANSIENT_IO],
    )
    
    # Allows retry for transient errors
    assert RetryPolicy.allows_retry(step, ErrorClass.TRANSIENT_IO, 0)
    assert RetryPolicy.allows_retry(step, ErrorClass.TRANSIENT_IO, 2)
    
    # Exceeds max retries
    assert not RetryPolicy.allows_retry(step, ErrorClass.TRANSIENT_IO, 3)


def test_retry_policy_hard_gate_no_retry():
    """Test hard gates don't retry on gate failure."""
    step = StepDefinition(
        step_id="phase_benchmark",
        name="Phase benchmark",
        is_hard_gate=True,
        max_retries=2,
    )
    
    # Hard gate failure: no retry
    assert not RetryPolicy.allows_retry(step, ErrorClass.HARD_GATE_FAILED, 0)
    
    # Transient error on hard gate: can retry (infrastructure issue)
    assert RetryPolicy.allows_retry(step, ErrorClass.TRANSIENT_IO, 0)


def test_retry_policy_contract_missing_no_retry():
    """Test contract input missing never retries."""
    step = StepDefinition(
        step_id="build_steward_bundle",
        name="Build steward bundle",
        max_retries=3,
        retry_classes=[ErrorClass.TRANSIENT_IO],
    )
    
    assert not RetryPolicy.allows_retry(step, ErrorClass.CONTRACT_INPUT_MISSING, 0)


def test_backoff_exponential():
    """Test exponential backoff calculation."""
    # Attempt 0: ~2s
    delay0 = RetryPolicy.backoff_seconds(0, base=2.0)
    assert 2.0 <= delay0 <= 2.2
    
    # Attempt 1: ~4s
    delay1 = RetryPolicy.backoff_seconds(1, base=2.0)
    assert 4.0 <= delay1 <= 4.4
    
    # Attempt 2: ~8s
    delay2 = RetryPolicy.backoff_seconds(2, base=2.0)
    assert 8.0 <= delay2 <= 8.8


def test_backoff_max_delay():
    """Test backoff respects max delay."""
    # Attempt 10 would be 2048s without cap
    delay = RetryPolicy.backoff_seconds(10, base=2.0, max_delay=60.0)
    assert delay <= 66.0  # max + 10% jitter


# ─── Pipeline DAG Tests ──────────────────────────────────────────────────────

def test_dag_step_order():
    """Test DAG preserves step order."""
    dag = PipelineDAG()
    
    assert dag.order[0] == "preflight_contract_check"
    assert dag.order[1] == "phase_benchmark"
    assert dag.order[-1] == "publish_internal"


def test_dag_upstream_dependencies():
    """Test upstream dependency calculation."""
    dag = PipelineDAG()
    
    # First step has no upstream
    assert dag.get_upstream_steps("preflight_contract_check") == []
    
    # Second step depends on first
    upstream = dag.get_upstream_steps("phase_benchmark")
    assert upstream == ["preflight_contract_check"]
    
    # Last step depends on all previous
    upstream = dag.get_upstream_steps("publish_internal")
    assert len(upstream) == 7
    assert upstream[0] == "preflight_contract_check"


def test_dag_downstream_steps():
    """Test downstream step calculation."""
    dag = PipelineDAG()
    
    # First step blocks all downstream
    downstream = dag.get_downstream_steps("preflight_contract_check")
    assert len(downstream) == 7
    
    # Last step has no downstream
    assert dag.get_downstream_steps("publish_internal") == []


def test_dag_can_execute_happy_path():
    """Test step execution gating - happy path."""
    dag = PipelineDAG()
    
    completed = set()
    failed_gates = set()
    
    # First step always executable
    can_exec, reason = dag.can_execute_step("preflight_contract_check", completed, failed_gates)
    assert can_exec is True
    
    # Second step requires first
    can_exec, reason = dag.can_execute_step("phase_benchmark", completed, failed_gates)
    assert can_exec is False
    assert "Missing upstream" in reason
    
    # After first completes
    completed.add("preflight_contract_check")
    can_exec, reason = dag.can_execute_step("phase_benchmark", completed, failed_gates)
    assert can_exec is True


def test_dag_fail_closed_hard_gate():
    """Test fail-closed: hard gate failure blocks downstream."""
    dag = PipelineDAG()
    
    completed = {"preflight_contract_check"}
    failed_gates = {"phase_benchmark"}  # hard gate failed
    
    # Downstream step blocked
    can_exec, reason = dag.can_execute_step("stage_data_layout", completed, failed_gates)
    assert can_exec is False
    assert "failed hard gate" in reason.lower()
    
    # Further downstream also blocked
    can_exec, reason = dag.can_execute_step("build_minimal_deliverable", completed, failed_gates)
    assert can_exec is False


def test_dag_partial_completion():
    """Test partial pipeline completion."""
    dag = PipelineDAG()
    
    completed = {
        "preflight_contract_check",
        "phase_benchmark",
        "stage_data_layout",
    }
    failed_gates = set()
    
    # Next step can execute
    can_exec, _ = dag.can_execute_step("build_steward_bundle", completed, failed_gates)
    assert can_exec is True
    
    # Cannot skip ahead
    can_exec, reason = dag.can_execute_step("verify_artifacts", completed, failed_gates)
    assert can_exec is False
    assert "Missing upstream" in reason
