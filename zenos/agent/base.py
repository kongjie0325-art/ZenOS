from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from zenos.agent.planning.planner import TaskPlanner
from zenos.agent.planning.task import Task, TaskStatus
from zenos.agent.reasoning.chain import ChainOfThought
from zenos.agent.reasoning.reflection import Reflection
from zenos.agent.execution.executor import Executor
from zenos.agent.execution.safety import SafetyChecker

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """Metadata describing a registered tool callable."""

    name: str
    description: str
    func: Callable[..., Any]
    parameters: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class AgentContext:
    """Mutable context carried through the think-act-observe loop."""

    goal: str
    agent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    iteration: int = 0
    memory: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def add_to_memory(self, role: str, content: str) -> None:
        """Append an entry to the agent's episodic memory."""
        self.memory.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.utcnow().isoformat(),
                "iteration": self.iteration,
            }
        )


class BaseAgent(ABC):
    """Abstract base agent implementing a think-act-observe reasoning loop.

    Subclasses must implement :meth:`think`, :meth:`act`, and :meth:`observe`.
    The orchestration logic lives in :meth:`run`, which iterates until the
    goal is satisfied or *max_iterations* is reached.

    Parameters
    ----------
    max_iterations:
        Hard upper bound on loop iterations before the agent gives up.
    planner:
        Optional task-planner instance.  A default is created when *None*.
    executor:
        Optional tool executor.  A default is created when *None*.
    safety_checker:
        Optional safety checker.  A default is created when *None*.
    reflection:
        Optional self-reflection module.  A default is created when *None*.
    reasoning:
        Optional chain-of-thought engine.  A default is created when *None*.
    """

    def __init__(
        self,
        max_iterations: int = 50,
        planner: Optional[TaskPlanner] = None,
        executor: Optional[Executor] = None,
        safety_checker: Optional[SafetyChecker] = None,
        reflection: Optional[Reflection] = None,
        reasoning: Optional[ChainOfThought] = None,
    ) -> None:
        self.max_iterations: int = max_iterations
        self.planner: TaskPlanner = planner or TaskPlanner()
        self.executor: Executor = executor or Executor()
        self.safety_checker: SafetyChecker = safety_checker or SafetyChecker()
        self.reflection: Reflection = reflection or Reflection()
        self.reasoning: ChainOfThought = reasoning or ChainOfThought()

        self._tools: Dict[str, ToolDefinition] = {}
        self._context: Optional[AgentContext] = None

    # ------------------------------------------------------------------
    # Tool registry
    # ------------------------------------------------------------------

    def register_tool(
        self,
        name: str,
        func: Callable[..., Any],
        description: str = "",
        parameters: Optional[Dict[str, str]] = None,
    ) -> None:
        """Register a callable as a tool the agent can invoke."""

        if name in self._tools:
            logger.warning("Overwriting existing tool registration for '%s'.", name)

        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            func=func,
            parameters=parameters or {},
        )
        logger.info("Registered tool '%s'.", name)

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Return the ``ToolDefinition`` for *name*, or ``None``."""
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        """Return all registered tools."""
        return list(self._tools.values())

    def disable_tool(self, name: str) -> bool:
        """Disable a tool by name.  Returns ``True`` if it existed."""
        tool = self._tools.get(name)
        if tool is not None:
            tool.enabled = False
            return True
        return False

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    def run(self, goal: str, **kwargs: Any) -> AgentContext:
        """Execute the think-act-observe loop until the goal is met.

        Parameters
        ----------
        goal:
            Natural-language description of the objective.
        **kwargs:
            Extra key-value pairs merged into the agent context metadata.

        Returns
        -------
        AgentContext
            The final context object containing the full execution trace.
        """
        self._context = AgentContext(goal=goal, metadata=kwargs)
        logger.info("Agent %s starting — goal: %s", self._context.agent_id, goal)

        plan = self.planner.create_plan(goal)
        self._context.add_to_memory("system", f"Plan created with {len(plan)} task(s).")

        for task in plan:
            if task.status == TaskStatus.COMPLETED:
                continue
            self._context.add_to_memory("system", f"Dispatched task: {task.description}")

        while self._context.iteration < self.max_iterations:
            self._context.iteration += 1
            logger.debug(
                "Iteration %d / %d", self._context.iteration, self.max_iterations
            )

            thought = self.think()
            self._context.add_to_memory("thought", str(thought))

            action_result = self.act(thought)
            self._context.add_to_memory("action", str(action_result))

            observation = self.observe(action_result)
            self._context.add_to_memory("observation", observation)

            if self._is_goal_satisfied():
                logger.info("Goal satisfied after %d iteration(s).", self._context.iteration)
                break

            # Periodic self-reflection every 5 iterations
            if self._context.iteration % 5 == 0:
                critique = self.reflect()
                self._context.add_to_memory("reflection", critique)

        else:
            logger.warning(
                "Max iterations (%d) reached without satisfying the goal.",
                self.max_iterations,
            )

        return self._context

    # ------------------------------------------------------------------
    # Abstract hooks
    # ------------------------------------------------------------------

    @abstractmethod
    def think(self) -> str:
        """Produce the next reasoning step (a *thought* string).

        Returns
        -------
        str
            A natural-language or structured description of the next
            reasoning step the agent intends to take.
        """
        ...

    @abstractmethod
    def act(self, thought: str) -> Any:
        """Execute an *action* derived from *thought*.

        Parameters
        ----------
        thought:
            The reasoning string produced by :meth:`think`.

        Returns
        -------
        Any
            An opaque action-result object that will be passed to
            :meth:`observe`.
        """
        ...

    @abstractmethod
    def observe(self, action_result: Any) -> str:
        """Produce an *observation* string from the action result.

        Parameters
        ----------
        action_result:
            The value returned by :meth:`act`.

        Returns
        -------
        str
            A natural-language summary of what was observed.
        """
        ...

    # ------------------------------------------------------------------
    # Reflection
    # ------------------------------------------------------------------

    def reflect(self) -> str:
        """Run the self-reflection module over recent memory.

        Returns
        -------
        str
            A critique or improvement suggestion.
        """
        recent = self._context.memory[-10:] if self._context else []
        return self.reflection.reflect(
            goal=self._context.goal if self._context else "",
            memory=recent,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_goal_satisfied(self) -> bool:
        """Return ``True`` when the current plan is fully completed.

        The default implementation checks whether every task in the
        planner's current plan has ``status == TaskCompleted``.
        Subclasses may override for domain-specific termination logic.
        """
        return all(
            t.status == TaskStatus.COMPLETED for t in self.planner.current_plan
        )
