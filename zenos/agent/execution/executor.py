from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from zenos.agent.execution.safety import SafetyChecker

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of a single tool execution."""

    tool_name: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    duration_seconds: float = 0.0
    attempts: int = 1

    def __repr__(self) -> str:
        status = "ok" if self.success else "failed"
        return f"ExecutionResult({self.tool_name}, {status}, {self.duration_seconds:.3f}s)"


class Executor:
    """Tool execution engine with retry, batching, and safety integration.

    Parameters
    -------
    max_retries:
        Default maximum retry attempts for :meth:`retry_with_backoff`.
    base_delay:
        Base delay (seconds) for exponential backoff.
    max_workers:
        Thread-pool size for :meth:`batch_execute`.
    safety_checker:
        Optional safety checker.  A default is created when *None*.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_workers: int = 4,
        safety_checker: Optional[SafetyChecker] = None,
    ) -> None:
        self.max_retries: int = max_retries
        self.base_delay: float = base_delay
        self.max_workers: int = max_workers
        self.safety_checker: SafetyChecker = safety_checker or SafetyChecker()
        self._tool_registry: Dict[str, Callable[..., Any]] = {}

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def register_tool(self, name: str, func: Callable[..., Any]) -> None:
        """Register a callable tool."""
        self._tool_registry[name] = func
        logger.info("Executor registered tool '%s'.", name)

    # ------------------------------------------------------------------
    # Single execution
    # ------------------------------------------------------------------

    def execute_tool(
        self,
        tool_name: str,
        tool_input: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ExecutionResult:
        """Execute a single tool by name.

        Parameters
        ----------
        tool_name:
            Registered tool name.
        tool_input:
            Dictionary of input parameters.
        **kwargs:
            Extra keyword arguments forwarded to the tool.

        Returns
        -------
        ExecutionResult
            Structured result with timing and error information.
        """
        tool_input = tool_input or {}

        # Safety: validate input
        input_ok, input_msg = self.safety_checker.validate_input(tool_name, tool_input)
        if not input_ok:
            logger.warning("Input validation failed for '%s': %s", tool_name, input_msg)
            return ExecutionResult(
                tool_name=tool_name,
                success=False,
                error=f"Input validation failed: {input_msg}",
            )

        func = self._tool_registry.get(tool_name)
        if func is None:
            return ExecutionResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool '{tool_name}' is not registered.",
            )

        start = time.monotonic()
        try:
            merged = {**tool_input, **kwargs}
            result = func(**merged)
            duration = time.monotonic() - start

            # Safety: validate output
            output_ok, output_msg = self.safety_checker.validate_output(tool_name, result)
            if not output_ok:
                logger.warning("Output validation failed for '%s': %s", tool_name, output_msg)
                return ExecutionResult(
                    tool_name=tool_name,
                    success=False,
                    error=f"Output validation failed: {output_msg}",
                    duration_seconds=duration,
                )

            return ExecutionResult(
                tool_name=tool_name,
                success=True,
                result=result,
                duration_seconds=duration,
            )
        except Exception:
            duration = time.monotonic() - start
            logger.exception("Tool '%s' raised an exception.", tool_name)
            return ExecutionResult(
                tool_name=tool_name,
                success=False,
                error=str(__import__("sys").exc_info()[1]),
                duration_seconds=duration,
            )

    # ------------------------------------------------------------------
    # Batch execution
    # ------------------------------------------------------------------

    def batch_execute(
        self,
        calls: List[Tuple[str, Dict[str, Any]]],
        parallel: bool = False,
    ) -> List[ExecutionResult]:
        """Execute multiple tool calls, optionally in parallel.

        Parameters
        ----------
        calls:
            List of ``(tool_name, input_dict)`` tuples.
        parallel:
            When *True*, use a thread pool for concurrent execution.

        Returns
        -------
        list[ExecutionResult]
            Results in the same order as *calls*.
        """
        if not calls:
            return []

        if not parallel:
            return [self.execute_tool(name, inp) for name, inp in calls]

        results: List[Optional[ExecutionResult]] = [None] * len(calls)
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_idx = {}
            for idx, (name, inp) in enumerate(calls):
                future = pool.submit(self.execute_tool, name, inp)
                future_to_idx[future] = idx

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception:
                    name, _ = calls[idx]
                    results[idx] = ExecutionResult(
                        tool_name=name,
                        success=False,
                        error=str(__import__("sys").exc_info()[1]),
                    )

        return results  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Retry with exponential backoff
    # ------------------------------------------------------------------

    def retry_with_backoff(
        self,
        tool_name: str,
        tool_input: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
        base_delay: Optional[float] = None,
        retryable_exceptions: Optional[Tuple[type, ...]] = None,
        **kwargs: Any,
    ) -> ExecutionResult:
        """Execute a tool with exponential-backoff retries.

        Parameters
        ----------
        tool_name:
            Registered tool name.
        tool_input:
            Input dictionary.
        max_retries:
            Override for the instance default.
        base_delay:
            Override for the instance default.
        retryable_exceptions:
            Tuple of exception types that trigger a retry.  When *None*,
            all exceptions are retryable.
        **kwargs:
            Extra keyword arguments forwarded to the tool.

        Returns
        -------
        ExecutionResult
            The first successful result, or the last failed result after
            exhausting retries.
        """
        retries = max_retries if max_retries is not None else self.max_retries
        delay = base_delay if base_delay is not None else self.base_delay
        retryable = retryable_exceptions or (Exception,)

        last_result: Optional[ExecutionResult] = None

        for attempt in range(1, retries + 2):  # 1 initial + retries
            result = self.execute_tool(tool_name, tool_input, **kwargs)
            result.attempts = attempt

            if result.success:
                if attempt > 1:
                    logger.info(
                        "Tool '%s' succeeded on attempt %d/%d.",
                        tool_name,
                        attempt,
                        retries + 1,
                    )
                return result

            last_result = result

            if attempt <= retries:
                # Check if the error is retryable
                # (we only have the error string, so we retry by default)
                wait = delay * (2 ** (attempt - 1))
                logger.warning(
                    "Tool '%s' attempt %d/%d failed (error: %s). "
                    "Retrying in %.1fs…",
                    tool_name,
                    attempt,
                    retries + 1,
                    result.error,
                    wait,
                )
                time.sleep(wait)

        logger.error(
            "Tool '%s' failed after %d attempt(s).", tool_name, retries + 1
        )
        return last_result  # type: ignore[return-value]

    def __repr__(self) -> str:
        return (
            f"Executor(tools={len(self._tool_registry)}, "
            f"max_retries={self.max_retries}, workers={self.max_workers})"
        )
