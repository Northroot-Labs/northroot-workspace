"""CLI interface for pipeline runner.

Commands:
- start: Start new run
- resume: Resume interrupted run
- status: Show run status
- events: Stream/tail events
- summary: Show run summary
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .contracts import PIPELINE_STEPS
from .executor import PipelineExecutor, StepFunction
from .resume import resume_run, ResumeError
from .summary import generate_summary
from .event_log import EventLog


def cmd_start(args: argparse.Namespace) -> int:
    """Start new pipeline run."""
    run_dir = Path(args.run_dir)
    run_id = args.run_id or run_dir.name
    
    print(f"Starting run: {run_id}")
    print(f"Run directory: {run_dir}")
    print()
    
    # Note: In real implementation, step_functions would be loaded from config
    # For now, this is a placeholder showing the CLI structure
    print("Error: No step implementations configured")
    print("Hint: Use PipelineExecutor programmatically with step_functions dict")
    return 1


def cmd_resume(args: argparse.Namespace) -> int:
    """Resume interrupted run."""
    run_dir = Path(args.run_dir)
    
    print(f"Resuming run from: {run_dir}")
    
    try:
        ctx = resume_run(run_dir)
        print(f"Run ID: {ctx.run_id}")
        print(f"Current state: {ctx.run_state.value}")
        print(f"Completed steps: {len(ctx.completed_steps)}")
        
        if ctx.failed_hard_gates:
            print(f"Failed hard gates: {ctx.failed_hard_gates}")
            print("Cannot resume: hard gate failures")
            return 1
        
        print()
        print("Run is resumable")
        print("Note: Use PipelineExecutor.resume() programmatically")
        return 0
        
    except ResumeError as e:
        print(f"Error: {e}")
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    """Show run status."""
    run_dir = Path(args.run_dir)
    log_path = run_dir / "events.jsonl"
    
    if not log_path.exists():
        print(f"No run found at: {run_dir}")
        return 1
    
    try:
        # Use resume logic to reconstruct state
        from .resume import RunReconstructor
        event_log = EventLog(log_path)
        reconstructor = RunReconstructor(event_log)
        ctx = reconstructor.reconstruct()
        
        print(f"Run ID: {ctx.run_id}")
        print(f"State: {ctx.run_state.value}")
        print()
        
        print("Steps:")
        for step_id, state in sorted(ctx.step_states.items()):
            attempt = ctx.step_attempts.get(step_id, 0)
            attempt_str = f" (attempt {attempt})" if attempt > 0 else ""
            print(f"  {step_id:<30} {state.value}{attempt_str}")
        
        print()
        print(f"Completed: {len(ctx.completed_steps)}")
        if ctx.failed_hard_gates:
            print(f"Failed hard gates: {ctx.failed_hard_gates}")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_events(args: argparse.Namespace) -> int:
    """Show/stream events."""
    run_dir = Path(args.run_dir)
    log_path = run_dir / "events.jsonl"
    
    if not log_path.exists():
        print(f"No event log found at: {log_path}")
        return 1
    
    event_log = EventLog(log_path)
    
    if args.tail:
        # Show last N events
        events = event_log.tail(n=args.tail)
        for event in events:
            if args.json:
                print(json.dumps(event, separators=(',', ':')))
            else:
                _print_event_human(event)
    elif args.follow:
        # Stream events (simplified - real impl would use inotify)
        print("Streaming events (Ctrl+C to stop)...")
        with event_log.stream() as f:
            for line in f:
                event = json.loads(line)
                if args.json:
                    print(json.dumps(event, separators=(',', ':')))
                else:
                    _print_event_human(event)
                sys.stdout.flush()
    else:
        # Show all events
        events = event_log.read_all()
        for event in events:
            if args.json:
                print(json.dumps(event, separators=(',', ':')))
            else:
                _print_event_human(event)
    
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    """Show run summary."""
    run_dir = Path(args.run_dir)
    
    try:
        summary = generate_summary(run_dir)
        
        if args.json:
            print(json.dumps(summary.to_dict(), indent=2))
        else:
            print(summary.to_text())
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


def _print_event_human(event: dict) -> None:
    """Print event in human-readable format."""
    timestamp = event.get("timestamp_utc", "")
    event_type = event.get("event_type", "")
    step_id = event.get("step_id", "")
    
    parts = [timestamp[:19], event_type]
    
    if step_id:
        parts.append(f"[{step_id}]")
    
    if "error_class" in event:
        parts.append(f"error={event['error_class']}")
    
    if "reason" in event:
        parts.append(f"reason=\"{event['reason']}\"")
    
    print(" ".join(parts))


def main(argv: Optional[list[str]] = None) -> int:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Pipeline runner CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # start
    start_parser = subparsers.add_parser("start", help="Start new run")
    start_parser.add_argument("run_dir", help="Run directory")
    start_parser.add_argument("--run-id", help="Run ID (default: directory name)")
    start_parser.add_argument("--reason", help="Reason for run")
    
    # resume
    resume_parser = subparsers.add_parser("resume", help="Resume interrupted run")
    resume_parser.add_argument("run_dir", help="Run directory")
    
    # status
    status_parser = subparsers.add_parser("status", help="Show run status")
    status_parser.add_argument("run_dir", help="Run directory")
    
    # events
    events_parser = subparsers.add_parser("events", help="Show/stream events")
    events_parser.add_argument("run_dir", help="Run directory")
    events_parser.add_argument("--tail", type=int, help="Show last N events")
    events_parser.add_argument("--follow", "-f", action="store_true", help="Follow events (tail -f)")
    events_parser.add_argument("--json", action="store_true", help="JSON output")
    
    # summary
    summary_parser = subparsers.add_parser("summary", help="Show run summary")
    summary_parser.add_argument("run_dir", help="Run directory")
    summary_parser.add_argument("--json", action="store_true", help="JSON output")
    
    args = parser.parse_args(argv)
    
    if not args.command:
        parser.print_help()
        return 1
    
    commands = {
        "start": cmd_start,
        "resume": cmd_resume,
        "status": cmd_status,
        "events": cmd_events,
        "summary": cmd_summary,
    }
    
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
