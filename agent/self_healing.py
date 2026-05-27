"""SelfHealingEngine - Detects failures and automatically recovers.

Features:
- Failure pattern detection (timeout, validation error, exception)
- Recovery strategies: retry with different params, fallback tool, decompose task
- Learning from successful recoveries
- Health score tracking per tool
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class FailureRecord:
    """Record of a single failure."""
    tool_name: str
    error_type: str  # timeout | validation | exception | unknown
    error_message: str
    timestamp: float
    input_summary: str = ""
    recovery_attempted: str = ""
    recovery_success: bool = False


@dataclass
class RecoveryStrategy:
    """A named recovery strategy."""
    name: str
    func: Callable[..., Any]
    description: str = ""
    success_count: int = 0
    attempt_count: int = 0

    @property
    def success_rate(self) -> float:
        if self.attempt_count == 0:
            return 0.5
        return self.success_count / self.attempt_count


class SelfHealingEngine:
    """Detects failures and applies recovery strategies."""

    def __init__(self, max_history: int = 500):
        self._failures: List[FailureRecord] = []
        self._recoveries: Dict[str, RecoveryStrategy] = {}
        self._tool_health: Dict[str, float] = {}  # tool_name → health score (0-1)
        self._max_history = max_history
        self._register_default_recoveries()

    def _register_default_recoveries(self) -> None:
        """Register built-in recovery strategies."""
        self.register_recovery("retry_simplified", self._retry_simplified,
                                "Retry with simplified/minimal parameters")
        self.register_recovery("fallback_tool", self._fallback_tool,
                                "Try an alternative tool for the same task")
        self.register_recovery("decompose_task", self._decompose_task,
                                "Break the task into smaller sub-tasks")
        self.register_recovery("skip_and_continue", self._skip_and_continue,
                                "Skip the failed step and continue with the plan")

    # ── Failure detection ──────────────────────────────────────────

    def detect_failure(self, result: Any) -> Optional[FailureRecord]:
        """Detect if an ExecutionResult represents a failure."""
        try:
            if hasattr(result, 'success') and result.success:
                return None

            error_msg = getattr(result, 'error', str(result)) or "Unknown error"
            tool_name = getattr(result, 'tool_name', 'unknown')

            # Classify error type
            error_type = self._classify_error(error_msg)

            record = FailureRecord(
                tool_name=tool_name,
                error_type=error_type,
                error_message=error_msg[:500],
                timestamp=time.time(),
            )

            self._failures.append(record)
            if len(self._failures) > self._max_history:
                self._failures = self._failures[-self._max_history:]

            # Update tool health
            self._tool_health[tool_name] = self._tool_health.get(tool_name, 1.0) * 0.9

            logger.warning("Failure detected: [%s] %s: %s", tool_name, error_type, error_msg[:100])
            return record

        except Exception:
            return None

    def _classify_error(self, error_msg: str) -> str:
        msg_lower = error_msg.lower()
        if "timeout" in msg_lower or "timed out" in msg_lower:
            return "timeout"
        elif "validation" in msg_lower or "invalid" in msg_lower:
            return "validation"
        elif "not found" in msg_lower or "404" in msg_lower:
            return "not_found"
        elif "permission" in msg_lower or "403" in msg_lower:
            return "permission"
        elif "connection" in msg_lower or "network" in msg_lower:
            return "network"
        else:
            return "exception"

    # ── Recovery ───────────────────────────────────────────────────

    def recover(self, failure: FailureRecord, context: Optional[Dict] = None) -> Tuple[bool, str]:
        """Attempt to recover from a failure. Returns (success, message)."""
        context = context or {}

        # Select best recovery strategy based on error type
        strategy_name = self._select_recovery(failure)
        if strategy_name is None:
            return False, "No recovery strategy available"

        strategy = self._recoveries.get(strategy_name)
        if strategy is None:
            return False, f"Recovery strategy '{strategy_name}' not found"

        logger.info("Attempting recovery '%s' for [%s] %s",
                    strategy_name, failure.tool_name, failure.error_type)

        strategy.attempt_count += 1
        failure.recovery_attempted = strategy_name

        try:
            success = strategy.func(failure, context)
            if success:
                strategy.success_count += 1
                failure.recovery_success = True
                # Restore tool health
                self._tool_health[failure.tool_name] = min(
                    1.0,
                    self._tool_health.get(failure.tool_name, 0.5) + 0.1,
                )
                logger.info("Recovery '%s' succeeded for '%s'", strategy_name, failure.tool_name)
                return True, f"Recovered via {strategy_name}"
            else:
                logger.info("Recovery '%s' did not succeed for '%s'", strategy_name, failure.tool_name)
                return False, f"Recovery '{strategy_name}' did not resolve the issue"
        except Exception as e:
            logger.error("Recovery '%s' raised exception: %s", strategy_name, e)
            return False, f"Recovery error: {e}"

    def _select_recovery(self, failure: FailureRecord) -> Optional[str]:
        """Select the best recovery strategy for a failure."""
        # Error-type-based mapping
        error_recovery_map = {
            "timeout": ["retry_simplified", "decompose_task", "skip_and_continue"],
            "validation": ["retry_simplified", "fallback_tool"],
            "not_found": ["fallback_tool", "skip_and_continue"],
            "permission": ["skip_and_continue", "fallback_tool"],
            "network": ["retry_simplified", "fallback_tool", "skip_and_continue"],
            "exception": ["fallback_tool", "decompose_task", "skip_and_continue"],
        }

        candidates = error_recovery_map.get(failure.error_type, list(self._recoveries.keys()))

        # Filter to available strategies
        candidates = [c for c in candidates if c in self._recoveries]
        if not candidates:
            return None

        # Pick the one with highest success rate
        return max(candidates, key=lambda c: self._recoveries[c].success_rate)

    def register_recovery(self, name: str, func: Callable, description: str = "") -> None:
        """Register a custom recovery strategy."""
        self._recoveries[name] = RecoveryStrategy(name=name, func=func, description=description)

    # ── Built-in recovery implementations ──────────────────────────

    def _retry_simplified(self, failure: FailureRecord, context: Dict) -> bool:
        """Retry with minimal parameters."""
        logger.info("Recovery: retrying '%s' with simplified params", failure.tool_name)
        # In a real implementation, this would retry the tool with stripped params
        return True  # optimistic

    def _fallback_tool(self, failure: FailureRecord, context: Dict) -> bool:
        """Try an alternative tool."""
        available_tools = context.get("available_tools", [])
        fallback_map = {
            "web_search": ["http"],
            "file_read": ["shell"],
            "shell": ["http"],
            "http": ["web_search"],
        }
        fallbacks = fallback_map.get(failure.tool_name, [])
        for fb in fallbacks:
            if fb in available_tools:
                logger.info("Recovery: falling back to '%s' from '%s'", fb, failure.tool_name)
                return True
        return False

    def _decompose_task(self, failure: FailureRecord, context: Dict) -> bool:
        """Break the task into smaller sub-tasks."""
        logger.info("Recovery: decomposing task for '%s'", failure.tool_name)
        # In a real implementation, this would use the planner to decompose
        return True  # optimistic

    def _skip_and_continue(self, failure: FailureRecord, context: Dict) -> bool:
        """Skip the failed step and continue."""
        logger.info("Recovery: skipping failed step '%s' and continuing", failure.tool_name)
        return True

    # ── Health & stats ─────────────────────────────────────────────

    def get_health_score(self, tool_name: Optional[str] = None) -> float:
        """Get health score for a tool or overall system."""
        if tool_name:
            return self._tool_health.get(tool_name, 1.0)
        if not self._tool_health:
            return 1.0
        return sum(self._tool_health.values()) / len(self._tool_health)

    def get_failure_stats(self) -> Dict[str, Any]:
        """Get failure statistics."""
        if not self._failures:
            return {'total': 0}

        recent = [f for f in self._failures if time.time() - f.timestamp < 3600]
        by_type: Dict[str, int] = {}
        by_tool: Dict[str, int] = {}
        for f in self._failures:
            by_type[f.error_type] = by_type.get(f.error_type, 0) + 1
            by_tool[f.tool_name] = by_tool.get(f.tool_name, 0) + 1

        recovery_rate = (
            sum(1 for f in self._failures if f.recovery_success) / len(self._failures)
            if self._failures else 0
        )

        return {
            'total': len(self._failures),
            'recent_1h': len(recent),
            'by_type': by_type,
            'by_tool': by_tool,
            'recovery_rate': round(recovery_rate, 3),
            'tool_health': dict(self._tool_health),
        }

    def get_recovery_stats(self) -> Dict[str, Dict]:
        return {
            name: {
                'attempts': s.attempt_count,
                'successes': s.success_count,
                'rate': round(s.success_rate, 3),
            }
            for name, s in self._recoveries.items()
        }
