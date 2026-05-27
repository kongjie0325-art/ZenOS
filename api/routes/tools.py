"""Tools API routes — list, execute, and register tool endpoints."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional
from http import HTTPStatus

from zenos.api.routes.agent import Route, HttpMethod


@dataclass
class ToolDefinition:
    """Describes a registered tool."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    returns: str = "Any"
    version: str = "1.0.0"
    enabled: bool = True


@dataclass
class ToolExecuteRequest:
    """Request body for tool execution."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    run_in_sandbox: bool = True


@dataclass
class ToolExecuteResponse:
    """Response from tool execution."""

    tool_name: str
    status: str  # "success", "error", "timeout"
    result: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class ToolRegisterRequest:
    """Request body for registering a new tool."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    returns: str = "Any"
    version: str = "1.0.0"


@dataclass
class ToolRegisterResponse:
    """Response from tool registration."""

    name: str
    status: str = "registered"
    registered_at: float = 0.0


@dataclass
class ToolListResponse:
    """Response listing all registered tools."""

    tools: list[ToolDefinition] = field(default_factory=list)
    total: int = 0


class ToolsRouter:
    """Tools route handler — manages tool discovery and execution.

    Provides endpoints to list available tools, execute a tool
    with arguments, and register new tools at runtime.
    """

    def __init__(self) -> None:
        self._routes = self._build_routes()
        self._tools: dict[str, ToolDefinition] = {}

    @property
    def routes(self) -> list[Route]:
        """Return the list of registered routes."""
        return self._routes

    def _build_routes(self) -> list[Route]:
        """Register all tools routes."""
        return [
            Route(
                path="/api/v1/tools/list",
                method=HttpMethod.GET,
                handler=self.list_tools,
                name="tools_list",
            ),
            Route(
                path="/api/v1/tools/execute",
                method=HttpMethod.POST,
                handler=self.execute,
                name="tools_execute",
            ),
            Route(
                path="/api/v1/tools/register",
                method=HttpMethod.POST,
                handler=self.register,
                name="tools_register",
            ),
        ]

    def list_tools(
        self,
        include_disabled: bool = False,
        **kwargs: Any,
    ) -> ToolListResponse:
        """List all registered tools.

        Args:
            include_disabled: Whether to include disabled tools.

        Returns:
            ToolListResponse with matching tool definitions.
        """
        tools = list(self._tools.values())
        if not include_disabled:
            tools = [t for t in tools if t.enabled]
        return ToolListResponse(tools=tools, total=len(tools))

    def execute(
        self,
        request: ToolExecuteRequest,
        **kwargs: Any,
    ) -> ToolExecuteResponse:
        """Execute a registered tool with the given arguments.

        Args:
            request: Tool execution parameters.

        Returns:
            ToolExecuteResponse with the result or error.
        """
        tool = self._tools.get(request.tool_name)
        if tool is None:
            return ToolExecuteResponse(
                tool_name=request.tool_name,
                status="error",
                error=f"Tool '{request.tool_name}' not found",
            )

        if not tool.enabled:
            return ToolExecuteResponse(
                tool_name=request.tool_name,
                status="error",
                error=f"Tool '{request.tool_name}' is disabled",
            )

        start = time.time()
        # Placeholder: in production this dispatches to the tool executor
        # (optionally within a sandbox).
        elapsed = (time.time() - start) * 1000
        return ToolExecuteResponse(
            tool_name=request.tool_name,
            status="success",
            result={"message": f"Executed {request.tool_name}"},
            duration_ms=round(elapsed, 2),
        )

    def register(
        self,
        request: ToolRegisterRequest,
        **kwargs: Any,
    ) -> ToolRegisterResponse:
        """Register a new tool at runtime.

        Args:
            request: Tool definition to register.

        Returns:
            ToolRegisterResponse confirming registration.
        """
        now = time.time()
        self._tools[request.name] = ToolDefinition(
            name=request.name,
            description=request.description,
            parameters=request.parameters,
            returns=request.returns,
            version=request.version,
            enabled=True,
        )
        return ToolRegisterResponse(
            name=request.name, status="registered", registered_at=now
        )
