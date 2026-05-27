"""Request/response logging middleware for ZenOS API."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from http import HTTPStatus


@dataclass
class LogEntry:
    """A single request/response log entry."""

    request_id: str
    method: str
    path: str
    status_code: int
    duration_ms: float
    client_ip: Optional[str] = None
    user_id: Optional[str] = None
    user_agent: Optional[str] = None
    request_body_size: int = 0
    response_body_size: int = 0
    error: Optional[str] = None
    timestamp: float = 0.0


@dataclass
class LoggingConfig:
    """Configuration for the logging middleware."""

    log_level: int = logging.INFO
    log_request_body: bool = False
    log_response_body: bool = False
    max_body_log_size: int = 1024
    exclude_paths: list[str] = field(
        default_factory=lambda: ["/api/v1/system/health"]
    )
    sensitive_headers: list[str] = field(
        default_factory=lambda: ["authorization", "cookie", "x-api-key"]
    )


class LoggingMiddleware:
    """Request/response logging middleware.

    Assigns a unique request ID, records timing, and emits structured
    log entries for every request passing through the API layer.
    """

    def __init__(
        self,
        config: Optional[LoggingConfig] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """Initialize the logging middleware.

        Args:
            config: Logging configuration. Uses defaults if not provided.
            logger: Logger instance. Creates one if not provided.
        """
        self._config = config or LoggingConfig()
        self._logger = logger or logging.getLogger("zenos.api.access")
        self._logger.setLevel(self._config.log_level)

    def process_request(
        self,
        method: str,
        path: str,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        user_id: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> tuple[str, float]:
        """Record the start of a request.

        Args:
            method: HTTP method.
            path: Request path.
            client_ip: Client IP address.
            user_agent: User-Agent header value.
            user_id: Authenticated user ID, if available.
            headers: Request headers (sensitive values are redacted).

        Returns:
            Tuple of (request_id, start_time).
        """
        request_id = str(uuid.uuid4())
        start_time = time.time()

        if path not in self._config.exclude_paths:
            safe_headers = self._redact_headers(headers or {})
            self._logger.info(
                "request_started",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                    "user_id": user_id,
                    "headers": safe_headers,
                },
            )

        return request_id, start_time

    def process_response(
        self,
        request_id: str,
        method: str,
        path: str,
        status_code: int,
        start_time: float,
        client_ip: Optional[str] = None,
        user_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> LogEntry:
        """Record the completion of a request.

        Args:
            request_id: The unique request ID from process_request.
            method: HTTP method.
            path: Request path.
            status_code: HTTP status code returned.
            start_time: Timestamp when the request started.
            client_ip: Client IP address.
            user_id: Authenticated user ID.
            error: Error message, if any.

        Returns:
            LogEntry with the full request/response details.
        """
        duration_ms = round((time.time() - start_time) * 1000, 2)
        entry = LogEntry(
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            client_ip=client_ip,
            user_id=user_id,
            error=error,
            timestamp=time.time(),
        )

        if path not in self._config.exclude_paths:
            level = logging.ERROR if status_code >= 500 else logging.INFO
            self._logger.log(
                level,
                "request_completed",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": client_ip,
                    "user_id": user_id,
                    "error": error,
                },
            )

        return entry

    def _redact_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Redact sensitive header values.

        Args:
            headers: Original header dictionary.

        Returns:
            Copy with sensitive values replaced by '***'.
        """
        redacted = {}
        for key, value in headers.items():
            if key.lower() in self._config.sensitive_headers:
                redacted[key] = "***"
            else:
                redacted[key] = value
        return redacted
