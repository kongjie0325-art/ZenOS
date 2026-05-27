"""Sandbox - Secure tool execution environment."""

from __future__ import annotations

import os
import resource
import signal
import subprocess
import tempfile
import time
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SandboxConfig:
    max_memory_mb: int = 256
    max_cpu_seconds: float = 30.0
    max_output_size: int = 1048576  # 1MB
    allowed_commands: List[str] = field(default_factory=lambda: [
        'ls', 'cat', 'echo', 'grep', 'find', 'head', 'tail', 'wc', 'sort', 'uniq',
        'python3', 'pip', 'git', 'curl', 'wget',
    ])
    blocked_commands: List[str] = field(default_factory=lambda: [
        'rm -rf /', 'mkfs', 'dd if=', ':(){:|:&};:', '> /dev/sda',
    ])
    network_access: bool = False
    file_system_read_only: bool = True
    working_directory: str = "/tmp"


@dataclass
class SandboxResult:
    success: bool
    output: str = ""
    error: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0
    memory_used_mb: float = 0.0
    timed_out: bool = False


class Sandbox:
    """Secure execution sandbox for tool calls."""

    def __init__(self, config: Optional[SandboxConfig] = None):
        self._config = config or SandboxConfig()

    def execute(self, command: str, timeout: Optional[float] = None,
                env: Optional[Dict[str, str]] = None,
                working_dir: Optional[str] = None) -> SandboxResult:
        """Execute a command in the sandbox."""
        # Safety check
        if not self._is_safe(command):
            return SandboxResult(
                success=False,
                error=f"Command blocked by sandbox: {command}",
            )

        timeout = timeout or self._config.max_cpu_seconds
        start = time.time()
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, **(env or {})},
                cwd=working_dir or self._config.working_directory,
                preexec_fn=self._set_limits if os.name != 'nt' else None,
            )
            duration = (time.time() - start) * 1000
            output = result.stdout[:self._config.max_output_size]
            error = result.stderr[:self._config.max_output_size]
            return SandboxResult(
                success=result.returncode == 0,
                output=output,
                error=error,
                exit_code=result.returncode,
                duration_ms=duration,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False,
                error=f"Command timed out after {timeout}s",
                timed_out=True,
                duration_ms=timeout * 1000,
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                error=str(e),
                duration_ms=(time.time() - start) * 1000,
            )

    def execute_python(self, code: str, timeout: float = 30.0) -> SandboxResult:
        """Execute Python code in a subprocess."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            tmp_path = f.name
        try:
            return self.execute(f"python3 {tmp_path}", timeout=timeout)
        finally:
            os.unlink(tmp_path)

    def _is_safe(self, command: str) -> bool:
        cmd_lower = command.lower().strip()
        for blocked in self._config.blocked_commands:
            if blocked.lower() in cmd_lower:
                logger.warning(f"Sandbox blocked dangerous command: {command}")
                return False
        return True

    def _set_limits(self):
        """Set resource limits (called in child process)."""
        try:
            mem_bytes = self._config.max_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            resource.setrlimit(resource.RLIMIT_CPU, (int(self._config.max_cpu_seconds), int(self._config.max_cpu_seconds)))
        except Exception:
            pass
