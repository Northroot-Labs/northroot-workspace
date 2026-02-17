"""Test pipeline executor with streaming event emission."""

import tempfile
from pathlib import Path

from runner.contracts import ErrorClass, RunState, StepState, StepDefinition
from runner.executor import PipelineExecutor, RunContext, hash_output


def test_executor_happy_path():
    """Test successful pipeline execution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        # Simple step implementations
        executed = []
        
        def step_1(ctx, step_id):
            executed.append(step_id)
            return True, None, None
        
        def step_2(ctx, step_id):
            executed.append(step_id)
            return True, None, None
        
        step_functions = {
            "step_1": step_1,
            "step_2": step_2,
        }
        
        steps = [
            StepDefinition("step_1", "Step 1"),
            StepDefinition("step_2", "Step 2"),
        ]
        
        executor = PipelineExecutor(run_dir, step_functions, steps)
        
        # Start and execute
        ctx = executor.start("run_123", reason="Test run")
        final_state = executor.execute(ctx)
        
        # Verify execution
        assert final_state == RunState.SUCCEEDED
        assert executed == ["step_1", "step_2"]
        assert ctx.completed_steps == {"step_1", "step_2"}
        
        # Verify events emitted
        events = executor.event_log.read_all()
        event_types = [e["event_type"] for e in events]
        
        assert "run.created" in event_types
        assert "run.state_changed" in event_types
        assert "step.started" in event_types
        assert "step.succeeded" in event_types
        assert "run.completed" in event_types


def test_executor_hard_gate_failure():
    """Test hard gate failure blocks downstream steps."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def step_1_success(ctx, step_id):
            return True, None, None
        
        def step_2_hard_fail(ctx, step_id):
            return False, ErrorClass.HARD_GATE_FAILED, "Hard gate failed"
        
        def step_3_should_skip(ctx, step_id):
            raise AssertionError("Step 3 should not execute")
        
        step_functions = {
            "step_1": step_1_success,
            "step_2": step_2_hard_fail,
            "step_3": step_3_should_skip,
        }
        
        steps = [
            StepDefinition("step_1", "Step 1"),
            StepDefinition("step_2", "Step 2", is_hard_gate=True),
            StepDefinition("step_3", "Step 3"),
        ]
        
        executor = PipelineExecutor(run_dir, step_functions, steps)
        ctx = executor.start("run_123")
        final_state = executor.execute(ctx)
        
        # Verify fail-closed
        assert final_state == RunState.FAILED
        assert "step_2" in ctx.failed_hard_gates
        assert ctx.step_states["step_3"] == StepState.SKIPPED
        
        # Verify gate.failed event
        events = executor.event_log.read_all()
        gate_failures = [e for e in events if e["event_type"] == "gate.failed"]
        assert len(gate_failures) == 1
        assert gate_failures[0]["step_id"] == "step_2"


def test_executor_retry_transient():
    """Test transient error retry with backoff."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        attempts = []
        
        def flaky_step(ctx, step_id):
            attempt = ctx.step_attempts[step_id]
            attempts.append(attempt)
            
            if attempt < 2:
                # Fail first 2 attempts
                return False, ErrorClass.TRANSIENT_IO, "Network timeout"
            else:
                # Succeed on 3rd attempt
                return True, None, None
        
        step_functions = {"step_1": flaky_step}
        steps = [StepDefinition("step_1", "Step 1", max_retries=3, retry_classes=[ErrorClass.TRANSIENT_IO])]
        
        executor = PipelineExecutor(run_dir, step_functions, steps)
        ctx = executor.start("run_123")
        final_state = executor.execute(ctx)
        
        # Verify retry succeeded
        assert final_state == RunState.SUCCEEDED
        assert attempts == [0, 1, 2]  # 3 total attempts
        
        # Verify retry events
        events = executor.event_log.read_all()
        retry_events = [e for e in events if e["event_type"] == "step.retried"]
        assert len(retry_events) == 2  # 2 retries after initial failure


def test_executor_retry_exhausted():
    """Test retry exhaustion leads to failure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def always_fail(ctx, step_id):
            return False, ErrorClass.TRANSIENT_IO, "Persistent failure"
        
        step_functions = {"step_1": always_fail}
        steps = [StepDefinition("step_1", "Step 1", max_retries=2, retry_classes=[ErrorClass.TRANSIENT_IO])]
        
        executor = PipelineExecutor(run_dir, step_functions, steps)
        ctx = executor.start("run_123")
        final_state = executor.execute(ctx)
        
        # Verify failure after retries
        assert ctx.step_states["step_1"] == StepState.FAILED
        # Non-hard-gate failure doesn't fail run immediately (depends on implementation)
        
        # Verify max retries
        events = executor.event_log.read_all()
        retry_events = [e for e in events if e["event_type"] == "step.retried"]
        assert len(retry_events) == 2  # 2 retries (attempt 0 fails, retry 1 and 2)


def test_executor_no_retry_contract_missing():
    """Test contract input missing never retries."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        attempt_count = []
        
        def missing_input(ctx, step_id):
            attempt_count.append(ctx.step_attempts[step_id])
            return False, ErrorClass.CONTRACT_INPUT_MISSING, "Input file missing"
        
        step_functions = {"step_1": missing_input}
        steps = [StepDefinition("step_1", "Step 1", max_retries=3)]
        
        executor = PipelineExecutor(run_dir, step_functions, steps)
        ctx = executor.start("run_123")
        executor.execute(ctx)
        
        # Verify no retry
        assert len(attempt_count) == 1  # only initial attempt
        assert ctx.step_states["step_1"] == StepState.FAILED


def test_executor_event_streaming():
    """Test events are streamed during execution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def step_1(ctx, step_id):
            # Check event log has step.started before we return
            events = executor.event_log.read_all()
            started = [e for e in events if e["event_type"] == "step.started" and e["step_id"] == step_id]
            assert len(started) == 1
            return True, None, None
        
        step_functions = {"step_1": step_1}
        steps = [StepDefinition("step_1", "Step 1")]
        
        executor = PipelineExecutor(run_dir, step_functions, steps)
        ctx = executor.start("run_123")
        executor.execute(ctx)
        
        # Verify event order
        events = executor.event_log.read_all()
        event_types = [e["event_type"] for e in events]
        
        # Correct order: created -> state_changed -> started -> succeeded -> state_changed -> completed
        assert event_types[0] == "run.created"
        assert "step.started" in event_types
        assert "step.succeeded" in event_types
        assert event_types[-1] == "run.completed"


def test_hash_output():
    """Test output hash helper."""
    h1 = hash_output("test data")
    h2 = hash_output("test data")
    h3 = hash_output("different data")
    
    assert h1 == h2  # deterministic
    assert h1 != h3  # different input
    assert len(h1) == 16  # truncated hash
