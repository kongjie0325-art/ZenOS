"""Agent request and response schemas for the ZenOS API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AgentRunRequest:
    """Request to start a new agent run.

    Attributes:
        prompt: The user prompt or task description.
        model: Optional model override (e.g. "claude-sonnet-4-20250514").
        temperature: Sampling temperature (0.0 – 2.0).
        max_tokens: Maximum tokens in the response.
        tools: List of tool names available to the agent.
        metadata: Arbitrary metadata attached to the run.
    """

    prompt: str
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    tools: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class AgentRunResponse:
    """Response from initiating an agent run.

    Attributes:
        run_id: Unique identifier for this run.
        status: Current run status.
        output: Agent output (populated when completed).
        tokens_used: Total tokens consumed.
        duration_ms: Wall-clock duration in milliseconds.
        error: Error message if the run failed.
    """

    run_id: str
    status: str
    output: Optional[str] = None
    tokens_used: int = 0
    duration_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class AgentStatusResponse:
    """Current status of an agent run.

    Attributes:
        run_id: Unique identifier for the run.
        status: One of "pending", "running", "completed", "failed", "cancelled".
        progress: Completion progress from 0.0 to 1.0.
        started_at: Unix timestamp when the run started.
        updated_at: Unix timestamp of the last status update.
        current_step: Human-readable description of the current step.
    """

    run_id: str
    status: str
    progress: float = 0.0
    started_at: Optional[float] = None
    updated_at: Optional[float] = None
    current_step: Optional[str] = None


@dataclass
class AgentHistoryEntry:
    """A single entry in the agent run history.

    Attributes:
        run_id: Unique identifier for the run.
        prompt: The original prompt.
        status: Final run status.
        created_at: Unix timestamp when the run was created.
        duration_ms: Total wall-clock duration.
        tokens_used: Total tokens consumed.
    """

    run_id: str
    prompt: str
    status: str
    created_at: float
    duration_ms: float = 0.0
    tokens_used: int = 0


@dataclass
class AgentHistoryResponse:
    """Paginated agent run history.

    Attributes:
        entries: List of history entries for the current page.
        total: Total number of history entries.
        page: Current page number (1-indexed).
        page_size: Number of entries per page.
    """

    entries: list[AgentHistoryEntry] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
