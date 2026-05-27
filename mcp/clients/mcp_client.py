"""ZenOS MCP Tool Bus - 工具注册中心 + MCP 客户端"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    server: str = ""
    category: str = "general"


class ToolRegistry:
    """MCP 工具注册中心"""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._servers: dict[str, Any] = {}
        self._categories: dict[str, list[str]] = {}

    def register(self, tool: ToolDefinition):
        """注册工具"""
        self._tools[tool.name] = tool
        self._categories.setdefault(tool.category, []).append(tool.name)

    def unregister(self, name: str):
        """注销工具"""
        if name in self._tools:
            cat = self._tools[name].category
            if cat in self._categories:
                self._categories[cat] = [t for t in self._categories[cat] if t != name]
            del self._tools[name]

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self, category: str | None = None) -> list[ToolDefinition]:
        if category:
            names = self._categories.get(category, [])
            return [self._tools[n] for n in names if n in self._tools]
        return list(self._tools.values())

    def get_schema(self, name: str) -> dict[str, Any] | None:
        tool = self._tools.get(name)
        if not tool:
            return None
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }


class MCPClient:
    """MCP 客户端 - stdio 传输"""

    def __init__(self, command: str, args: list[str] | None = None, env: dict[str, str] | None = None):
        self._command = command
        self._args = args or []
        self._env = env or {}
        self._process: Any = None
        self._tools: list[ToolDefinition] = []

    async def connect(self):
        """连接到 MCP server"""
        import asyncio.subprocess

        cmd = [self._command] + self._args
        env = {**self._env}

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    async def list_tools(self) -> list[ToolDefinition]:
        """列出工具"""
        if not self._process:
            return []

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }
        await self._send(request)
        response = await self._receive()

        tools = []
        for tool in response.get("result", {}).get("tools", []):
            tools.append(ToolDefinition(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=tool.get("inputSchema", {}),
            ))
        self._tools = tools
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """调用工具"""
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        await self._send(request)
        response = await self._receive()
        return response.get("result", {})

    async def _send(self, data: dict[str, Any]):
        if self._process and self._process.stdin:
            line = json.dumps(data) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()

    async def _receive(self) -> dict[str, Any]:
        if self._process and self._process.stdout:
            line = await self._process.stdout.readline()
            return json.loads(line.decode())
        return {}

    async def disconnect(self):
        if self._process:
            self._process.terminate()
            await self._process.wait()
