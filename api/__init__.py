"""ZenOS API module — HTTP routes, middleware, and request/response schemas."""

from zenos.api.routes.agent import AgentRouter
from zenos.api.routes.memory import MemoryRouter
from zenos.api.routes.tools import ToolsRouter
from zenos.api.routes.system import SystemRouter
from zenos.api.middleware.auth import AuthMiddleware
from zenos.api.middleware.rate_limit import RateLimitMiddleware
from zenos.api.middleware.logging import LoggingMiddleware
from zenos.api.schemas.agent import (
    AgentRunRequest,
    AgentRunResponse,
    AgentStatusResponse,
    AgentHistoryResponse,
)
from zenos.api.schemas.memory import (
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryAddRequest,
    MemoryAddResponse,
    MemoryDeleteResponse,
    MemoryCompressRequest,
    MemoryCompressResponse,
)

__all__ = [
    # Routers
    "AgentRouter",
    "MemoryRouter",
    "ToolsRouter",
    "SystemRouter",
    # Middleware
    "AuthMiddleware",
    "RateLimitMiddleware",
    "LoggingMiddleware",
    # Schemas
    "AgentRunRequest",
    "AgentRunResponse",
    "AgentStatusResponse",
    "AgentHistoryResponse",
    "MemorySearchRequest",
    "MemorySearchResponse",
    "MemoryAddRequest",
    "MemoryAddResponse",
    "MemoryDeleteResponse",
    "MemoryCompressRequest",
    "MemoryCompressResponse",
]
