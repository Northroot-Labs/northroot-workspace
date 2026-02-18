"""State machine with transition guards for fail-closed execution."""

from typing import Optional

from .contracts import (
    RunState,
    StepState,
    ErrorClass,
    StepDefinition,
    PIPELINE_STEPS,
)


class RunStateMachine:
    """Run-level state machine with fail-closed semantics."""
    
    # Valid state transitions (fail-closed: most failures -> FAILED terminal state)
    TRANSITIONS = {
        RunState.CREATED: {RunState.PREFLIGHT_VALIDATED, RunState.FAILED},
        RunState.PREFLIGHT_VALIDATED: {RunState.EXECUTING, RunState.FAILED},
        RunState.EXECUTING: {
            RunState.BLOCKED,
            RunState.FAILED,
            RunState.SUCCEEDED,
        },
        RunState.BLOCKED: {
            RunState.EXECUTING,  # after manual action
            RunState.FAILED,
            RunState.ROLLED_BACK,
        },
        RunState.FAILED: {RunState.ROLLED_BACK},  # optional compensation
        RunState.SUCCEEDED: set(),  # terminal
        RunState.ROLLED_BACK: set(),  # terminal
    }
    
    @classmethod
    def can_transition(
        cls,
        current: RunState,
        target: RunState,
    ) -> bool:
        """Check if state transition is valid.
        
        Args:
            current: Current run state
            target: Target run state
            
        Returns:
            True if transition is allowed
        """
        return target in cls.TRANSITIONS.get(current, set())
    
    @classmethod
    def validate_transition(
        cls,
        current: RunState,
        target: RunState,
    ) -> None:
        """Validate state transition (raise on invalid).
        
        Args:
            current: Current run state
            target: Target run state
            
        Raises:
            ValueError: If transition is invalid
        """
        if not cls.can_transition(current, target):
            raise ValueError(
                f"Invalid run state transition: {current.value} -> {target.value}"
            )


class StepStateMachine:
    """Step-level state machine."""
    
    TRANSITIONS = {
        StepState.PENDING: {StepState.RUNNING, StepState.SKIPPED},
        StepState.RUNNING: {
            StepState.SUCCEEDED,
            StepState.FAILED,
        },
        StepState.FAILED: {
            StepState.RUNNING,  # retry
            StepState.COMPENSATED,
        },
        StepState.SUCCEEDED: set(),  # terminal
        StepState.COMPENSATED: set(),  # terminal
        StepState.SKIPPED: set(),  # terminal
    }
    
    @classmethod
    def can_transition(
        cls,
        current: StepState,
        target: StepState,
    ) -> bool:
        """Check if step state transition is valid."""
        return target in cls.TRANSITIONS.get(current, set())
    
    @classmethod
    def validate_transition(
        cls,
        current: StepState,
        target: StepState,
    ) -> None:
        """Validate step state transition.
        
        Raises:
            ValueError: If transition is invalid
        """
        if not cls.can_transition(current, target):
            raise ValueError(
                f"Invalid step state transition: {current.value} -> {target.value}"
            )


class RetryPolicy:
    """Retry policy with error classification."""
    
    @staticmethod
    def allows_retry(
        step: StepDefinition,
        error_class: ErrorClass,
        current_attempt: int,
    ) -> bool:
        """Check if retry is allowed.
        
        Args:
            step: Step definition
            error_class: Error classification
            current_attempt: Current attempt number (0-indexed)
            
        Returns:
            True if retry should be attempted
        """
        # Hard gate failures never retry (unless manual override)
        if step.is_hard_gate and error_class == ErrorClass.HARD_GATE_FAILED:
            return False
        
        # Check step-specific retry policy
        return step.allows_retry(error_class, current_attempt)
    
    @staticmethod
    def backoff_seconds(attempt: int, base: float = 2.0, max_delay: float = 60.0) -> float:
        """Calculate exponential backoff with jitter.
        
        Args:
            attempt: Retry attempt number (0-indexed)
            base: Base delay in seconds
            max_delay: Maximum delay in seconds
            
        Returns:
            Delay in seconds with jitter applied
        """
        import random
        
        delay = min(base * (2 ** attempt), max_delay)
        jitter = random.uniform(0, delay * 0.1)  # 10% jitter
        return delay + jitter


class PipelineDAG:
    """Pipeline DAG with dependency tracking."""
    
    def __init__(self, steps: list[StepDefinition] = PIPELINE_STEPS):
        """Initialize pipeline DAG.
        
        Args:
            steps: Ordered list of step definitions
        """
        self.steps = {step.step_id: step for step in steps}
        self.order = [step.step_id for step in steps]
    
    def get_step(self, step_id: str) -> Optional[StepDefinition]:
        """Get step definition by ID."""
        return self.steps.get(step_id)
    
    def get_upstream_steps(self, step_id: str) -> list[str]:
        """Get all upstream step IDs (dependencies).
        
        Args:
            step_id: Step to check
            
        Returns:
            List of upstream step IDs in execution order
        """
        try:
            idx = self.order.index(step_id)
            return self.order[:idx]
        except ValueError:
            return []
    
    def get_downstream_steps(self, step_id: str) -> list[str]:
        """Get all downstream step IDs.
        
        Args:
            step_id: Step to check
            
        Returns:
            List of downstream step IDs in execution order
        """
        try:
            idx = self.order.index(step_id)
            return self.order[idx + 1:]
        except ValueError:
            return []
    
    def can_execute_step(
        self,
        step_id: str,
        completed_steps: set[str],
        failed_hard_gates: set[str],
    ) -> tuple[bool, Optional[str]]:
        """Check if step can execute (all dependencies satisfied, no hard gate failures).
        
        Args:
            step_id: Step to check
            completed_steps: Set of successfully completed step IDs
            failed_hard_gates: Set of failed hard gate step IDs
            
        Returns:
            (can_execute, reason) tuple
        """
        # Check if step exists
        step = self.get_step(step_id)
        if not step:
            return False, f"Unknown step: {step_id}"
        
        # Fail-closed: any upstream hard gate failure blocks downstream
        upstream = set(self.get_upstream_steps(step_id))
        blocked_by = upstream & failed_hard_gates
        if blocked_by:
            return False, f"Blocked by failed hard gate(s): {blocked_by}"
        
        # All upstream steps must be completed
        missing = upstream - completed_steps
        if missing:
            return False, f"Missing upstream dependencies: {missing}"
        
        return True, None
