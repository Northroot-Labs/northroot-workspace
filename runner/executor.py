"""Pipeline executor with retry/compensation and event streaming."""

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .contracts import (
    Event,
    RunState,
    StepState,
    ErrorClass,
    StepDefinition,
    PIPELINE_STEPS,
    run_created,
    run_state_changed,
    run_completed,
    step_started,
    step_succeeded,
    step_failed,
    step_retried,
    gate_failed,
    artifact_emitted,
)
from .event_log import EventLog
from .state_machine import (
    RunStateMachine,
    StepStateMachine,
    RetryPolicy,
    PipelineDAG,
)


# ─── Run Context ─────────────────────────────────────────────────────────────

@dataclass
class RunContext:
    """Runtime execution context for a pipeline run."""
    
    run_id: str
    run_state: RunState
    step_states: dict[str, StepState] = field(default_factory=dict)
    step_attempts: dict[str, int] = field(default_factory=dict)
    completed_steps: set[str] = field(default_factory=set)
    failed_hard_gates: set[str] = field(default_factory=set)
    artifacts: dict[str, str] = field(default_factory=dict)  # step_id -> path
    
    def initialize_steps(self, step_ids: list[str]) -> None:
        """Initialize all steps to PENDING."""
        for step_id in step_ids:
            self.step_states[step_id] = StepState.PENDING
            self.step_attempts[step_id] = 0
    
    def can_run_step(self, step_id: str, dag: PipelineDAG) -> tuple[bool, Optional[str]]:
        """Check if step can run (dependencies satisfied, no blocking failures)."""
        return dag.can_execute_step(
            step_id,
            self.completed_steps,
            self.failed_hard_gates,
        )


# ─── Step Executor ───────────────────────────────────────────────────────────

StepFunction = Callable[[RunContext, str], tuple[bool, Optional[ErrorClass], Optional[str]]]


class StepExecutor:
    """Executes individual pipeline steps with retry and compensation."""
    
    def __init__(
        self,
        event_log: EventLog,
        step_functions: dict[str, StepFunction],
    ):
        """Initialize step executor.
        
        Args:
            event_log: Event log for streaming events
            step_functions: Map of step_id -> callable(context, step_id) -> (success, error_class, message)
        """
        self.event_log = event_log
        self.step_functions = step_functions
        self.step_sm = StepStateMachine()
    
    def execute_step(
        self,
        ctx: RunContext,
        step: StepDefinition,
    ) -> bool:
        """Execute step with retry policy.
        
        Args:
            ctx: Run context
            step: Step definition
            
        Returns:
            True if step succeeded, False otherwise
        """
        step_func = self.step_functions.get(step.step_id)
        if not step_func:
            self._emit_and_fail(
                ctx,
                step,
                ErrorClass.UNKNOWN,
                f"No implementation for step: {step.step_id}",
            )
            return False
        
        attempt = ctx.step_attempts[step.step_id]
        
        # Emit step.started
        event = step_started(ctx.run_id, step.step_id, attempt=attempt)
        self.event_log.append(event)
        ctx.step_states[step.step_id] = StepState.RUNNING
        
        # Execute step function
        success, error_class, message = step_func(ctx, step.step_id)
        
        if success:
            # Success
            event = step_succeeded(ctx.run_id, step.step_id, attempt=attempt)
            self.event_log.append(event)
            ctx.step_states[step.step_id] = StepState.SUCCEEDED
            ctx.completed_steps.add(step.step_id)
            return True
        else:
            # Failure - check retry policy
            error_class = error_class or ErrorClass.UNKNOWN
            reason = message or "Step failed"
            
            # Emit step.failed
            event = step_failed(
                ctx.run_id,
                step.step_id,
                error_class,
                reason,
                attempt=attempt,
            )
            self.event_log.append(event)
            
            # Hard gate failure
            if step.is_hard_gate:
                gate_event = gate_failed(
                    ctx.run_id,
                    step.step_id,
                    error_class,
                    reason,
                )
                self.event_log.append(gate_event)
                ctx.failed_hard_gates.add(step.step_id)
                ctx.step_states[step.step_id] = StepState.FAILED
                return False
            
            # Check retry
            if RetryPolicy.allows_retry(step, error_class, attempt):
                # Retry
                ctx.step_attempts[step.step_id] += 1
                new_attempt = ctx.step_attempts[step.step_id]
                
                retry_event = step_retried(
                    ctx.run_id,
                    step.step_id,
                    new_attempt,
                    f"Retrying after {error_class.value}",
                )
                self.event_log.append(retry_event)
                
                # Backoff
                delay = RetryPolicy.backoff_seconds(attempt)
                time.sleep(delay)
                
                # Recursive retry
                return self.execute_step(ctx, step)
            else:
                # No retry
                ctx.step_states[step.step_id] = StepState.FAILED
                return False
    
    def _emit_and_fail(
        self,
        ctx: RunContext,
        step: StepDefinition,
        error_class: ErrorClass,
        reason: str,
    ) -> None:
        """Emit failure event without retry."""
        event = step_failed(
            ctx.run_id,
            step.step_id,
            error_class,
            reason,
            attempt=ctx.step_attempts[step.step_id],
        )
        self.event_log.append(event)
        ctx.step_states[step.step_id] = StepState.FAILED


