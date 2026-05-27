"""Built-in tool: ShellTool.

Executes shell commands with configurable safety checks:

* Optional allow-list / deny-list of commands.
* Timeout enforcement.
* Working directory and environment variable control.
* Captured stdout / stderr.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from typing import Any, Dict, List, Optional, Sequence

from zenos.tools.base import BaseTool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Commands that are always denied unless explicitly overridden.
_DEFAULT_DENY_LIST: List[str] = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs.",
    "dd if=",
    ":(){:|:&};:",
    "> /dev/sda",
    "mv / /dev/null",
]


def _is_dangerous(command: str, deny_list: Sequence[str]) -> Optional[str]:
    """Return an error string if *command* matches a deny-list entry."""
    normalized = command.strip().lower()
    for denied in deny_list:
        if denied.strip().lower() in normalized:
            return f"Command matches denied pattern: '{denied}'"
    return None


class ShellTool(BaseTool):
    """Execute a shell command and return its output.

    Parameters:
        command: The shell command to run.
        cwd: Working directory for the command.
        env: Extra environment variables (dict).
        timeout: Maximum execution time in seconds.
        shell: If ``True``, run via ``/bin/sh -c``.
    """

    name = "shell"
    description = (
        "Execute a shell command and return stdout, stderr, and exit code. "
        "Use with caution -- dangerous commands are blocked."
    )
    parameters = [
        ToolParameter(
            name="command",
            type="string",
            description="Shell command to execute.",
        ),
        ToolParameter(
            name="cwd",
            type="string",
            description="Working directory.",
            required=False,
            default=".",
        ),
        ToolParameter(
            name="env",
            type="object",
            description="Extra environment variables as key-value pairs.",
            required=False,
            default=None,
        ),
        ToolParameter(
            name="timeout",
            type="integer",
            description="Timeout in seconds.",
            required=False,
            default=30,
        ),
        ToolParameter(
            name="shell",
            type="boolean",
            description="Run command through the shell.",
            required=False,
            default=True,
        ),
    ]

    def __init__(
        self,
        allow_list: Optional[Sequence[str]] = None,
        deny_list: Optional[Sequence[str]] = None,
        default_timeout: int = 30,
        max_timeout: int = 300,
    ):
        """Create the tool.

        Args:
            allow_list: If set, only commands matching one of these
                patterns are allowed.
            deny_list: Additional command patterns to deny.
            default_timeout: Default timeout in seconds.
            max_timeout: Maximum allowed timeout.
        """
        self._allow_list = allow_list
        self._deny_list = list(_DEFAULT_DENY_LIST) + list(deny_list or [])
        self._default_timeout = default_timeout
        self._max_timeout = max_timeout

    # ------------------------------------------------------------------
    # Safety helpers
    # ------------------------------------------------------------------

    def _check_safety(self, command: str) -> Optional[str]:
        """Return an error string if *command* is not allowed."""
        # Check deny list first.
        reason = _is_dangerous(command, self._deny_list)
        if reason:
            return reason

        # Check allow list (if configured).
        if self._allow_list is not None:
            normalized = command.strip().lower()
            for allowed in self._allow_list:
                if allowed.strip().lower() in normalized:
                    return None
            return "Command is not in the allow list."

        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, **kwargs: Any) -> ToolResult:
        command: str = kwargs["command"]
        cwd: str = kwargs.get("cwd", ".")
        env: Optional[Dict[str, str]] = kwargs.get("env")
        timeout: int = kwargs.get("timeout", self._default_timeout)
        shell: bool = kwargs.get("shell", True)

        # Safety check.
        safety_error = self._check_safety(command)
        if safety_error:
            logger.warning("Blocked dangerous command: %s -- %s", command, safety_error)
            return ToolResult.fail(error=safety_error)

        # Clamp timeout.
        timeout = min(max(1, timeout), self._max_timeout)

        # Build environment.
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        try:
            proc = subprocess.run(
                command if shell else shlex.split(command),
                capture_output=True,
                text=True,
                cwd=cwd,
                env=run_env,
                timeout=timeout,
                shell=shell,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.fail(
                error=f"Command timed out after {timeout}s.",
                command=command,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            return ToolResult.fail(error=f"Command not found: {exc}")
        except OSError as exc:
            logger.exception("Shell execution failed")
            return ToolResult.fail(error=f"Execution error: {exc}")

        success = proc.returncode == 0
        content: Dict[str, Any] = {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode,
        }

        if success:
            return ToolResult.ok(content=content, command=command)
        return ToolResult.fail(
            error=f"Command exited with code {proc.returncode}.",
            **content,
        )
