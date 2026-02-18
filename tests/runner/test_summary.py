"""Test run summary generation."""

import json
import tempfile
from pathlib import Path

from runner.contracts import RunState, StepState, ErrorClass, StepDefinition
from runner.executor import PipelineExecutor
from runner.summary import SummaryGenerator, generate_summary


def test_summary_successful_run():
    """Test summary for successful run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def step_1(ctx, step_id):
            return True, None, None
        
        def step_2(ctx, step_id):
            return True, None, None
        
        steps = [
            StepDefinition("step_1", "Step 1"),
            StepDefinition("step_2", "Step 2"),
        ]
        
        executor = PipelineExecutor(run_dir, {"step_1": step_1, "step_2": step_2}, steps)
        ctx = executor.start("run_123", reason="Test")
        executor.execute(ctx)
        
        # Generate summary
        summary = generate_summary(run_dir)
        
        assert summary.run_id == "run_123"
        assert summary.final_state == RunState.SUCCEEDED
        assert summary.completed_steps == 2
        assert summary.failed_steps == 0
        assert summary.skipped_steps == 0
        assert len(summary.steps) == 2
        assert summary.total_retries == 0


def test_summary_with_failures():
    """Test summary with failed steps."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def step_1_fail(ctx, step_id):
            return False, ErrorClass.HARD_GATE_FAILED, "Hard gate failed"
        
        def step_2_skip(ctx, step_id):
            return True, None, None
        
        steps = [
            StepDefinition("step_1", "Step 1", is_hard_gate=True),
            StepDefinition("step_2", "Step 2"),
        ]
        
        executor = PipelineExecutor(run_dir, {"step_1": step_1_fail, "step_2": step_2_skip}, steps)
        ctx = executor.start("run_123")
        executor.execute(ctx)
        
        # Generate summary
        summary = generate_summary(run_dir)
        
        assert summary.final_state == RunState.FAILED
        assert summary.failed_steps == 1
        # Note: skipped steps don't emit events, so they won't appear in summary
        # This is expected behavior - summary only reflects executed steps
        assert "step_1" in summary.failed_hard_gates
        
        # Check step details
        step1_summary = next(s for s in summary.steps if s.step_id == "step_1")
        assert step1_summary.state == StepState.FAILED
        assert step1_summary.error_class == ErrorClass.HARD_GATE_FAILED
        assert "Hard gate failed" in step1_summary.error_reason
        
        # step_2 was skipped (no events emitted), so it won't be in summary
        assert len(summary.steps) == 1


def test_summary_with_retries():
    """Test summary includes retry count."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        attempts = []
        
        def flaky_step(ctx, step_id):
            attempt = ctx.step_attempts[step_id]
            attempts.append(attempt)
            
            if attempt < 2:
                return False, ErrorClass.TRANSIENT_IO, "Timeout"
            return True, None, None
        
        steps = [
            StepDefinition("step_1", "Step 1", max_retries=3, retry_classes=[ErrorClass.TRANSIENT_IO]),
        ]
        
        executor = PipelineExecutor(run_dir, {"step_1": flaky_step}, steps)
        ctx = executor.start("run_123")
        executor.execute(ctx)
        
        # Generate summary
        summary = generate_summary(run_dir)
        
        assert summary.final_state == RunState.SUCCEEDED
        assert summary.total_retries == 2  # 2 retries after initial failure
        
        step1 = summary.steps[0]
        assert step1.attempts == 3  # initial + 2 retries


def test_summary_to_dict():
    """Test machine-readable dict output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def step_1(ctx, step_id):
            return True, None, None
        
        steps = [StepDefinition("step_1", "Step 1")]
        executor = PipelineExecutor(run_dir, {"step_1": step_1}, steps)
        
        ctx = executor.start("run_123")
        executor.execute(ctx)
        
        summary = generate_summary(run_dir)
        data = summary.to_dict()
        
        # Verify structure
        assert data["run_id"] == "run_123"
        assert data["final_state"] == "succeeded"
        assert "created_at" in data
        assert "completed_at" in data
        assert "duration_ms" in data
        
        assert len(data["steps"]) == 1
        assert data["steps"][0]["step_id"] == "step_1"
        assert data["steps"][0]["state"] == "succeeded"
        
        assert data["stats"]["total_steps"] == 1
        assert data["stats"]["completed"] == 1
        
        # Should be JSON-serializable
        json_str = json.dumps(data)
        assert "run_123" in json_str


def test_summary_to_text():
    """Test human-readable text output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def step_1(ctx, step_id):
            return True, None, None
        
        def step_2_fail(ctx, step_id):
            return False, ErrorClass.VALIDATION_FAILED, "Validation error"
        
        steps = [
            StepDefinition("step_1", "Step 1"),
            StepDefinition("step_2", "Step 2", max_retries=0),
        ]
        
        executor = PipelineExecutor(
            run_dir,
            {"step_1": step_1, "step_2": step_2_fail},
            steps,
        )
        
        ctx = executor.start("run_123")
        executor.execute(ctx)
        
        summary = generate_summary(run_dir)
        text = summary.to_text()
        
        # Verify key content
        assert "Run Summary: run_123" in text
        assert "Status:" in text
        assert "Steps:" in text
        assert "step_1" in text
        assert "step_2" in text
        assert "Validation error" in text
        assert "Duration:" in text


def test_summary_duration_calculation():
    """Test duration is calculated from timestamps."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def step_1(ctx, step_id):
            import time
            time.sleep(0.05)  # 50ms
            return True, None, None
        
        steps = [StepDefinition("step_1", "Step 1")]
        executor = PipelineExecutor(run_dir, {"step_1": step_1}, steps)
        
        ctx = executor.start("run_123")
        executor.execute(ctx)
        
        summary = generate_summary(run_dir)
        
        # Duration should be > 50ms
        assert summary.duration_ms is not None
        assert summary.duration_ms >= 50


def test_summary_empty_log():
    """Test summary generation fails on empty log."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        run_dir.mkdir()
        log_path = run_dir / "events.jsonl"
        log_path.touch()
        
        from runner.event_log import EventLog
        event_log = EventLog(log_path)
        generator = SummaryGenerator(event_log)
        
        try:
            generator.generate()
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "empty" in str(e).lower()


def test_summary_missing_log():
    """Test summary fails when log missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        run_dir.mkdir()
        
        try:
            generate_summary(run_dir)
            assert False, "Should raise FileNotFoundError"
        except FileNotFoundError as e:
            assert "Event log not found" in str(e)
