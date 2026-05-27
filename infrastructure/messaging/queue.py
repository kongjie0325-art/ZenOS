"""Priority message queue with blocking and non-blocking operations."""

from __future__ import annotations

import enum
import heapq
import threading
import time
from dataclasses import dataclass, field
from typing import Any


class MessagePriority(enum.IntEnum):
    """Standard priority levels for queued messages."""

    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


@dataclass(order=True)
class _QueueEntry:
    """Internal heap entry wrapping a message with priority and ordering.

    Attributes:
        priority: Numeric priority (lower = higher priority).
        seq: Monotonically increasing sequence number to preserve FIFO
            ordering among entries with equal priority.
        message: The actual message payload (excluded from comparison).
    """

    priority: int
    seq: int
    message: Any = field(compare=False)


@dataclass
class PriorityMessageQueue:
    """Thread-safe priority message queue.

    Messages are dequeued in priority order (CRITICAL first, BACKGROUND last).
    Within the same priority level, messages are dequeued in FIFO order.

    Supports both blocking (with timeout) and non-blocking pop operations.

    Example::

        queue = PriorityMessageQueue(maxsize=1000)
        queue.push("urgent alert", priority=MessagePriority.CRITICAL)
        queue.push("routine log", priority=MessagePriority.LOW)
        msg = queue.pop()  # Returns "urgent alert"
    """

    maxsize: int = 0  # 0 means unlimited

    def __post_init__(self) -> None:
        self._heap: list[_QueueEntry] = []
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._not_full = threading.Condition(self._lock)
        self._seq = 0
        self._size = 0

    # ------------------------------------------------------------------ #
    #  Core operations
    # ------------------------------------------------------------------ #

    def push(
        self,
        message: Any,
        *,
        priority: MessagePriority = MessagePriority.NORMAL,
        block: bool = True,
        timeout: float | None = None,
    ) -> bool:
        """Add a message to the queue.

        Args:
            message: The payload to enqueue.
            priority: Message priority level.
            block: If True, block until space is available (when queue is
                at ``maxsize``). If False, raise immediately when full.
            timeout: Maximum seconds to block. ``None`` means wait
                indefinitely. Only relevant when ``block`` is True.

        Returns:
            True if the message was enqueued.

        Raises:
            TimeoutError: If ``block`` is True and ``timeout`` expires
                before space is available.
            RuntimeError: If ``block`` is False and the queue is full.
        """
        with self._not_full:
            if self.maxsize > 0:
                if not block:
                    if self._size >= self.maxsize:
                        raise RuntimeError("Queue is full")
                elif timeout is None:
                    while self._size >= self.maxsize:
                        self._not_full.wait()
                else:
                    deadline = time.monotonic() + timeout
                    while self._size >= self.maxsize:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError(
                                f"Timed out after {timeout}s waiting to push"
                            )
                        self._not_full.wait(timeout=remaining)

            entry = _QueueEntry(priority=priority.value, seq=self._seq, message=message)
            self._seq += 1
            heapq.heappush(self._heap, entry)
            self._size += 1
            self._not_empty.notify()
            return True

    def pop(
        self,
        *,
        block: bool = True,
        timeout: float | None = None,
    ) -> Any:
        """Remove and return the highest-priority message.

        Args:
            block: If True, block until a message is available.
                If False, raise immediately when empty.
            timeout: Maximum seconds to block. ``None`` means wait
                indefinitely.

        Returns:
            The dequeued message payload.

        Raises:
            TimeoutError: If ``block`` is True and ``timeout`` expires
                before a message is available.
            IndexError: If ``block`` is False and the queue is empty.
        """
        with self._not_empty:
            if not block:
                if self._size == 0:
                    raise IndexError("Pop from an empty queue")
            elif timeout is None:
                while self._size == 0:
                    self._not_empty.wait()
            else:
                deadline = time.monotonic() + timeout
                while self._size == 0:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            f"Timed out after {timeout}s waiting to pop"
                        )
                    self._not_empty.wait(timeout=remaining)

            entry = heapq.heappop(self._heap)
            self._size -= 1
            self._not_full.notify()
            return entry.message

    def peek(self, default: Any = None) -> Any:
        """Return the next message without removing it.

        Args:
            default: Value to return if the queue is empty.

        Returns:
            The highest-priority message, or ``default`` if the queue is empty.
        """
        with self._lock:
            if self._size == 0:
                return default
            return self._heap[0].message

    # ------------------------------------------------------------------ #
    #  Introspection
    # ------------------------------------------------------------------ #

    def size(self) -> int:
        """Return the current number of messages in the queue."""
        with self._lock:
            return self._size

    def is_empty(self) -> bool:
        """Return True if the queue contains no messages."""
        with self._lock:
            return self._size == 0

    def is_full(self) -> bool:
        """Return True if the queue has reached ``maxsize``."""
        with self._lock:
            if self.maxsize <= 0:
                return False
            return self._size >= self.maxsize

    def clear(self) -> int:
        """Remove all messages from the queue.

        Returns:
            The number of messages that were cleared.
        """
        with self._lock:
            count = self._size
            self._heap.clear()
            self._size = 0
            self._not_full.notify_all()
            return count

    def __len__(self) -> int:
        return self.size()

    def __bool__(self) -> bool:
        return not self.is_empty()
