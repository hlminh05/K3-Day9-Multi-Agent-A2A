"""Central trace recorder; workers cannot append or overwrite trace files."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, Decimal)):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value)!r}")


class TraceRecorder:
    def __init__(self) -> None:
        self.run_id = str(uuid.uuid4())
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._sequence = 0
        self._events: list[dict[str, Any]] = []

    def record(
        self,
        case_id: str,
        sender: str,
        receiver: str,
        message_type: str,
        payload: Any,
    ) -> None:
        self._sequence += 1
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, default=_json_default
        )
        self._events.append(
            {
                "run_id": self.run_id,
                "sequence": self._sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "case_id": case_id,
                "sender": sender,
                "receiver": receiver,
                "message_type": message_type,
                "payload_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "payload": payload,
            }
        )

    @property
    def event_count(self) -> int:
        return len(self._events)

    def write_latest(self, path: Path) -> None:
        content = "".join(
            json.dumps(event, ensure_ascii=False, default=_json_default) + "\n"
            for event in self._events
        )
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

