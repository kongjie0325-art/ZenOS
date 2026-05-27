"""Agent API routes — run, stop, status, and history endpoints."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from enum import Enum
from http import HTTPStatus


class HttpMethod(Enum):
    """Supported HTTP methods."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


@dataclass
class Route:
    """Represents an API route binding."""

    path: str
    method: HttpMethod
    handler: Callable[..., dict[str, Any]]
    name: str
    require_auth: bool = True


@dataclass
class AgentRunRequest:
    """Request body for running an agent."""

    prompt: str
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    tools: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class AgentRunResponse:
    """Response from an agent run request."""

    run_id: str
    status: str
    output: Optional[str] = None
    tokens_used: int = 0
    duration_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class AgentStatusResponse:
    """Response for agent status query."""

    run_id: str
    status: str  # "pending", "running", "completed", "failed", "cancelled"
    progress: float = 0.0
    started_at: Optional[float] = None
    updated_at: Optional[float] = None
    current_step: Optional[str] = None


@dataclass
class HistoryEntry:
    """A single entry in the agent history."""

    run_id: str
    prompt: str
    status: str
    created_at: float
    duration_ms: float = 0.0
    tokens_used: int = 0


@dataclass
class AgentHistoryResponse:
    """Response containing agent run history."""

    entries: list[HistoryEntry] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class AgentRouter:
    """Agent route handler — manages agent lifecycle endpoints.

    Provides endpoints to run, stop, query status, and fetch history
    for agent executions.
    """

    def __init__(self) -> None:
        self._routes = self._build_routes()
        # In-memory stores (replace with persistent storage in production)
        self._active_runs: dict[str, AgentStatusResponse] = {}
        self._history: list[HistoryEntry] = []

    @property
    def routes(self) -> list[Route]:
        """Return the list of registered routes."""
        return self._routes

    def _build_routes(self) -> list[Route]:
        """Register all agent routes."""
        return [
            Route(
                path="/api/v1/agent/run",
                method=HttpMethod.POST,
                handler=self.run,
                name="agent_run",
            ),
            Route(
                path="/api/v1/agent/stop",
                method=HttpMethod.POST,
                handler=self.stop,
                name="agent_stop",
            ),
            Route(
                path="/api/v1/agent/status/{run_id}",
                method=HttpMethod.GET,
                handler=self.status,
                name="agent_status",
            ),
            Route(
                path="/api/v1/agent/history",
                method=HttpMethod.GET,
                handler=self.history,
                name="agent_history",
            ),
        ]

    def run(self, request: AgentRunRequest, **kwargs: Any) -> AgentRunResponse:
        """Start a new agent run.

        Args:
            request: The agent run parameters.

        Returns:
            AgentRunResponse with the run ID and initial status.
        """
        import uuid

        run_id = str(uuid.uuid4())
        now = time.time()

        status_entry = AgentStatusResponse(
            run_id=run_id,
            status="pending",
            progress=0.0,
            started_at=now,
            updated_at=now,
        )
        self._active_runs[run_id] = status_entry

        # In production this would dispatch to the agent executor.
        return AgentRunResponse(
            run_id=run_id,
            status="pending",
            output=None,
            tokens_used=0,
            duration_ms=0.0,
        )

    def stop(self, run_id: str, **kwargs: Any) -> dict[str, Any]:
        """Cancel a running agent.

        Args:
            run_id: The unique run identifier to cancel.

        Returns:
            Dict with cancellation result.
        """
        entry = self._active_runs.get(run_id)
        if entry is None:
            return {
                "error": "Run not found",
                "status_code": HTTPStatus.NOT_FOUND,
            }

        if entry.status in ("completed", "failed", "cancelled"):
            return {
                "error": f"Run already in terminal state: {entry.status}",
                "status_code": HTTPStatus.CONFLICT,
            }

        entry.status = "cancelled"
        entry.updated_at = time.time()
        return {"run_id": run_id, "status": "cancelled"}

    def status(self, run_id: str, **kwargs: Any) -> Optional[AgentStatusResponse]:
        """Get the current status of an agent run.

        Args:
            run_id: The unique run identifier.

        Returns:
            AgentStatusResponse or None if not found.
        """
        return self._active_runs.get(run_id)

    def history(
        self,
        page: int = 1,
        page_size: int = 50,
        **kwargs: Any,
    ) -> AgentHistoryResponse:
        """Retrieve paginated agent run history.

        Args:
            page: Page number (1-indexed).
            page_size: Number of entries per page.

        Returns:
            AgentHistoryResponse with matching entries.
        """
        start = (page - 1) * page_size
        end = start + page_size
        entries = self._history[start:end]
        return AgentHistoryResponse(
            entries=entries,
            total=len(self._history),
            page=page,
            page_size=page_size,
        )
