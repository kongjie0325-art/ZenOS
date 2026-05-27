"""Models data layer - Pydantic-style dataclasses for API I/O."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime


@dataclass
class AgentModel:
    id: str
    name: str
    status: str = "idle"
    model: str = "gpt-4o"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRunRequest:
    agent_id: str
    message: str
    context_id: Optional[str] = None
    stream: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRunResponse:
    agent_id: str
    context_id: str
    message: str
    status: str = "completed"
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tokens_used: int = 0
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentStatusResponse:
    agent_id: str
    status: str
    current_task: Optional[str] = None
    uptime_seconds: float = 0.0
    total_runs: int = 0
    total_tokens: int = 0
    last_error: Optional[str] = None
