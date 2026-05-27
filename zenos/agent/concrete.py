"""ConcreteAgent - Full implementation of BaseAgent with event-driven integration.

Wires together: EventBus → Memory → Planning → Reasoning → Execution → Safety → Reflection
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from zenos.agent.base import BaseAgent, AgentContext, ToolDefinition
from zenos.agent.planning.planner import TaskPlanner
from zenos.agent.planning.task import TaskStatus
from zenos.agent.reasoning.chain import ChainOfThought
from zenos.agent.reasoning.reflection import Reflection
from zenos.agent.execution.executor import Executor, ExecutionResult
from zenos.agent.execution.safety import SafetyChecker

logger = logging.getLogger(__name__)


class ConcreteAgent(BaseAgent):
    """A concrete agent that connects all subsystems into a working loop.

    Features:
    - Event-driven: publishes AGENT_* events on EventBus
    - Memory-aware: reads/writes EpisodicMemory each iteration
    - Self-healing: retries with backoff, falls back to alternative tools
    - Adaptive: adjusts strategy based on reflection feedback
    - Observable: records metrics and traces for every action
    """

    def __init__(
        self,
        event_bus: Any = None,
        episodic_memory: Any = None,
        semantic_memory: Any = None,
        metrics: Any = None,
        tracer: Any = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._event_bus = event_bus
        self._episodic_memory = episodic_memory
        self._semantic_memory = semantic_memory
        self._metrics = metrics
        self._tracer = tracer
        self._span_ctx: Optional[Any] = None

    # ── Event helpers ──────────────────────────────────────────────

    async def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        if self._event_bus is None:
            return
        try:
            from zenos.core.events import Event, EventType
            try:
                et = EventType(event_type)
            except ValueError:
                et = EventType.AGENT_THINK  # fallback
            await self._event_bus.publish(Event(type=et, data=data, source="agent"))
        except Exception as e:
            logger.debug("Event emit failed: %s", e)

    def _record_metric(self, name: str, value: float = 1, labels: Optional[Dict] = None) -> None:
        if self._metrics is None:
            return
        try:
            if "error" in name:
                self._metrics.counter(name, value, labels)
            elif "duration" in name:
                self._metrics.histogram(name, value, labels)
            else:
                self._metrics.counter(name, value, labels)
        except Exception:
            pass

    def _start_span(self, name: str, **attrs) -> None:
        if self._tracer is None:
            return
        try:
            self._span_ctx = self._tracer.start_span(name, **attrs)
        except Exception:
            pass

    def _end_span(self, status: str = "ok") -> None:
        if self._tracer is None or self._span_ctx is None:
            return
        try:
            from zenos.observability.tracing.tracer import SpanStatus
            s = SpanStatus.OK if status == "ok" else SpanStatus.ERROR
            self._tracer.end_span(self._span_ctx, s)
        except Exception:
            pass

    # ── Core loop ─────────────────────────────────────────────────

    def think(self) -> str:
        """Produce next reasoning step using ChainOfThought + memory context."""
        self._start_span("agent.think")

        # Gather context from memory
        memory_context = ""
        if self._episodic_memory is not None:
            try:
                recent = self._episodic_memory.get_episodes(limit=5)
                memory_context = "\n".join(
                    f"[{e.timestamp}] {e.content}" for e in recent
                )
            except Exception:
                pass

        # Search semantic memory for relevant knowledge
        semantic_context = ""
        if self._semantic_memory is not None and self._context:
            try:
                results = self._semantic_memory.search(
                    query_text=self._context.goal, top_k=3
                )
                semantic_context = "\n".join(k.content for k in results)
            except Exception:
                pass

        # Build thought using ChainOfThought
        thought_input = {
            "goal": self._context.goal if self._context else "",
            "iteration": self._context.iteration if self._context else 0,
            "memory": memory_context,
            "knowledge": semantic_context,
        }

        try:
            thought = self.reasoning.step(
                f"Iteration {thought_input['iteration']}: Given goal '{thought_input['goal']}' "
                f"and recent memory:\n{memory_context}\n\n"
                f"Relevant knowledge:\n{semantic_context}\n\n"
                f"What should I do next?"
            )
        except Exception:
            thought = f"Continue working on: {thought_input['goal']}"

        self._record_metric("agent.thoughts_total")
        self._end_span()
        return thought

    def act(self, thought: str) -> ExecutionResult:
        """Execute action based on thought. Tries tools in priority order with self-healing."""
        self._start_span("agent.act")

        if self._context is None:
            return ExecutionResult(tool_name="none", success=False, error="No context")

        # Convert thought to string if needed
        thought_str = str(thought) if not isinstance(thought, str) else thought

        # Sync tools to executor
        for name, td in self._tools.items():
            if td.enabled:
                self.executor.register_tool(name, td.func)

        # Determine which tool to call based on thought content
        tool_name = self._select_tool(thought_str)
        if tool_name is None:
            self._end_span("error")
            return ExecutionResult(
                tool_name="none",
                success=False,
                error=f"No suitable tool found for thought: {thought[:100]}",
            )

        # Get tool definition
        tool_def = self._tools.get(tool_name)
        if tool_def is None or not tool_def.enabled:
            self._end_span("error")
            return ExecutionResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool '{tool_name}' not registered or disabled",
            )

        # Execute with retry and backoff
        start = time.monotonic()
        try:
            result = self.executor.retry_with_backoff(
                tool_name=tool_name,
                tool_input={"text": thought_str, "goal": self._context.goal},
                max_retries=2,
                base_delay=0.5,
            )
        except Exception as e:
            result = ExecutionResult(
                tool_name=tool_name,
                success=False,
                error=str(e),
                duration_seconds=time.monotonic() - start,
            )

        duration = time.monotonic() - start
        self._record_metric("agent.actions_total", labels={"tool": tool_name})
        self._record_metric("agent.action_duration", duration, labels={"tool": tool_name})

        if not result.success:
            self._record_metric("agent.errors_total", labels={"tool": tool_name})
            logger.warning("Tool '%s' failed: %s", tool_name, result.error)
            # Self-healing: try fallback tool
            result = self._try_fallback(thought_str, tool_name, result)

        self._end_span("ok" if result.success else "error")
        return result

    def observe(self, action_result: ExecutionResult) -> str:
        """Process action result into observation, update memory."""
        self._start_span("agent.observe")

        if action_result.success:
            observation = f"Action '{action_result.tool_name}' succeeded: {action_result.result}"
        else:
            observation = f"Action '{action_result.tool_name}' failed: {action_result.error}"

        # Write to episodic memory
        if self._episodic_memory is not None:
            try:
                from zenos.memory.episodic import Episode
                self._episodic_memory.add_episode(
                    Episode(
                        content=f"[{action_result.tool_name}] {observation}",
                        importance=0.7 if action_result.success else 0.9,
                    )
                )
            except Exception as e:
                logger.debug("Failed to write episodic memory: %s", e)

        self._record_metric("agent.observations_total")
        self._end_span()
        return observation

    # ── Tool selection & self-healing ──────────────────────────────

    def _select_tool(self, thought: str) -> Optional[str]:
        """Select the best tool based on thought content."""
        thought_lower = thought.lower()

        # Keyword-based routing
        tool_keywords = {
            "web_search": ["search", "find", "look up", "query", "web", "internet"],
            "file_read": ["read", "open", "load", "file", "content"],
            "file_write": ["write", "save", "create", "file", "output"],
            "shell": ["run", "execute", "command", "shell", "terminal", "bash"],
            "http": ["api", "request", "http", "fetch", "post", "get"],
        }

        for tool_name, keywords in tool_keywords.items():
            if any(kw in thought_lower for kw in keywords):
                if tool_name in self._tools and self._tools[tool_name].enabled:
                    return tool_name

        # Fallback: use first enabled tool
        for name, td in self._tools.items():
            if td.enabled:
                return name
        return None

    def _try_fallback(self, thought: str, failed_tool: str, original_result: ExecutionResult) -> ExecutionResult:
        """Try alternative tools when the primary tool fails."""
        for name, td in self._tools.items():
            if name == failed_tool or not td.enabled:
                continue
            logger.info("Self-healing: trying fallback tool '%s' after '%s' failed",
                        name, failed_tool)
            try:
                result = self.executor.execute_tool(
                    name, {"text": thought, "goal": self._context.goal if self._context else ""},
                )
                if result.success:
                    self._record_metric("agent.self_heals_total")
                    return result
            except Exception:
                continue
        return original_result

    # ── Async run wrapper ──────────────────────────────────────────

    async def run_async(self, goal: str, **kwargs) -> AgentContext:
        """Async version that emits events."""
        await self._emit("agent.start", {"goal": goal})
        self._start_span("agent.run", goal=goal)

        ctx = self.run(goal, **kwargs)

        await self._emit("agent.complete", {
            "goal": goal,
            "iterations": ctx.iteration if ctx else 0,
            "memory_size": len(ctx.memory) if ctx else 0,
        })
        self._end_span()
        return ctx
