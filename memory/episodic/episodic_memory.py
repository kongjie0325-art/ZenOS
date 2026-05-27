"""ZenOS Episodic Memory - 事件记忆

基于 PostgreSQL，记录：做了什么、为什么、是否成功、花费 token、调用了什么工具
类似 Agent Journal
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class EpisodicEntry:
    """事件记忆条目"""
    task_id: str
    task_summary: str
    action: str
    result: str
    success: bool
    tokens_used: int = 0
    tools_called: list[str] = None  # type: ignore
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if self.tools_called is None:
            self.tools_called = []
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_summary": self.task_summary,
            "action": self.action,
            "result": self.result,
            "success": self.success,
            "tokens_used": self.tokens_used,
            "tools_called": self.tools_called,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
        }


from dataclasses import dataclass


class EpisodicMemory:
    """事件记忆（Agent Journal）"""

    def __init__(self, db_url: str | None = None):
        self._db_url = db_url
        self._entries: list[EpisodicEntry] = []
        self._pg = None

        if db_url:
            try:
                import asyncpg  # noqa: F401
                # TODO: async connection pool
            except ImportError:
                pass

    def record(
        self,
        task_id: str,
        task_summary: str,
        action: str,
        result: str,
        success: bool,
        tokens_used: int = 0,
        tools_called: list[str] | None = None,
        error: str | None = None,
        duration_ms: float = 0.0,
    ) -> EpisodicEntry:
        """记录事件"""
        entry = EpisodicEntry(
            task_id=task_id,
            task_summary=task_summary,
            action=action,
            result=result,
            success=success,
            tokens_used=tokens_used,
            tools_called=tools_called or [],
            error=error,
            duration_ms=duration_ms,
        )
        self._entries.append(entry)
        return entry

    def get_history(
        self,
        task_id: str | None = None,
        limit: int = 50,
        successful_only: bool = False,
    ) -> list[EpisodicEntry]:
        """获取历史"""
        entries = self._entries
        if task_id:
            entries = [e for e in entries if e.task_id == task_id]
        if successful_only:
            entries = [e for e in entries if e.success]
        return entries[-limit:]

    def get_failure_patterns(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取失败模式"""
        failures = [e for e in self._entries if not e.success]
        patterns: dict[str, int] = {}
        for f in failures:
            key = f.error or "unknown"
            patterns[key] = patterns.get(key, 0) + 1
        return [
            {"pattern": k, "count": v}
            for k, v in sorted(patterns.items(), key=lambda x: -x[1])[:limit]
        ]

    def get_token_stats(self) -> dict[str, Any]:
        """获取 token 统计"""
        if not self._entries:
            return {"total": 0, "avg": 0, "max": 0}
        tokens = [e.tokens_used for e in self._entries]
        return {
            "total": sum(tokens),
            "avg": sum(tokens) / len(tokens),
            "max": max(tokens),
            "count": len(tokens),
        }
