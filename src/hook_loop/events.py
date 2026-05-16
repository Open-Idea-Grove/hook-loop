from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Event:
    schema_version: int
    event_id: str
    session_id: str
    run_id: str
    timestamp: str
    state: str
    event_type: str
    actor: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Event":
        return cls(
            schema_version=int(raw["schema_version"]),
            event_id=str(raw["event_id"]),
            session_id=str(raw["session_id"]),
            run_id=str(raw["run_id"]),
            timestamp=str(raw["timestamp"]),
            state=str(raw["state"]),
            event_type=str(raw["event_type"]),
            actor=str(raw["actor"]),
            payload=dict(raw.get("payload", {})),
        )


def new_event(
    session_id: str,
    run_id: str,
    state: str,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
) -> Event:
    return Event(
        schema_version=SCHEMA_VERSION,
        event_id=str(uuid4()),
        session_id=session_id,
        run_id=run_id,
        timestamp=datetime.now(UTC).isoformat(),
        state=state,
        event_type=event_type,
        actor=actor,
        payload=payload,
    )
