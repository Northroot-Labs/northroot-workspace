"""Event and step contracts for fail-closed pipeline runner.

Compact schema optimized for streaming/SSE and low token cost for AI consumers.
All events are immutable and append-only.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid


# ─── Run States ──────────────────────────────────────────────────────────────

class RunState(str, Enum):
    """Run-level states with fail-closed semantics."""
    
    CREATED = "created"
    PREFLIGHT_VALIDATED = "preflight_validated"
    EXECUTING = "executing"
    BLOCKED = "blocked"  # manual action required
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    ROLLED_BACK = "rolled_back"


# ─── Step States ─────────────────────────────────────────────────────────────

class StepState(str, Enum):
    """Step-level states for DAG execution."""
    
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    COMPENSATED = "compensated"
    SKIPPED = "skipped"


# ─── Error Classes ───────────────────────────────────────────────────────────

class ErrorClass(str, Enum):
    """Error classification for retry policy."""
    
    TRANSIENT_IO = "transient_io"  # retry with backoff
    CONTRACT_INPUT_MISSING = "contract_input_missing"  # no retry
    HARD_GATE_FAILED = "hard_gate_failed"  # no retry unless override
    VALIDATION_FAILED = "validation_failed"  # no retry
    UNKNOWN = "unknown"  # no retry by default


# ─── Event Types ─────────────────────────────────────────────────────────────

class EventType(str, Enum):
    """All event types emitted by runner."""
    
    RUN_CREATED = "run.created"
    RUN_STATE_CHANGED = "run.state_changed"
    STEP_STARTED = "step.started"
    STEP_SUCCEEDED = "step.succeeded"
    STEP_FAILED = "step.failed"
    STEP_RETRIED = "step.retried"
    STEP_COMPENSATED = "step.compensated"
    ARTIFACT_EMITTED = "artifact.emitted"
    GATE_FAILED = "gate.failed"
    RUN_COMPLETED = "run.completed"
    RUN_OVERRIDE_APPLIED = "run.override_applied"


# ─── Actor ───────────────────────────────────────────────────────────────────

class Actor(str, Enum):
    """Entity triggering event."""
    
    RUNNER = "runner"
    MANUAL = "manual"


# ─── Base Event ──────────────────────────────────────────────────────────────

@dataclass
class Event:
    """Compact base event contract.
    
    Required fields optimized for streaming and low token cost:
    - event_type: discriminator
    - run_id: correlation
    - step_id: correlation (null for run-level events)
    - attempt: retry tracking
    - error_class: failure classification
    - reason: compact explanation (error_message or action reason)
    
    All events are timestamped and uniquely identified.
    """
    
    event_id: str
    event_type: EventType
    run_id: str
    timestamp_utc: str
    actor: Actor
    attempt: int = 0
    step_id: Optional[str] = None
    error_class: Optional[ErrorClass] = None
    reason: Optional[str] = None
    
    # Optional extended fields (not in compact core)
    inputs_hash: Optional[str] = None
    outputs_hash: Optional[str] = None
    artifact_path: Optional[str] = None
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    override_reason: Optional[str] = None
    
    @staticmethod
    def now_utc() -> str:
        """ISO 8601 UTC timestamp."""
        return datetime.now(timezone.utc).isoformat()
    
    @staticmethod
    def new_id() -> str:
        """Generate event ID."""
        return str(uuid.uuid4())
    
    def to_dict(self) -> dict:
        """Compact dict representation (omit null optional fields)."""
        result = {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "run_id": self.run_id,
            "timestamp_utc": self.timestamp_utc,
            "actor": self.actor.value,
            "attempt": self.attempt,
        }
        
        # Add optional fields only if present
        if self.step_id is not None:
            result["step_id"] = self.step_id
        if self.error_class is not None:
            result["error_class"] = self.error_class.value
        if self.reason is not None:
            result["reason"] = self.reason
        if self.inputs_hash is not None:
            result["inputs_hash"] = self.inputs_hash
        if self.outputs_hash is not None:
            result["outputs_hash"] = self.outputs_hash
        if self.artifact_path is not None:
            result["artifact_path"] = self.artifact_path
        if self.previous_state is not None:
            result["previous_state"] = self.previous_state
        if self.new_state is not None:
            result["new_state"] = self.new_state
        if self.override_reason is not None:
            result["override_reason"] = self.override_reason
        
        return result


# ─── Event Builders ──────────────────────────────────────────────────────────

def run_created(run_id: str, reason: Optional[str] = None) -> Event:
    """Run creation event."""
    return Event(
        event_id=Event.new_id(),
        event_type=EventType.RUN_CREATED,
        run_id=run_id,
        timestamp_utc=Event.now_utc(),
        actor=Actor.RUNNER,
        new_state=RunState.CREATED.value,
        reason=reason,
    )


def run_state_changed(
    run_id: str,
    previous_state: RunState,
    new_state: RunState,
    reason: Optional[str] = None,
) -> Event:
    """Run state transition event."""
    return Event(
        event_id=Event.new_id(),
        event_type=EventType.RUN_STATE_CHANGED,
        run_id=run_id,
        timestamp_utc=Event.now_utc(),
        actor=Actor.RUNNER,
        previous_state=previous_state.value,
        new_state=new_state.value,
        reason=reason,
    )


def step_started(run_id: str, step_id: str, attempt: int = 0) -> Event:
    """Step execution start."""
    return Event(
        event_id=Event.new_id(),
        event_type=EventType.STEP_STARTED,
        run_id=run_id,
        step_id=step_id,
        timestamp_utc=Event.now_utc(),
        actor=Actor.RUNNER,
        attempt=attempt,
        new_state=StepState.RUNNING.value,
    )


def step_succeeded(
    run_id: str,
    step_id: str,
    attempt: int = 0,
    outputs_hash: Optional[str] = None,
) -> Event:
    """Step success event."""
    return Event(
        event_id=Event.new_id(),
        event_type=EventType.STEP_SUCCEEDED,
        run_id=run_id,
        step_id=step_id,
        timestamp_utc=Event.now_utc(),
        actor=Actor.RUNNER,
        attempt=attempt,
        new_state=StepState.SUCCEEDED.value,
        outputs_hash=outputs_hash,
    )


def step_failed(
    run_id: str,
    step_id: str,
    error_class: ErrorClass,
    reason: str,
    attempt: int = 0,
) -> Event:
    """Step failure event."""
    return Event(
        event_id=Event.new_id(),
        event_type=EventType.STEP_FAILED,
        run_id=run_id,
        step_id=step_id,
        timestamp_utc=Event.now_utc(),
        actor=Actor.RUNNER,
        attempt=attempt,
        error_class=error_class,
        reason=reason,
        new_state=StepState.FAILED.value,
    )


def step_retried(run_id: str, step_id: str, attempt: int, reason: str) -> Event:
    """Step retry event."""
    return Event(
        event_id=Event.new_id(),
        event_type=EventType.STEP_RETRIED,
        run_id=run_id,
        step_id=step_id,
        timestamp_utc=Event.now_utc(),
        actor=Actor.RUNNER,
        attempt=attempt,
        reason=reason,
    )


def gate_failed(
    run_id: str,
    step_id: str,
    error_class: ErrorClass,
    reason: str,
) -> Event:
    """Hard gate failure event."""
    return Event(
        event_id=Event.new_id(),
        event_type=EventType.GATE_FAILED,
        run_id=run_id,
        step_id=step_id,
        timestamp_utc=Event.now_utc(),
        actor=Actor.RUNNER,
        error_class=error_class,
        reason=reason,
    )


def artifact_emitted(
    run_id: str,
    step_id: str,
    artifact_path: str,
    outputs_hash: Optional[str] = None,
) -> Event:
    """Artifact emission event."""
    return Event(
        event_id=Event.new_id(),
        event_type=EventType.ARTIFACT_EMITTED,
        run_id=run_id,
        step_id=step_id,
        timestamp_utc=Event.now_utc(),
        actor=Actor.RUNNER,
        artifact_path=artifact_path,
        outputs_hash=outputs_hash,
    )


def run_completed(run_id: str, final_state: RunState, reason: Optional[str] = None) -> Event:
    """Run completion event."""
    return Event(
        event_id=Event.new_id(),
        event_type=EventType.RUN_COMPLETED,
        run_id=run_id,
        timestamp_utc=Event.now_utc(),
        actor=Actor.RUNNER,
        new_state=final_state.value,
        reason=reason,
    )


# ─── Step Definition ─────────────────────────────────────────────────────────

@dataclass
class StepDefinition:
    """Pipeline step definition."""
    
    step_id: str
    name: str
    is_hard_gate: bool = False
    is_manual_gated: bool = False
    max_retries: int = 0
    retry_classes: list[ErrorClass] = field(default_factory=lambda: [ErrorClass.TRANSIENT_IO])
    
    def allows_retry(self, error_class: ErrorClass, current_attempt: int) -> bool:
        """Check if retry is allowed for this error class and attempt count."""
        if current_attempt >= self.max_retries:
            return False
        return error_class in self.retry_classes


# ─── Pipeline DAG ────────────────────────────────────────────────────────────

# Ordered steps from PR description
PIPELINE_STEPS = [
    StepDefinition(
        step_id="preflight_contract_check",
        name="Preflight contract check",
        is_hard_gate=True,
    ),
    StepDefinition(
        step_id="phase_benchmark",
        name="Phase benchmark",
        is_hard_gate=True,
        max_retries=2,
    ),
    StepDefinition(
        step_id="stage_data_layout",
        name="Stage data layout",
        max_retries=3,
    ),
    StepDefinition(
        step_id="build_steward_bundle",
        name="Build steward bundle",
        max_retries=2,
    ),
    StepDefinition(
        step_id="validate_bundle_quality",
        name="Validate bundle quality",
        is_hard_gate=True,
    ),
    StepDefinition(
        step_id="build_minimal_deliverable",
        name="Build minimal deliverable",
        max_retries=2,
    ),
    StepDefinition(
        step_id="verify_artifacts",
        name="Verify artifacts",
        is_hard_gate=True,
    ),
    StepDefinition(
        step_id="publish_internal",
        name="Publish internal",
        is_manual_gated=True,
    ),
]
