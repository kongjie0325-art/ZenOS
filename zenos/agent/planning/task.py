from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, List, Optional


class TaskStatus(str, Enum):
    """Lifecycle states of a ``Task``."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class TaskPriority(int, Enum):
    """Priority levels — higher value means higher priority."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Task:
    """A single unit of work within a plan.

    Attributes
    ----------
    id:
        Auto-generated unique identifier.
    description:
        Human-readable description of what the task should accomplish.
    status:
        Current lifecycle state (default ``PENDING``).
    priority:
        Scheduling priority (default ``MEDIUM``).
    dependencies:
        List of task-ids that must complete before this task can start.
    result:
        Arbitrary result payload set after successful execution.
    created_at:
        UTC timestamp of task creation.
    completed_at:
        UTC timestamp of task completion (``None`` until done).
    step_index:
        Zero-based position of this task within its parent plan.
    metadata:
        Arbitrary key-value data for downstream consumers.
    """

    description: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    dependencies: List[str] = field(default_factory=list)
    result: Optional[Any] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    step_index: int = 0
    metadata: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        """Return ``True`` when the task can no longer change state."""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

    @property
    def duration(self) -> Optional[float]:
        """Elapsed wall-clock seconds between creation and completion."""
        if self.completed_at is None:
            return None
        return (self.completed_at - self.created_at).total_seconds()

    def mark_completed(self, result: Any = None) -> None:
        """Transition the task to ``COMPLETED`` and store *result*."""
        self.result = result
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.utcnow()

    def mark_failed(self) -> None:
        """Transition the task to ``FAILED``."""
        self.status = TaskStatus.FAILED

    def __repr__(self) -> str:
        return (
            f"Task(id={self.id[:8]}, desc={self.description!r}, "
            f"status={self.status.value}, priority={self.priority.name})"
        )
