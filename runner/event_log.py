"""Event log writer with streaming support.

Append-only JSONL format optimized for tail/SSE consumption.
"""

import json
from pathlib import Path
from typing import Optional, TextIO

from .contracts import Event


class EventLog:
    """Append-only event log with streaming support."""
    
    def __init__(self, log_path: Path):
        """Initialize event log.
        
        Args:
            log_path: Path to events.jsonl file
        """
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Ensure file exists
        if not self.log_path.exists():
            self.log_path.touch(mode=0o600)
    
    def append(self, event: Event) -> None:
        """Append event to log (atomic line write).
        
        Args:
            event: Event to append
        """
        line = json.dumps(event.to_dict(), separators=(',', ':'))
        
        # Atomic append: single write syscall with newline
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
            f.flush()  # ensure visible for tail consumers
    
    def read_all(self) -> list[Event]:
        """Read all events from log.
        
        Returns:
            List of events in order
        """
        if not self.log_path.exists():
            return []
        
        events = []
        with open(self.log_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                # Reconstruct Event (simplified - full deserialization would need type mapping)
                events.append(data)
        
        return events
    
    def tail(self, n: int = 10) -> list[dict]:
        """Get last N events.
        
        Args:
            n: Number of events to retrieve
            
        Returns:
            List of event dicts (most recent last)
        """
        events = self.read_all()
        return events[-n:] if events else []
    
    def stream(self, follow: bool = False) -> TextIO:
        """Open log for streaming (tail -f equivalent).
        
        Args:
            follow: If True, keep file open for new events
            
        Returns:
            File handle for streaming
            
        Note:
            Caller responsible for closing handle.
            For SSE bridge, wrap in generator that yields new lines.
        """
        return open(self.log_path, 'r', encoding='utf-8')
