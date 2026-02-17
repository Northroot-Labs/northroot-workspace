"""Run summary generation from event log.

Produces human-readable and machine-readable summaries of completed runs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .contracts import RunState, StepState, EventType, ErrorClass
from .event_log import EventLog


@dataclass
class StepSummary:
    """Summary of a single step execution."""
    
    step_id: str
    state: StepState
    attempts: int = 0
    error_class: Optional[ErrorClass] = None
    error_reason: Optional[str] = None
    duration_ms: Optional[int] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class RunSummary:
    """Summary of a complete run."""
    
    run_id: str
    final_state: RunState
    created_at: str
    completed_at: Optional[str] = None
    duration_ms: Optional[int] = None
    
    steps: list[StepSummary] = field(default_factory=list)
    completed_steps: int = 0
    failed_steps: int = 0
    skipped_steps: int = 0
    failed_hard_gates: list[str] = field(default_factory=list)
    
    total_attempts: int = 0
    total_retries: int = 0
    
    def to_dict(self) -> dict:
        """Machine-readable summary."""
        return {
            "run_id": self.run_id,
            "final_state": self.final_state.value,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "steps": [
                {
                    "step_id": s.step_id,
                    "state": s.state.value,
                    "attempts": s.attempts,
                    "error_class": s.error_class.value if s.error_class else None,
                    "error_reason": s.error_reason,
                    "duration_ms": s.duration_ms,
                }
                for s in self.steps
            ],
            "stats": {
                "total_steps": len(self.steps),
                "completed": self.completed_steps,
                "failed": self.failed_steps,
                "skipped": self.skipped_steps,
                "total_attempts": self.total_attempts,
                "total_retries": self.total_retries,
            },
            "failed_hard_gates": self.failed_hard_gates,
        }
    
    def to_text(self) -> str:
        """Human-readable summary."""
        lines = []
        
        # Header
        lines.append(f"Run Summary: {self.run_id}")
        lines.append("=" * 60)
        
        # Status
        status_emoji = {
            RunState.SUCCEEDED: "✓",
            RunState.FAILED: "✗",
            RunState.ROLLED_BACK: "↺",
        }.get(self.final_state, "•")
        
        lines.append(f"Status: {status_emoji} {self.final_state.value.upper()}")
        lines.append(f"Created: {self.created_at}")
        if self.completed_at:
            lines.append(f"Completed: {self.completed_at}")
        if self.duration_ms is not None:
            lines.append(f"Duration: {self.duration_ms / 1000:.2f}s")
        
        lines.append("")
        
        # Stats
        lines.append(f"Steps: {len(self.steps)} total "
                    f"({self.completed_steps} completed, "
                    f"{self.failed_steps} failed, "
                    f"{self.skipped_steps} skipped)")
        lines.append(f"Retries: {self.total_retries}")
        
        if self.failed_hard_gates:
            lines.append(f"Hard gate failures: {', '.join(self.failed_hard_gates)}")
        
        lines.append("")
        
        # Steps
        lines.append("Steps:")
        lines.append("-" * 60)
        
        for step in self.steps:
            state_emoji = {
                StepState.SUCCEEDED: "✓",
                StepState.FAILED: "✗",
                StepState.SKIPPED: "⊘",
                StepState.COMPENSATED: "↺",
            }.get(step.state, "•")
            
            line = f"  {state_emoji} {step.step_id:<30} {step.state.value}"
            
            if step.attempts > 1:
                line += f" (attempts: {step.attempts})"
            
            lines.append(line)
            
            if step.error_reason:
                lines.append(f"      Error: {step.error_reason}")
        
        return "\n".join(lines)


class SummaryGenerator:
    """Generates run summaries from event logs."""
    
    def __init__(self, event_log: EventLog):
        """Initialize summary generator.
        
        Args:
            event_log: Event log to analyze
        """
        self.event_log = event_log
    
    def generate(self) -> RunSummary:
        """Generate run summary from event log.
        
        Returns:
            RunSummary with stats and step outcomes
        """
        events = self.event_log.read_all()
        
        if not events:
            raise ValueError("Event log is empty")
        
        # Initialize summary
        first = events[0]
        run_id = first["run_id"]
        created_at = first["timestamp_utc"]
        
        summary = RunSummary(
            run_id=run_id,
            final_state=RunState.CREATED,
            created_at=created_at,
        )
        
        # Track step states
        step_states = {}
        step_attempts = {}
        step_start_times = {}
        step_errors = {}
        gate_failures = set()
        retry_count = 0
        
        # Process events
        for event in events:
            event_type = event["event_type"]
            timestamp = event["timestamp_utc"]
            
            if event_type == "run.state_changed" or event_type == "run.completed":
                summary.final_state = RunState(event["new_state"])
                summary.completed_at = timestamp
            
            elif event_type == "step.started":
                step_id = event["step_id"]
                step_states[step_id] = StepState.RUNNING
                step_attempts[step_id] = event.get("attempt", 0)
                step_start_times[step_id] = timestamp
            
            elif event_type == "step.succeeded":
                step_id = event["step_id"]
                step_states[step_id] = StepState.SUCCEEDED
            
            elif event_type == "step.failed":
                step_id = event["step_id"]
                step_states[step_id] = StepState.FAILED
                step_errors[step_id] = {
                    "class": event.get("error_class"),
                    "reason": event.get("reason"),
                }
            
            elif event_type == "step.retried":
                retry_count += 1
            
            elif event_type == "gate.failed":
                step_id = event["step_id"]
                gate_failures.add(step_id)
        
        # Build step summaries
        for step_id in sorted(step_states.keys()):
            state = step_states[step_id]
            attempts = step_attempts.get(step_id, 0) + 1  # +1 for initial attempt
            
            error_info = step_errors.get(step_id, {})
            error_class = error_info.get("class")
            if error_class:
                error_class = ErrorClass(error_class)
            
            step_summary = StepSummary(
                step_id=step_id,
                state=state,
                attempts=attempts,
                error_class=error_class,
                error_reason=error_info.get("reason"),
                started_at=step_start_times.get(step_id),
            )
            
            summary.steps.append(step_summary)
            
            # Update counts
            if state == StepState.SUCCEEDED:
                summary.completed_steps += 1
            elif state == StepState.FAILED:
                summary.failed_steps += 1
            elif state == StepState.SKIPPED:
                summary.skipped_steps += 1
        
        # Calculate totals
        summary.total_attempts = sum(s.attempts for s in summary.steps)
        summary.total_retries = retry_count
        summary.failed_hard_gates = sorted(gate_failures)
        
        # Calculate duration
        if summary.completed_at and summary.created_at:
            start = datetime.fromisoformat(summary.created_at.replace('Z', '+00:00'))
            end = datetime.fromisoformat(summary.completed_at.replace('Z', '+00:00'))
            summary.duration_ms = int((end - start).total_seconds() * 1000)
        
        return summary


def generate_summary(run_dir: Path) -> RunSummary:
    """Generate summary for a run.
    
    Args:
        run_dir: Run directory with events.jsonl
        
    Returns:
        RunSummary
    """
    log_path = run_dir / "events.jsonl"
    if not log_path.exists():
        raise FileNotFoundError(f"Event log not found: {log_path}")
    
    event_log = EventLog(log_path)
    generator = SummaryGenerator(event_log)
    return generator.generate()
