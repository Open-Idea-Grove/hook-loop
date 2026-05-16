from __future__ import annotations

import json
from pathlib import Path

from hook_loop.events import Event


class JsonlEventLog:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def append(self, event: Event) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")

    def read_all(self) -> list[Event]:
        if not self.path.exists():
            return []
        events: list[Event] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    events.append(Event.from_dict(json.loads(line)))
        return events


def recover_current_state(events: list[Event]) -> str | None:
    current: str | None = None
    for event in events:
        if event.event_type == "session_initialized":
            current = event.payload.get("initial_state", event.state)
        elif event.event_type == "state_transitioned":
            current = event.payload.get("to", event.state)
        else:
            current = event.state
    return current
