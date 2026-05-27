"""State Management - System-wide state machine and snapshotting.

Manages the overall system state with transitions, persistence,
and rollback capability.
"""

from __future__ import annotations

import json
import logging
import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class SystemState(Enum):
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    DEGRADED = "degraded"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"


VALID_TRANSITIONS = {
    SystemState.INITIALIZING: {SystemState.READY, SystemState.ERROR, SystemState.STOPPED},
    SystemState.READY: {SystemState.RUNNING, SystemState.ERROR, SystemState.SHUTTING_DOWN},
    SystemState.RUNNING: {SystemState.PAUSED, SystemState.DEGRADED, SystemState.ERROR, SystemState.SHUTTING_DOWN},
    SystemState.PAUSED: {SystemState.RUNNING, SystemState.ERROR, SystemState.SHUTTING_DOWN},
    SystemState.DEGRADED: {SystemState.RUNNING, SystemState.ERROR, SystemState.SHUTTING_DOWN},
    SystemState.ERROR: {SystemState.INITIALIZING, SystemState.SHUTTING_DOWN, SystemState.STOPPED},
    SystemState.SHUTTING_DOWN: {SystemState.STOPPED},
    SystemState.STOPPED: {SystemState.INITIALIZING},
}


@dataclass
class StateSnapshot:
    state: SystemState
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: int = 0


class StateManager:
    """Thread-safe state machine with history and snapshotting."""

    def __init__(self, initial: SystemState = SystemState.INITIALIZING):
        self._state = initial
        self._history: List[StateSnapshot] = []
        self._version = 0
        self._listeners: List[Callable] = []
        self._data: Dict[str, Any] = {}
        self._record_transition(initial)

    @property
    def state(self) -> SystemState:
        return self._state

    @property
    def version(self) -> int:
        return self._version

    def transition(self, new_state: SystemState, **metadata) -> bool:
        allowed = VALID_TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            logger.warning(f"Invalid transition: {self._state.value} -> {new_state.value}")
            return False
        old_state = self._state
        self._state = new_state
        self._version += 1
        self._record_transition(new_state, metadata)
        logger.info(f"State: {old_state.value} -> {new_state.value}")
        for listener in self._listeners:
            try:
                listener(old_state, new_state, metadata)
            except Exception as e:
                logger.error(f"State listener error: {e}")
        return True

    def can_transition_to(self, new_state: SystemState) -> bool:
        return new_state in VALID_TRANSITIONS.get(self._state, set())

    def on_transition(self, listener: Callable) -> None:
        self._listeners.append(listener)

    def set_data(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get_data(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def snapshot(self) -> StateSnapshot:
        return StateSnapshot(
            state=self._state,
            timestamp=time.time(),
            metadata=dict(self._data),
            version=self._version,
        )

    def get_history(self, limit: int = 50) -> List[StateSnapshot]:
        return self._history[-limit:]

    def save_snapshot(self, path: str) -> None:
        snap = self.snapshot()
        data = {
            'state': snap.state.value,
            'timestamp': snap.timestamp,
            'metadata': snap.metadata,
            'version': snap.version,
        }
        Path(path).write_text(json.dumps(data, indent=2))

    def load_snapshot(self, path: str) -> bool:
        try:
            data = json.loads(Path(path).read_text())
            self._state = SystemState(data['state'])
            self._data = data.get('metadata', {})
            self._version = data.get('version', 0)
            self._record_transition(self._state)
            return True
        except Exception as e:
            logger.error(f"Failed to load snapshot: {e}")
            return False

    def _record_transition(self, state: SystemState, metadata: Optional[Dict] = None):
        self._history.append(StateSnapshot(
            state=state,
            timestamp=time.time(),
            metadata=metadata or {},
            version=self._version,
        ))
        if len(self._history) > 1000:
            self._history = self._history[-1000:]
