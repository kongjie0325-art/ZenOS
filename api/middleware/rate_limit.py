"""Rate limiting middleware for ZenOS API."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional
from http import HTTPStatus


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit rule."""

    key: str
    max_requests: int
    window_seconds: float
    scope: str = "ip"  # "ip", "user", "global"


@dataclass
class RateLimitState:
    """Tracks request count within a sliding window."""

    count: int = 0
    window_start: float = 0.0


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int = 0
    reset_at: float = 0.0
    retry_after: float = 0.0
    limit: int = 0


class RateLimitMiddleware:
    """Token-bucket style rate limiting middleware.

    Tracks request counts per key (IP, user, or global) within
    a sliding window and rejects requests that exceed the configured
    threshold.

    Thread-safe via internal locking.
    """

    def __init__(
        self,
        default_max_requests: int = 100,
        default_window_seconds: float = 60.0,
    ) -> None:
        """Initialize the rate limiter.

        Args:
            default_max_requests: Default maximum requests per window.
            default_window_seconds: Default window duration in seconds.
        """
        self._default_max = default_max_requests
        self._default_window = default_window_seconds
        self._rules: dict[str, RateLimitConfig] = {}
        self._state: dict[str, RateLimitState] = {}
        self._lock = Lock()

    def add_rule(self, config: RateLimitConfig) -> None:
        """Register a rate limit rule.

        Args:
            config: The rate limit configuration to add.
        """
        self._rules[config.key] = config

    def check(
        self,
        key: str,
        rule_key: str = "default",
    ) -> RateLimitResult:
        """Check whether a request is within the rate limit.

        Args:
            key: The rate limit bucket key (e.g. IP address or user ID).
            rule_key: Which registered rule to apply.

        Returns:
            RateLimitResult indicating whether the request is allowed.
        """
        rule = self._rules.get(
            rule_key,
            RateLimitConfig(
                key="default",
                max_requests=self._default_max,
                window_seconds=self._default_window,
            ),
        )

        composite_key = f"{rule.scope}:{key}"
        now = time.time()

        with self._lock:
            state = self._state.get(composite_key)
            if state is None or now - state.window_start >= rule.window_seconds:
                # New window
                state = RateLimitState(count=0, window_start=now)
                self._state[composite_key] = state

            state.count += 1
            remaining = max(0, rule.max_requests - state.count)
            reset_at = state.window_start + rule.window_seconds
            allowed = state.count <= rule.max_requests
            retry_after = max(0.0, reset_at - now) if not allowed else 0.0

            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                reset_at=reset_at,
                retry_after=retry_after,
                limit=rule.max_requests,
            )

    def cleanup(self, max_age_seconds: float = 3600.0) -> int:
        """Remove stale rate limit state entries.

        Args:
            max_age_seconds: Remove entries older than this many seconds.

        Returns:
            Number of entries removed.
        """
        now = time.time()
        removed = 0
        with self._lock:
            stale = [
                k
                for k, v in self._state.items()
                if now - v.window_start > max_age_seconds
            ]
            for k in stale:
                del self._state[k]
                removed += 1
        return removed
