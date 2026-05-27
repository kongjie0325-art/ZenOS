from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from zenos.agent.planning.task import Task, TaskPriority, TaskStatus

logger = logging.getLogger(__name__)


class TaskPlanner:
    """Decomposes high-level goals into ordered task plans.

    The planner maintains an internal list of tasks (the *current plan*)
    and provides methods to create, execute, and dynamically replan
    based on runtime feedback.

    Parameters
    ----------
    max_parallel:
        Maximum number of tasks that may execute concurrently.
    """

    def __init__(self, max_parallel: int = 4) -> None:
        self.max_parallel: int = max_parallel
        self.current_plan: List[Task] = []
        self._goal: Optional[str] = None

    # ------------------------------------------------------------------
    # Goal decomposition
    # ------------------------------------------------------------------

    def decompose_goal(self, goal: str) -> List[str]:
        """Break *goal* into an ordered list of sub-goal strings.

        The default implementation performs a simple sentence-splitting
        heuristic.  In a production system this would call an LLM or a
        domain-specific decomposition strategy.

        Parameters
        ----------
        goal:
            The high-level objective to decompose.

        Returns
        -------
        list[str]
            Ordered sub-goals.
        """
        # Heuristic: split on periods / newlines and drop empties.
        sub_goals: List[str] = [
            s.strip() for s in goal.replace("\n", ".").split(".") if s.strip()
        ]

        if not sub_goals:
            sub_goals = [goal]

        logger.debug("Decomposed goal into %d sub-goal(s): %s", len(sub_goals), sub_goals)
        return sub_goals

    # ------------------------------------------------------------------
    # Plan creation
    # ------------------------------------------------------------------

    def create_plan(
        self,
        goal: str,
        sub_goals: Optional[List[str]] = None,
        priority: TaskPriority = TaskPriority.MEDIUM,
    ) -> List[Task]:
        """Create a full task plan for *goal*.

        Parameters
        ----------
        goal:
            The top-level objective.
        sub_goals:
            Optional pre-decomposed sub-goals.  When *None*,
            :meth:`decompose_goal` is called automatically.
        priority:
            Default priority assigned to every task in the plan.

        Returns
        -------
        list[Task]
            An ordered list of ``Task`` objects with dependency links.
        """
        self._goal = goal
        steps = sub_goals or self.decompose_goal(goal)

        tasks: List[Task] = []
        previous_task_id: Optional[str] = None

        for idx, step in enumerate(steps):
            task = Task(
                description=step,
                status=TaskStatus.PENDING,
                priority=priority,
                step_index=idx,
            )
            if previous_task_id is not None:
                task.dependencies.append(previous_task_id)
            tasks.append(task)
            previous_task_id = task.id

        self.current_plan = tasks
        logger.info(
            "Created plan for goal '%s' with %d task(s).",
            goal,
            len(tasks),
        )
        return tasks

    # ------------------------------------------------------------------
    # Plan execution (orchestration)
    # ------------------------------------------------------------------

    def execute_plan(self, executor_callback: Any) -> Dict[str, Any]:
        """Execute the current plan using *executor_callback* for each task.

        Parameters
        ----------
        executor_callback:
            A callable ``(Task) -> Any`` that performs the actual work.

        Returns
        -------
        dict[str, Any]
            Mapping of task-id → result.
        """
        if not self.current_plan:
            logger.warning("execute_plan called with an empty plan.")
            return {}

        results: Dict[str, Any] = {}
        for task in self._ready_tasks():
            task.status = TaskStatus.IN_PROGRESS
            logger.info("Executing task %s: %s", task.id, task.description)

            try:
                result = executor_callback(task)
                task.result = result
                task.status = TaskStatus.COMPLETED
                task.completed_at = __import__("datetime").datetime.utcnow()
                results[task.id] = result
            except Exception:
                task.status = TaskStatus.FAILED
                logger.exception("Task %s failed.", task.id)
                results[task.id] = None

        return results

    # ------------------------------------------------------------------
    # Replanning
    # ------------------------------------------------------------------

    def replan(
        self,
        failed_task: Optional[Task] = None,
        additional_context: Optional[str] = None,
    ) -> List[Task]:
        """Rebuild the current plan, optionally retrying a failed task.

        Parameters
        ----------
        failed_task:
            The task that triggered the replan.
        additional_context:
            Extra information to inject into the new plan.

        Returns
        -------
        list[Task]
            The updated task list.
        """
        if self._goal is None:
            logger.warning("replan called without a stored goal.")
            return []

        # Collect incomplete tasks
        incomplete = [
            t for t in self.current_plan if t.status in (TaskStatus.PENDING, TaskStatus.FAILED)
        ]

        sub_goals = [t.description for t in incomplete]
        if additional_context:
            sub_goals.insert(0, additional_context)

        if failed_task is not None:
            logger.info("Replanning around failed task: %s", failed_task.description)
            failed_task.status = TaskStatus.PENDING  # Reset for retry

        return self.create_plan(self._goal, sub_goals=sub_goals)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ready_tasks(self) -> List[Task]:
        """Return tasks whose dependencies are all completed."""
        completed_ids = {t.id for t in self.current_plan if t.status == TaskStatus.COMPLETED}
        ready: List[Task] = []
        for task in self.current_plan:
            if task.status != TaskStatus.PENDING:
                continue
            if all(dep_id in completed_ids for dep_id in task.dependencies):
                ready.append(task)
        return ready

    @property
    def progress(self) -> float:
        """Fraction of tasks that are completed (0.0 – 1.0)."""
        if not self.current_plan:
            return 0.0
        done = sum(1 for t in self.current_plan if t.status == TaskStatus.COMPLETED)
        return done / len(self.current_plan)
