"""Test CLI interface."""

import json
import tempfile
from pathlib import Path
from io import StringIO
import sys

from runner.cli import main, cmd_status, cmd_events, cmd_summary
from runner.contracts import StepDefinition
from runner.executor import PipelineExecutor


def test_cli_status(capsys):
    """Test status command."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def step_1(ctx, step_id):
            return True, None, None
        
        steps = [StepDefinition("step_1", "Step 1")]
        executor = PipelineExecutor(run_dir, {"step_1": step_1}, steps)
        
        ctx = executor.start("run_123")
        executor.execute(ctx)
        
        # Run status command
        exit_code = main(["status", str(run_dir)])
        
        assert exit_code == 0
        
        captured = capsys.readouterr()
        assert "Run ID: run_123" in captured.out
        assert "State: succeeded" in captured.out


def test_cli_events_json(capsys):
    """Test events command with JSON output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def step_1(ctx, step_id):
            return True, None, None
        
        steps = [StepDefinition("step_1", "Step 1")]
        executor = PipelineExecutor(run_dir, {"step_1": step_1}, steps)
        
        ctx = executor.start("run_123")
        executor.execute(ctx)
        
        # Run events command with JSON
        exit_code = main(["events", str(run_dir), "--json"])
        
        assert exit_code == 0
        
        captured = capsys.readouterr()
        lines = captured.out.strip().split('\n')
        
        # Each line should be valid JSON
        for line in lines:
            event = json.loads(line)
            assert "event_type" in event
            assert "run_id" in event


def test_cli_events_tail(capsys):
    """Test events tail command."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def step_1(ctx, step_id):
            return True, None, None
        
        steps = [StepDefinition("step_1", "Step 1")]
        executor = PipelineExecutor(run_dir, {"step_1": step_1}, steps)
        
        ctx = executor.start("run_123")
        executor.execute(ctx)
        
        # Tail last 2 events
        exit_code = main(["events", str(run_dir), "--tail", "2", "--json"])
        
        assert exit_code == 0
        
        captured = capsys.readouterr()
        lines = captured.out.strip().split('\n')
        
        # Should show only 2 events
        assert len(lines) == 2


def test_cli_summary_text(capsys):
    """Test summary command with text output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def step_1(ctx, step_id):
            return True, None, None
        
        steps = [StepDefinition("step_1", "Step 1")]
        executor = PipelineExecutor(run_dir, {"step_1": step_1}, steps)
        
        ctx = executor.start("run_123")
        executor.execute(ctx)
        
        # Run summary command
        exit_code = main(["summary", str(run_dir)])
        
        assert exit_code == 0
        
        captured = capsys.readouterr()
        assert "Run Summary: run_123" in captured.out
        assert "Status:" in captured.out
        assert "SUCCEEDED" in captured.out


def test_cli_summary_json(capsys):
    """Test summary command with JSON output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def step_1(ctx, step_id):
            return True, None, None
        
        steps = [StepDefinition("step_1", "Step 1")]
        executor = PipelineExecutor(run_dir, {"step_1": step_1}, steps)
        
        ctx = executor.start("run_123")
        executor.execute(ctx)
        
        # Run summary command with JSON
        exit_code = main(["summary", str(run_dir), "--json"])
        
        assert exit_code == 0
        
        captured = capsys.readouterr()
        summary_data = json.loads(captured.out)
        
        assert summary_data["run_id"] == "run_123"
        assert summary_data["final_state"] == "succeeded"
        assert len(summary_data["steps"]) == 1


def test_cli_resume_check(capsys):
    """Test resume command (check only, no execution)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "run_123"
        
        def step_1(ctx, step_id):
            raise RuntimeError("Interrupt")
        
        steps = [StepDefinition("step_1", "Step 1")]
        executor = PipelineExecutor(run_dir, {"step_1": step_1}, steps)
        
        ctx = executor.start("run_123")
        try:
            executor.execute(ctx)
        except RuntimeError:
            pass
        
        # Check resume
        exit_code = main(["resume", str(run_dir)])
        
        assert exit_code == 0
        
        captured = capsys.readouterr()
        assert "resumable" in captured.out.lower()


def test_cli_no_command():
    """Test CLI with no command shows help."""
    exit_code = main([])
    assert exit_code == 1


def test_cli_status_missing_run(capsys):
    """Test status on missing run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "nonexistent"
        
        exit_code = main(["status", str(run_dir)])
        
        assert exit_code == 1
        
        captured = capsys.readouterr()
        assert "No run found" in captured.out