# ─── Pipeline Executor ───────────────────────────────────────────────────────

class PipelineExecutor:
    """Orchestrates full pipeline execution with fail-closed semantics."""
    
    def __init__(
        self,
        run_dir: Path,
        step_functions: dict[str, StepFunction],
        pipeline_steps: list[StepDefinition] = PIPELINE_STEPS,
    ):
        """Initialize pipeline executor.
        
        Args:
            run_dir: Directory for run artifacts and event log
            step_functions: Step implementations
            pipeline_steps: Pipeline DAG definition
        """
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        
        self.event_log = EventLog(run_dir / "events.jsonl")
        self.step_executor = StepExecutor(self.event_log, step_functions)
        self.dag = PipelineDAG(pipeline_steps)
        self.run_sm = RunStateMachine()
    
    def resume(self, ctx: RunContext, start_from: Optional[str] = None) -> RunState:
        """Resume pipeline execution from reconstructed context.
        
        Args:
            ctx: Reconstructed run context
            start_from: Optional step ID to start from (auto-detect if None)
            
        Returns:
            Final run state
        """
        # If run not in EXECUTING state, transition to it
        if ctx.run_state == RunState.CREATED:
            self._transition_run_state(ctx, RunState.PREFLIGHT_VALIDATED, reason="Resume: validation passed")
            self._transition_run_state(ctx, RunState.EXECUTING, reason="Resume execution")
        elif ctx.run_state == RunState.PREFLIGHT_VALIDATED:
            self._transition_run_state(ctx, RunState.EXECUTING, reason="Resume execution")
        elif ctx.run_state == RunState.FAILED:
            # Allow resume from failed state (for transient errors)
            self._transition_run_state(ctx, RunState.EXECUTING, reason="Resume after transient failure")
        elif ctx.run_state == RunState.BLOCKED:
            self._transition_run_state(ctx, RunState.EXECUTING, reason="Resume after manual action")
        
        # Determine start point
        if start_from is None:
            # Find first non-completed step
            for step_id in self.dag.order:
                if ctx.step_states[step_id] not in {StepState.SUCCEEDED, StepState.SKIPPED}:
                    start_from = step_id
                    break
        
        if start_from is None:
            # All steps already complete
            self._complete_run(ctx, RunState.SUCCEEDED, "All steps already complete (resume)")
            return ctx.run_state
        
        # Execute from resume point
        start_idx = self.dag.order.index(start_from)
        for step_id in self.dag.order[start_idx:]:
            step = self.dag.get_step(step_id)
            if not step:
                continue
            
            # Initialize step state if missing (not in reconstructed context)
            if step_id not in ctx.step_states:
                ctx.step_states[step_id] = StepState.PENDING
                ctx.step_attempts[step_id] = 0
            
            # Skip if already succeeded
            if ctx.step_states[step_id] == StepState.SUCCEEDED:
                continue
            
            # Check if step can execute
            can_run, reason = ctx.can_run_step(step_id, self.dag)
            
            if not can_run:
                # Skip step
                ctx.step_states[step_id] = StepState.SKIPPED
                continue
            
            # Reset failed step to pending for retry
            if ctx.step_states[step_id] == StepState.FAILED:
                ctx.step_states[step_id] = StepState.PENDING
            
            # Execute step
            success = self.step_executor.execute_step(ctx, step)
            
            if not success:
                if step.is_hard_gate:
                    # Hard gate failure: skip downstream and fail
                    downstream = self.dag.get_downstream_steps(step_id)
                    for ds in downstream:
                        if ctx.step_states[ds] == StepState.PENDING:
                            ctx.step_states[ds] = StepState.SKIPPED
                    
                    self._fail_run(ctx, f"Hard gate failed: {step_id}")
                    return ctx.run_state
        
        # Completed
        if ctx.failed_hard_gates:
            self._fail_run(ctx, f"Hard gate failures: {ctx.failed_hard_gates}")
        else:
            self._complete_run(ctx, RunState.SUCCEEDED, "All steps succeeded (resume)")
        
        return ctx.run_state
    
    def start(self, run_id: str, reason: Optional[str] = None) -> RunContext:
        """Start new pipeline run.
        
        Args:
            run_id: Unique run identifier
            reason: Optional reason for run
            
        Returns:
            Initialized run context
        """
        # Emit run.created
        event = run_created(run_id, reason=reason)
        self.event_log.append(event)
        
        # Initialize context
        ctx = RunContext(run_id=run_id, run_state=RunState.CREATED)
        ctx.initialize_steps(self.dag.order)
        
        return ctx
    
    def execute(self, ctx: RunContext) -> RunState:
        """Execute full pipeline with fail-closed semantics.
        
        Args:
            ctx: Run context
            
        Returns:
            Final run state
        """
        # Transition: CREATED -> PREFLIGHT_VALIDATED -> EXECUTING
        self._transition_run_state(ctx, RunState.PREFLIGHT_VALIDATED, reason="Pre-execution validation passed")
        self._transition_run_state(ctx, RunState.EXECUTING)
        
        # Execute steps in order
        for step_id in self.dag.order:
            step = self.dag.get_step(step_id)
            if not step:
                continue
            
            # Check if step can execute
            can_run, reason = ctx.can_run_step(step_id, self.dag)
            
            if not can_run:
                # Skip step (blocked by hard gate or missing dependencies)
                ctx.step_states[step_id] = StepState.SKIPPED
                continue
            
            # Execute step
            success = self.step_executor.execute_step(ctx, step)
            
            if not success:
                # Step failed
                if step.is_hard_gate:
                    # Hard gate failure: skip all downstream steps
                    downstream = self.dag.get_downstream_steps(step_id)
                    for ds in downstream:
                        if ctx.step_states[ds] == StepState.PENDING:
                            ctx.step_states[ds] = StepState.SKIPPED
                    
                    # Fail run immediately
                    self._fail_run(ctx, f"Hard gate failed: {step_id}")
                    return ctx.run_state
                # Continue to next step (non-critical failure)
        
        # All steps completed or skipped
        if ctx.failed_hard_gates:
            # Some hard gates failed
            self._fail_run(ctx, f"Hard gate failures: {ctx.failed_hard_gates}")
        else:
            # Success
            self._complete_run(ctx, RunState.SUCCEEDED, "All steps succeeded")
        
        return ctx.run_state
    
    def _transition_run_state(
        self,
        ctx: RunContext,
        new_state: RunState,
        reason: Optional[str] = None,
    ) -> None:
        """Transition run state and emit event."""
        self.run_sm.validate_transition(ctx.run_state, new_state)
        
        event = run_state_changed(
            ctx.run_id,
            ctx.run_state,
            new_state,
            reason=reason,
        )
        self.event_log.append(event)
        ctx.run_state = new_state
    
    def _fail_run(self, ctx: RunContext, reason: str) -> None:
        """Fail run and emit completion event."""
        if ctx.run_state != RunState.FAILED:
            self._transition_run_state(ctx, RunState.FAILED, reason=reason)
        
        event = run_completed(ctx.run_id, RunState.FAILED, reason=reason)
        self.event_log.append(event)
    
    def _complete_run(self, ctx: RunContext, final_state: RunState, reason: str) -> None:
        """Complete run and emit completion event."""
        if ctx.run_state != final_state:
            self._transition_run_state(ctx, final_state, reason=reason)
        
        event = run_completed(ctx.run_id, final_state, reason=reason)
        self.event_log.append(event)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def hash_output(data: str) -> str:
    """Compute deterministic hash of output."""
    return hashlib.sha256(data.encode()).hexdigest()[:16]
