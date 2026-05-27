"""ZenOS Orchestrator - Agent Operating System Core

基于 LangGraph 的状态机编排器，实现：
- 状态机 (IDLE → PLANNING → EXECUTING → REVIEWING → DONE/FAILED)
- 工作流图管理
- 工具分发 (重试/超时/回滚)
- 检查点管理 (保存/恢复)
- 事件溯源
"""

from __future__ import annotations

import enum
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

try:
    from langgraph.graph import StateGraph, END
except ImportError:
    StateGraph = None  # type: ignore
    END = "__end__"  # type: ignore


# ─── State Machine ───────────────────────────────────────────

class AgentState(enum.Enum):
    """Agent 状态机状态"""
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    DONE = "done"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"
    ROLLING_BACK = "rolling_back"


# Valid state transitions
TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.IDLE: {AgentState.PLANNING},
    AgentState.PLANNING: {AgentState.EXECUTING, AgentState.FAILED},
    AgentState.EXECUTING: {AgentState.REVIEWING, AgentState.FAILED, AgentState.WAITING_APPROVAL},
    AgentState.REVIEWING: {AgentState.DONE, AgentState.EXECUTING, AgentState.FAILED},
    AgentState.WAITING_APPROVAL: {AgentState.EXECUTING, AgentState.FAILED},
    AgentState.ROLLING_BACK: {AgentState.FAILED, AgentState.IDLE},
    AgentState.DONE: {AgentState.IDLE},
    AgentState.FAILED: {AgentState.IDLE, AgentState.ROLLING_BACK},
}


