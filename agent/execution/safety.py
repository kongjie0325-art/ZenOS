from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class SafetyRule:
    """A single safety rule with a name, check callable, and blocking flag."""

    name: str
    check_fn: Callable[..., Tuple[bool, str]]
    block: bool = True  # When True, a failing check blocks execution

    def evaluate(self, *args: Any, **kwargs: Any) -> Tuple[bool, str]:
        """Run the check and return (passed, message)."""
        try:
            return self.check_fn(*args, **kwargs)
        except Exception as exc:
            logger.exception("Safety rule '%s' raised an exception.", self.name)
            return False, f"Rule '{self.name}' internal error: {exc}"


class SafetyChecker:
    """Safety validation layer for tool inputs, outputs, and actions.

    The checker maintains a registry of named ``SafetyRule`` objects and
    provides convenience methods :meth:`check`, :meth:`validate_input`, and
    :meth:`validate_output`.

    Parameters
    ----------
    strict:
        When *True*, any failing rule (including non-blocking ones) is
        treated as a hard failure.
    """

    # Patterns that are always rejected in string inputs
    _DANGEROUS_PATTERNS: List[re.Pattern[str]] = [
        re.compile(r"rm\s+-rf\s+/", re.IGNORECASE),
        re.compile(r":\(\)\s*\{.*};\s*:", re.IGNORECASE),  # fork bomb
        re.compile(r"DROP\s+TABLE", re.IGNORECASE),
    ]

    def __init__(self, strict: bool = False) -> None:
        self.strict: bool = strict
        self._rules: Dict[str, SafetyRule] = {}
        self._register_defaults()

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(
        self,
        name: str,
        check_fn: Callable[..., Tuple[bool, str]],
        block: bool = True,
    ) -> None:
        """Register a new safety rule.

        Parameters
        ----------
        name:
            Unique rule identifier.
        check_fn:
            Callable that returns ``(passed: bool, message: str)``.
        block:
            If ``True``, a failing check blocks execution.
        """
        if name in self._rules:
            logger.warning("Overwriting existing safety rule '%s'.", name)
        self._rules[name] = SafetyRule(name=name, check_fn=check_fn, block=block)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name.  Returns ``True`` if it existed."""
        return self._rules.pop(name, None) is not None

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def check(self, tool_name: str, tool_input: Any, tool_output: Any = None) -> Tuple[bool, str]:
        """Run all registered safety checks for a tool invocation.

        Parameters
        ----------
        tool_name:
            Name of the tool being invoked.
        tool_input:
            The input payload.
        tool_output:
            Optional output payload (checked when provided).

        Returns
        -------
        tuple[bool, str]
            ``(True, "ok")`` when all checks pass, otherwise
            ``(False, "<failure message>")``.
        """
        context = {"tool_name": tool_name, "input": tool_input, "output": tool_output}

        for rule in self._rules.values():
            passed, message = rule.evaluate(context)
            if not passed:
                level = "blocking" if rule.block else "warning"
                msg = f"Safety rule '{rule.name}' ({level}): {message}"
                if rule.block or self.strict:
                    logger.warning("Safety check failed — %s", msg)
                    return False, msg
                else:
                    logger.info("Safety warning — %s", msg)

        return True, "ok"

    def validate_input(self, tool_name: str, tool_input: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate *tool_input* before execution.

        Parameters
        ----------
        tool_name:
            Name of the tool.
        tool_input:
            Input dictionary to validate.

        Returns
        -------
        tuple[bool, str]
            ``(True, "ok")`` or ``(False, "<reason>")``.
        """
        # Check input size
        if len(str(tool_input)) > 1_000_000:
            return False, "Input exceeds maximum allowed size (1 MB)."

        # Check for dangerous string patterns
        input_str = str(tool_input)
        for pattern in self._DANGEROUS_PATTERNS:
            if pattern.search(input_str):
                return False, f"Input matches dangerous pattern: {pattern.pattern}"

        # Run registered rules
        return self.check(tool_name, tool_input)

    def validate_output(self, tool_name: str, tool_output: Any) -> Tuple[bool, str]:
        """Validate *tool_output* after execution.

        Parameters
        ----------
        tool_name:
            Name of the tool.
        tool_output:
            Output value to validate.

        Returns
        -------
        tuple[bool, str]
            ``(True, "ok")`` or ``(False, "<reason>")``.
        """
        # Check output size
        if len(str(tool_output)) > 10_000_000:
            return False, "Output exceeds maximum allowed size (10 MB)."

        return self.check(tool_name, {}, tool_output)

    # ------------------------------------------------------------------
    # Default rules
    # ------------------------------------------------------------------

    def _register_defaults(self) -> None:
        """Register built-in safety rules."""

        def _no_secret_leaks(ctx: Dict[str, Any]) -> Tuple[bool, str]:
            """Prevent accidental secret/token leakage in output."""
            output = ctx.get("output")
            if output is None:
                return True, ""
            output_str = str(output)
            secret_patterns = [
                re.compile(r"sk-[A-Za-z0-9]{20,}"),          # API keys
                re.compile(r"password\s*[:=]\s*\S+", re.IGNORECASE),
                re.compile(r"BEGIN\s+(RSA|OPENSSH)\s+PRIVATE\s+KEY"),
            ]
            for pat in secret_patterns:
                if pat.search(output_str):
                    return False, "Potential secret/key detected in output."
            return True, ""

        self.add_rule("no_secret_leaks", _no_secret_leaks, block=False)

    def __repr__(self) -> str:
        return f"SafetyChecker(rules={len(self._rules)}, strict={self.strict})"
