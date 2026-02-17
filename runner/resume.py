"""Run resume logic with transition guards.

Reconstructs run state from event log and validates resumability.
"""

from pathlib import Path
from typing import Optional

from .contracts import (
    RunState,
    StepState,
    EventType,
    ErrorClass,
    PIPELINE_STEPS,
)
from .event_log import EventLog
from .executor import RunContext, PipelineDAG


class ResumeError(Exception):
    """Raised when run cannot be resumed."""
    pass


class RunReconstructor:
    """Reconstructs run state from event log."""
    
    def __init__(self, event_log: EventLog):
        """Initialize reconstructor.
        
        Args:
            event_log: Event log to reconstruct from
        """
        self.event_log = event_log
    
    def reconstruct(self) -> RunContext:
        """Reconstruct run context from event log.
        
        Returns:
            Reconstructed run context
            
        Raises:
            ResumeError: If event log is invalid or incomplete
        """
        events = self.event_log.read_all()
        
        if not events:
            raise ResumeError("Event log is empty")
        
        # First event must be run.created
        first = events[0]
        if first["event_type"] != "run.created":
            raise ResumeError(f"First event must be run.created, got {first['event_type']}")
        
        run_id = first["run_id"]
        
        # Initialize context
        ctx = RunContext(
            run_id=run_id,
            run_state=RunState.CREATED,
        )
        
        # Initialize all steps to pending
        step_ids = [step.step_id for step in PIPELINE_STEPS]
        ctx.initialize_steps(step_ids)
        
        # Replay events
        for event in events:
            self._apply_event(ctx, event)
        
        return ctx
    
    def _apply_event(self, ctx: RunContext, event: dict) -> None:
        """Apply single event to context.
        
        Args:
            ctx: Run context to update
            event: Event dict
        """
        event_type = event["event_type"]
        
        if event_type == "run.state_changed":
            # Update run state
            ctx.run_state = RunState(event["new_state"])
        
        elif event_type == "run.completed":
            # Final state
            ctx.run_state = RunState(event["new_state"])
        
        elif event_type == "step.started":
            step_id = event["step_id"]
            ctx.step_states[step_id] = StepState.RUNNING
            ctx.step_attempts[step_id] = event["attempt"]
        
        elif event_type == "step.succeeded":
            step_id = event["step_id"]
            ctx.step_states[step_id] = StepState.SUCCEEDED
            ctx.completed_steps.add(step_id)
        
        elif event_type == "step.failed":
            step_id = event["step_id"]
            ctx.step_states[step_id] = StepState.FAILED
        
        elif event_type == "gate.failed":
            step_id = event["step_id"]
            ctx.failed_hard_gates.add(step_id)
        
        elif event_type == "step.retried":
            step_id = event["step_id"]
            ctx.step_attempts[step_id] = event["attempt"]
            # Reset to pending for retry
            ctx.step_states[step_id] = StepState.PENDING


class ResumeGuard:
    """Guards for run resume validation."""
    
    # Terminal run states that cannot be resumed
    TERMINAL_STATES = {
        RunState.SUCCEEDED,
        RunState.ROLLED_BACK,
    }
    
    # Step states that can be retried/resumed
    RESUMABLE_STEP_STATES = {
        StepState.PENDING,
        StepState.FAILED,  # if retry policy allows
    }
    
    @classmethod
    def can_resume(cls, ctx: RunContext) -> tuple[bool, Optional[str]]:
        """Check if run can be resumed.
        
        Args:
            ctx: Run context
            
        Returns:
            (can_resume, reason) tuple
        """
        # Cannot resume terminal states
        if ctx.run_state in cls.TERMINAL_STATES:
            return False, f"Run in terminal state: {ctx.run_state.value}"
        
        # Can resume FAILED if no hard gates failed
        if ctx.run_state == RunState.FAILED:
            if ctx.failed_hard_gates:
                return False, f"Hard gate failures block resume: {ctx.failed_hard_gates}"
            # Failed but retriable (transient errors)
            return True, None
        
        # Can resume BLOCKED (manual action required)
        if ctx.run_state == RunState.BLOCKED:
            return True, None
        
        # Can resume in-progress runs
        if ctx.run_state in {RunState.CREATED, RunState.PREFLIGHT_VALIDATED, RunState.EXECUTING}:
            return True, None
        
        return False, f"Unknown run state: {ctx.run_state.value}"
    
    @classmethod
    def validate_resume(cls, ctx: RunContext) -> None:
        """Validate run can be resumed.
        
        Args:
            ctx: Run context
            
        Raises:
            ResumeError: If run cannot be resumed
        """
        can_resume, reason = cls.can_resume(ctx)
        if not can_resume:
            raise ResumeError(f"Cannot resume run: {reason}")
    
    @classmethod
    def get_resume_point(cls, ctx: RunContext, dag: PipelineDAG) -> Optional[str]:
        """Get first step to resume from.
        
        Args:
            ctx: Run context
            dag: Pipeline DAG
            
        Returns:
            Step ID to resume from, or None if all complete
        """
        for step_id in dag.order:
            state = ctx.step_states[step_id]
            
            # Skip completed
            if state == StepState.SUCCEEDED:
                continue
            
            # Skip skipped
            if state == StepState.SKIPPED:
                continue
            
            # Found resumable step
            if state in cls.RESUMABLE_STEP_STATES:
                return step_id
        
        return None


def resume_run(run_dir: Path) -> RunContext:
    """Resume run from event log.
    
    Args:
        run_dir: Run directory with events.jsonl
        
    Returns:
        Reconstructed run context
        
    Raises:
        ResumeError: If run cannot be resumed
    """
    log_path = run_dir / "events.jsonl"
    if not log_path.exists():
        raise ResumeError(f"Event log not found: {log_path}")
    
    event_log = EventLog(log_path)
    reconstructor = RunReconstructor(event_log)
    
    # Reconstruct state
    ctx = reconstructor.reconstruct()
    
    # Validate resumability
    ResumeGuard.validate_resume(ctx)
    
    return ctx
