"""ZenOS Memory Router - 记忆路由器

根据任务类型自动选择记忆层
"""

from __future__ import annotations

from typing import Any, Optional

from memory.working.working_memory import WorkingMemory
from memory.episodic.episodic_memory import EpisodicMemory
from memory.semantic.semantic_memory import SemanticMemory


class MemoryRouter:
    """
    记忆路由器
    - 当前任务上下文 → Working Memory (Redis)
    - 历史事件/经验 → Episodic Memory (Postgres)
    - 知识/文档 → Semantic Memory (Qdrant)
    """

    def __init__(
        self,
        working: WorkingMemory | None = None,
        episodic: EpisodicMemory | None = None,
        semantic: SemanticMemory | None = None,
    ):
        self.working = working or WorkingMemory()
        self.episodic = episodic or EpisodicMemory()
        self.semantic = semantic or SemanticMemory()

    def get_context(self, task_id: str, query: str = "") -> dict[str, Any]:
        """获取完整的任务上下文"""
        context: dict[str, Any] = {}

        # 1. Working memory: current state
        state = self.working.get_state(task_id)
        if state:
            context["current_state"] = state

        # 2. Working memory: tool results
        tool_results = self.working.get_tool_results(task_id)
        if tool_results:
            context["tool_results"] = tool_results

        # 3. Episodic: recent history
        history = self.episodic.get_history(limit=10)
        if history:
            context["recent_history"] = [e.to_dict() for e in history]

        # 4. Semantic: relevant knowledge
        if query:
            knowledge = self.semantic.search(query, limit=5)
            if knowledge:
                context["relevant_knowledge"] = [k.to_dict() for k in knowledge]

        return context

    def summarize_and_distill(self, task_id: str) -> str:
        """总结并蒸馏记忆"""
        # Get working memory
        state = self.working.get_state(task_id) or {}
        tool_results = self.working.get_tool_results(task_id) or {}

        # Create summary
        summary = f"Task: {state.get('task', 'unknown')}\n"
        summary += f"State: {state.get('state', 'unknown')}\n"
        summary += f"Steps completed: {state.get('current_step', 0)}\n"
        if state.get('errors'):
            summary += f"Errors: {', '.join(state['errors'])}\n"

        # Store in episodic
        self.episodic.record(
            task_id=task_id,
            task_summary=summary,
            action="task_completion",
            result="distilled",
            success=not state.get('errors'),
        )

        # Store in semantic
        self.semantic.store(
            content=summary,
            category="task_summary",
            metadata={"task_id": task_id, "state": state.get("state", "unknown")},
        )

        # Clear working memory
        self.working.clear_task(task_id)

        return summary

    def inject_relevant_memory(self, task: str, task_id: str) -> dict[str, Any]:
        """注入相关记忆到上下文"""
        return self.get_context(task_id, query=task)
