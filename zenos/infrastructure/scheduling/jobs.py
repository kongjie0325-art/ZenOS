"""Job definitions for the ZenOS task scheduler."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable


class JobStatus(enum.Enum):
    """Represents the current lifecycle state of a scheduled job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class JobPriority(enum.IntEnum):
    """Priority levels for job execution ordering."""

    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


@dataclass
class Job:
    """Represents a schedulable unit of work.

    Attributes:
        name: Human-readable job identifier.
        func: The callable to execute when the job fires.
        trigger: One of 'cron', 'interval', or 'oneshot'.
        args: Positional arguments forwarded to ``func``.
        kwargs: Keyword arguments forwarded to ``func``.
        status: Current lifecycle state.
        priority: Scheduling priority for execution ordering.
        max_retries: Maximum number of retry attempts on failure.
        next_run: The next scheduled run time (UTC).
        id: Unique auto-generated job identifier.
        created_at: Timestamp when the job was created.
        last_run: Timestamp of the most recent execution attempt.
        retry_count: Number of retries attempted so far.
        cron_expr: Cron expression string (only for cron triggers).
        interval_seconds: Interval duration in seconds (only for interval triggers).
        oneshot_at: Specific run time (only for oneshot triggers).
        result: Return value from the last successful execution.
        error: Error message from the last failed execution.
    """

    name: str
    func: Callable[..., Any]
    trigger: str  # 'cron' | 'interval' | 'oneshot'
    args: tuple = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)
    status: JobStatus = JobStatus.PENDING
    priority: JobPriority = JobPriority.NORMAL
    max_retries: int = 3
    next_run: datetime | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_run: datetime | None = None
    retry_count: int = 0
    cron_expr: str | None = None
    interval_seconds: float | None = None
    oneshot_at: datetime | None = None
    result: Any = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.trigger not in ("cron", "interval", "oneshot"):
            raise ValueError(f"Invalid trigger type: {self.trigger!r}")

    @property
    def is_active(self) -> bool:
        """Return True if the job is eligible for execution."""
        return self.status in (JobStatus.PENDING, JobStatus.RUNNING)

    @property
    def has_retries_remaining(self) -> bool:
        """Return True if the job can still be retried after a failure."""
        return self.retry_count < self.max_retries

    def reset(self) -> None:
        """Reset the job to its initial pending state."""
        self.status = JobStatus.PENDING
        self.retry_count = 0
        self.last_run = None
        self.result = None
        self.error = None

    def mark_running(self) -> None:
        """Transition the job to the running state."""
        self.status = JobStatus.RUNNING
        self.last_run = datetime.utcnow()

    def mark_completed(self, result: Any = None) -> None:
        """Transition the job to the completed state."""
        self.status = JobStatus.COMPLETED
        self.result = result
        self.error = None

    def mark_failed(self, error: str) -> None:
        """Transition the job to the failed state and increment retry count."""
        self.retry_count += 1
        self.error = error
        if self.has_retries_remaining:
            self.status = JobStatus.PENDING
        else:
            self.status = JobStatus.FAILED

    def to_dict(self) -> dict[str, Any]:
        """Serialize the job metadata to a dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "trigger": self.trigger,
            "status": self.status.value,
            "priority": self.priority.value,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "created_at": self.created_at.isoformat(),
            "cron_expr": self.cron_expr,
            "interval_seconds": self.interval_seconds,
            "oneshot_at": self.oneshot_at.isoformat() if self.oneshot_at else None,
            "error": self.error,
        }
