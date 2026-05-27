"""ZenOS Working Memory - 短期上下文记忆

基于 Redis，TTL 10min~24h
保存：当前任务、当前 tool 结果、当前状态
"""

from __future__ import annotations

import json
from typing import Any, Optional

try:
    import redis
except ImportError:
    redis = None  # type: ignore


class WorkingMemory:
    """短期工作记忆"""

    def __init__(self, redis_url: str = "redis://localhost:6379/0", default_ttl: int = 3600):
        self._redis_url = redis_url
        self._default_ttl = default_ttl
        self._local: dict[str, Any] = {}
        self._client = None

        if redis:
            try:
                self._client = redis.from_url(redis_url, decode_responses=True)
                self._client.ping()
            except Exception:
                self._client = None

    def _key(self, task_id: str, key: str) -> str:
        return f"zenos:working:{task_id}:{key}"

    def set(self, task_id: str, key: str, value: Any, ttl: int | None = None) -> None:
        serialized = json.dumps(value, default=str)
        if self._client:
            self._client.setex(self._key(task_id, key), ttl or self._default_ttl, serialized)
        else:
            self._local[self._key(task_id, key)] = serialized

    def get(self, task_id: str, key: str) -> Any | None:
        if self._client:
            raw = self._client.get(self._key(task_id, key))
            return json.loads(raw) if raw else None
        raw = self._local.get(self._key(task_id, key))
        return json.loads(raw) if raw else None

    def delete(self, task_id: str, key: str) -> None:
        if self._client:
            self._client.delete(self._key(task_id, key))
        self._local.pop(self._key(task_id, key), None)

    def clear_task(self, task_id: str) -> None:
        """清除任务的所有工作记忆"""
        if self._client:
            keys = self._client.keys(f"zenos:working:{task_id}:*")
            if keys:
                self._client.delete(*keys)
        else:
            prefix = f"zenos:working:{task_id}:"
            for k in list(self._local.keys()):
                if k.startswith(prefix):
                    del self._local[k]

    def set_state(self, task_id: str, state: dict[str, Any], ttl: int | None = None) -> None:
        self.set(task_id, "state", state, ttl)

    def get_state(self, task_id: str) -> dict[str, Any] | None:
        return self.get(task_id, "state")

    def add_tool_result(self, task_id: str, tool_name: str, result: Any) -> None:
        results = self.get(task_id, "tool_results") or {}
        results[tool_name] = result
        self.set(task_id, "tool_results", results)

    def get_tool_results(self, task_id: str) -> dict[str, Any]:
        return self.get(task_id, "tool_results") or {}