@dataclass
class StateContext:
    """状态上下文，在状态机中传递"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task: str = ""
    state: AgentState = AgentState.IDLE
    plan: list[str] = field(default_factory=list)
    current_step: int = 0
    results: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    retries: dict[str, int] = field(default_factory=dict)
    max_retries: int = 3
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def transition_to(self, new_state: AgentState) -> None:
        """状态转换，带校验"""
        if new_state not in TRANSITIONS.get(self.state, set()):
            raise ValueError(
                f"Invalid transition: {self.state.value} → {new_state.value}"
            )
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task": self.task,
            "state": self.state.value,
            "plan": self.plan,
            "current_step": self.current_step,
            "results": self.results,
            "errors": self.errors,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateContext:
        ctx = cls()
        ctx.task_id = data.get("task_id", ctx.task_id)
        ctx.task = data.get("task", "")
        ctx.state = AgentState(data.get("state", "idle"))
        ctx.plan = data.get("plan", [])
        ctx.current_step = data.get("current_step", 0)
        ctx.results = data.get("results", {})
        ctx.errors = data.get("errors", [])
        ctx.retries = data.get("retries", {})
        ctx.max_retries = data.get("max_retries", 3)
        ctx.metadata = data.get("metadata", {})
        ctx.created_at = data.get("created_at", ctx.created_at)
        ctx.updated_at = data.get("updated_at", ctx.updated_at)
        return ctx


# ─── Event Store (Event Sourcing) ────────────────────────────

@dataclass
class Event:
    """事件"""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    event_type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


class EventStore:
    """事件溯源存储 (append-only)"""

    def __init__(self, db_url: str | None = None):
        self._events: list[Event] = []
        self._db_url = db_url

    def append(self, task_id: str, event_type: str, payload: dict[str, Any]) -> Event:
        """追加事件"""
        event = Event(task_id=task_id, event_type=event_type, payload=payload)
        self._events.append(event)
        return event

    def get_events(self, task_id: str | None = None) -> list[Event]:
        """获取事件，可过滤 task_id"""
        if task_id:
            return [e for e in self._events if e.task_id == task_id]
        return list(self._events)

    def get_state_at(self, task_id: str, timestamp: str) -> dict[str, Any]:
        """回放事件，重建某时刻的状态"""
        events = [e for e in self._events if e.task_id == task_id and e.timestamp <= timestamp]
        state: dict[str, Any] = {}
        for event in events:
            if event.event_type == "state_change":
                state.update(event.payload)
            elif event.event_type == "tool_result":
                state.setdefault("results", []).append(event.payload)
            elif event.event_type == "error":
                state.setdefault("errors", []).append(event.payload)
        return state


# ─── Checkpoint Manager ──────────────────────────────────────

@dataclass
class Checkpoint:
    """检查点"""
    checkpoint_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    step_index: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CheckpointManager:
    """检查点管理：保存/恢复执行状态"""

    def __init__(self, redis_url: str | None = None):
        self._checkpoints: dict[str, list[Checkpoint]] = {}
        self._redis_url = redis_url

    def save(self, ctx: StateContext) -> Checkpoint:
        """保存检查点"""
        cp = Checkpoint(
            task_id=ctx.task_id,
            context=ctx.to_dict(),
            step_index=ctx.current_step,
        )
        self._checkpoints.setdefault(ctx.task_id, []).append(cp)
        return cp

    def restore(self, task_id: str, step_index: int | None = None) -> StateContext | None:
        """恢复检查点"""
        cps = self._checkpoints.get(task_id, [])
        if not cps:
            return None
        if step_index is not None:
            for cp in reversed(cps):
                if cp.step_index <= step_index:
                    return StateContext.from_dict(cp.context)
            return None
        return StateContext.from_dict(cps[-1].context)

    def list_checkpoints(self, task_id: str) -> list[Checkpoint]:
        return self._checkpoints.get(task_id, [])

    def rollback(self, task_id: str, steps: int = 1) -> StateContext | None:
        """回滚到前 N 步"""
        cps = self._checkpoints.get(task_id, [])
        if len(cps) <= steps:
            return None
        target = cps[-(steps + 1)]
        return StateContext.from_dict(target.context)


# ─── Tool Dispatcher ─────────────────────────────────────────

@dataclass
class ToolResult:
    """工具调用结果"""
    tool_name: str
    success: bool
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    tokens_used: int = 0


class ToolDispatcher:
    """工具分发器：带重试、超时、回滚"""

    def __init__(self, max_retries: int = 3, timeout: float = 60.0):
        self._tools: dict[str, Callable] = {}
        self._rollback_handlers: dict[str, Callable] = {}
        self._max_retries = max_retries
        self._timeout = timeout

    def register(self, name: str, handler: Callable, rollback: Callable | None = None):
        """注册工具"""
        self._tools[name] = handler
        if rollback:
            self._rollback_handlers[name] = rollback

    def dispatch(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """分发工具调用，带重试"""
        if tool_name not in self._tools:
            return ToolResult(tool_name=tool_name, success=False, error=f"Unknown tool: {tool_name}")

        handler = self._tools[tool_name]
        last_error = None

        for attempt in range(1, self._max_retries + 1):
            start = time.monotonic()
            try:
                result = handler(**kwargs)
                duration = (time.monotonic() - start) * 1000
                return ToolResult(
                    tool_name=tool_name,
                    success=True,
                    result=result,
                    duration_ms=duration,
                )
            except Exception as e:
                last_error = str(e)
                duration = (time.monotonic() - start) * 1000
                if attempt < self._max_retries:
                    time.sleep(min(2 ** attempt, 10))  # exponential backoff

        return ToolResult(
            tool_name=tool_name,
            success=False,
            error=f"Failed after {self._max_retries} retries: {last_error}",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    def rollback(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """回滚工具调用"""
        if tool_name not in self._rollback_handlers:
            return ToolResult(tool_name=tool_name, success=False, error="No rollback handler")
        handler = self._rollback_handlers[tool_name]
        try:
            result = handler(**kwargs)
            return ToolResult(tool_name=tool_name, success=True, result=result)
        except Exception as e:
            return ToolResult(tool_name=tool_name, success=False, error=str(e))


# ─── Workflow Graph ──────────────────────────────────────────

class WorkflowGraph:
    """工作流图管理"""

    def __init__(self, name: str):
        self.name = name
        self._nodes: dict[str, Callable] = {}
        self._edges: dict[str, str] = {}
        self._conditions: dict[str, Callable] = {}

    def add_node(self, name: str, handler: Callable):
        self._nodes[name] = handler
        return self

    def add_edge(self, from_node: str, to_node: str):
        self._edges[from_node] = to_node
        return self

    def add_conditional_edge(self, from_node: str, condition: Callable, default: str):
        self._conditions[from_node] = condition
        self._edges[from_node] = default
        return self

    def execute(self, ctx: StateContext) -> StateContext:
        """执行工作流"""
        current = "start"
        visited = set()

        while current and current != "end":
            if current in visited:
                ctx.errors.append(f"Cycle detected at node: {current}")
                break
            visited.add(current)

            if current not in self._nodes:
                break

            handler = self._nodes[current]
            try:
                ctx = handler(ctx)
            except Exception as e:
                ctx.errors.append(f"Node {current} error: {e}")
                break

            # Determine next node
            if current in self._conditions:
                next_node = self._conditions[current](ctx)
                if not next_node:
                    next_node = self._edges.get(current)
            else:
                next_node = self._edges.get(current)

            current = next_node

        return ctx

    def to_langgraph(self) -> Any:
        """转换为 LangGraph StateGraph"""
        if StateGraph is None:
            raise ImportError("langgraph is required for to_langgraph()")

        graph = StateGraph(dict)
        for name, handler in self._nodes.items():
            graph.add_node(name, handler)

        for from_node, to_node in self._edges.items():
            if from_node in self._conditions:
                graph.add_conditional_edges(from_node, self._conditions[from_node])
            else:
                graph.add_edge(from_node, to_node)

        return graph.compile()


# ─── Orchestrator (Main Entry) ───────────────────────────────

class Orchestrator:
    """
    ZenOS Orchestrator - Agent OS Kernel

    职责：
    - 状态机管理
    - 任务调度
    - 工作流执行
    - 工具分发
    - 检查点/回滚
    - 事件溯源
    """

    def __init__(
        self,
        event_store: EventStore | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        tool_dispatcher: ToolDispatcher | None = None,
    ):
        self.event_store = event_store or EventStore()
        self.checkpoint_manager = checkpoint_manager or CheckpointManager()
        self.tool_dispatcher = tool_dispatcher or ToolDispatcher()
        self._workflows: dict[str, WorkflowGraph] = {}

    def register_workflow(self, name: str, workflow: WorkflowGraph):
        """注册工作流"""
        self._workflows[name] = workflow

    def execute_task(
        self,
        task: str,
        workflow_name: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> StateContext:
        """
        执行任务的主入口

        流程：IDLE → PLANNING → EXECUTING → REVIEWING → DONE/FAILED
        """
        ctx = StateContext(task=task, metadata=metadata or {})

        # PLANNING
        ctx.transition_to(AgentState.PLANNING)
        self.event_store.append(ctx.task_id, "state_change", {"state": "planning"})

        try:
            ctx.plan = self._plan_task(task)
            self.event_store.append(ctx.task_id, "task_planned", {"plan": ctx.plan})
        except Exception as e:
            ctx.errors.append(f"Planning failed: {e}")
            ctx.transition_to(AgentState.FAILED)
            return ctx

        # EXECUTING
        ctx.transition_to(AgentState.EXECUTING)
        self.event_store.append(ctx.task_id, "state_change", {"state": "executing"})

        workflow = self._workflows.get(workflow_name)
        if workflow:
            ctx = workflow.execute(ctx)
        else:
            # Default: sequential execution
            for i, step in enumerate(ctx.plan):
                ctx.current_step = i
                self.checkpoint_manager.save(ctx)
                ctx.results[step] = {"status": "executed", "step": i}

        # REVIEWING
        ctx.transition_to(AgentState.REVIEWING)
        self.event_store.append(ctx.task_id, "state_change", {"state": "reviewing"})

        if not ctx.errors:
            ctx.transition_to(AgentState.DONE)
            self.event_store.append(ctx.task_id, "task_completed", {"task_id": ctx.task_id})
        else:
            # Try rollback
            ctx.transition_to(AgentState.ROLLING_BACK)
            self.event_store.append(ctx.task_id, "state_change", {"state": "rolling_back"})

            for step_name in reversed(ctx.plan[:ctx.current_step + 1]):
                if step_name in self.tool_dispatcher._rollback_handlers:
                    self.tool_dispatcher.rollback(step_name)

            ctx.transition_to(AgentState.FAILED)
            self.event_store.append(ctx.task_id, "task_failed", {"errors": ctx.errors})

        return ctx

    def _plan_task(self, task: str) -> list[str]:
        """任务规划：分解为子任务（简单实现，实际应由 LLM 完成）"""
        # TODO: 接入 Model Router + LLM 进行智能规划
        return [f"step_{i}" for i in range(3)]

    def restore_task(self, task_id: str) -> StateContext | None:
        """从检查点恢复任务"""
        return self.checkpoint_manager.restore(task_id)

    def rollback_task(self, task_id: str, steps: int = 1) -> StateContext | None:
        """回滚任务"""
        return self.checkpoint_manager.rollback(task_id, steps)


# ─── Convenience: Create Default Orchestrator ────────────────

def create_orchestrator() -> Orchestrator:
    """创建默认配置的 Orchestrator"""
    event_store = EventStore()
    checkpoint_mgr = CheckpointManager()
    tool_dispatcher = ToolDispatcher()

    orch = Orchestrator(
        event_store=event_store,
        checkpoint_manager=checkpoint_mgr,
        tool_dispatcher=tool_dispatcher,
    )

    # Register default task workflow
    workflow = WorkflowGraph("default")
    workflow.add_node("start", lambda ctx: ctx)
    workflow.add_edge("start", "end")
    orch.register_workflow("default", workflow)

    return orch
