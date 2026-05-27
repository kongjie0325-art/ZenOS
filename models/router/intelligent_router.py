"""ZenOS Model Router - 智能模型路由器

路由策略：
- cost-aware: 根据 token 成本选择
- latency-aware: 根据响应延迟选择
- capability-aware: 根据任务能力选择
- context-window aware: 根据上下文长度选择
- fallback chain: 主→备→兜底
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskType(str, Enum):
    COMPLEX_PLANNING = "complex_planning"
    CODE_FIX = "code_fix"
    LONG_SUMMARY = "long_summary"
    CLASSIFICATION = "classification"
    EMBEDDING = "embedding"
    OCR = "ocr"
    REVIEW = "review"
    CHAT = "chat"
    TOOL_CALL = "tool_call"


# Default routing table
DEFAULT_ROUTE_TABLE: dict[TaskType, list[str]] = {
    TaskType.COMPLEX_PLANNING: ["claude-sonnet-4", "gpt-4o", "gemini-2.0-flash"],
    TaskType.CODE_FIX: ["claude-sonnet-4", "gpt-4o", "deepseek-chat"],
    TaskType.LONG_SUMMARY: ["gemini-2.0-flash", "claude-sonnet-4", "gpt-4o"],
    TaskType.CLASSIFICATION: ["qwen3-8b", "gemini-2.0-flash", "claude-haiku"],
    TaskType.EMBEDDING: ["local-bge-m3", "local-minilm"],
    TaskType.OCR: ["local-got-ocr2", "gpt-4o-vision"],
    TaskType.REVIEW: ["claude-sonnet-4", "gpt-4o"],
    TaskType.CHAT: ["claude-sonnet-4", "gemini-2.0-flash", "deepseek-chat"],
    TaskType.TOOL_CALL: ["claude-sonnet-4", "gpt-4o", "gemini-2.0-flash"],
}


@dataclass
class ModelProfile:
    """模型配置"""
    name: str
    provider: str
    base_url: str
    api_key_env: str
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    context_window: int = 8192
    supports_vision: bool = False
    supports_tools: bool = False
    avg_latency_ms: float = 0.0
    max_retries: int = 3


@dataclass
class RouteDecision:
    """路由决策结果"""
    model: str
    provider: str
    reason: str
    estimated_cost: float = 0.0
    fallback_chain: list[str] = field(default_factory=list)


class IntelligentRouter:
    """智能模型路由器"""

    def __init__(
        self,
        route_table: dict[TaskType, list[str]] | None = None,
        models: dict[str, ModelProfile] | None = None,
    ):
        self.route_table = route_table or DEFAULT_ROUTE_TABLE
        self.models = models or {}
        self._latency_stats: dict[str, list[float]] = {}

    def register_model(self, model_id: str, profile: ModelProfile):
        """注册模型"""
        self.models[model_id] = profile

    def route(
        self,
        task_type: TaskType,
        context_length: int = 0,
        prefer_cost: bool = False,
        prefer_latency: bool = False,
    ) -> RouteDecision:
        """
        智能路由

        Args:
            task_type: 任务类型
            context_length: 上下文长度
            prefer_cost: 优先成本
            prefer_latency: 优先延迟
        """
        candidates = self.route_table.get(task_type, ["claude-sonnet-4"])

        # Filter by context window
        if context_length > 0:
            candidates = [
                m for m in candidates
                if m not in self.models or self.models[m].context_window >= context_length
            ]

        if not candidates:
            return RouteDecision(
                model="claude-sonnet-4",
                provider="anthropic",
                reason="fallback: no suitable model found",
            )

        # Score candidates
        scored: list[tuple[float, str]] = []
        for model_id in candidates:
            score = 0.0
            profile = self.models.get(model_id)

            if prefer_cost and profile:
                score -= (profile.cost_per_1k_input + profile.cost_per_1k_output)
            if prefer_latency and profile:
                score -= profile.avg_latency_ms * 0.1

            # Prefer models with tool support for tool_call tasks
            if task_type == TaskType.TOOL_CALL and profile and profile.supports_tools:
                score += 10

            scored.append((score, model_id))

        scored.sort(key=lambda x: -x[0])
        best = scored[0][1]

        profile = self.models.get(best)
        return RouteDecision(
            model=best,
            provider=profile.provider if profile else "unknown",
            reason=f"task={task_type.value}, cost_priority={prefer_cost}, latency_priority={prefer_latency}",
            fallback_chain=[m for _, m in scored[1:]],
        )

    def record_latency(self, model_id: str, latency_ms: float):
        """记录延迟统计"""
        self._latency_stats.setdefault(model_id, []).append(latency_ms)
        # Keep last 100
        if len(self._latency_stats[model_id]) > 100:
            self._latency_stats[model_id] = self._latency_stats[model_id][-100:]

    def get_avg_latency(self, model_id: str) -> float:
        stats = self._latency_stats.get(model_id, [])
        return sum(stats) / len(stats) if stats else 0.0

    def get_stats(self) -> dict[str, Any]:
        return {
            model_id: {
                "avg_latency_ms": self.get_avg_latency(model_id),
                "calls": len(stats),
            }
            for model_id, stats in self._latency_stats.items()
        }
