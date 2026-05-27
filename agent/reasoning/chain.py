from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ThoughtStep:
    """A single node in a chain-of-thought reasoning trace."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    parent_id: Optional[str] = None
    branch_id: str = "main"
    depth: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class ChainOfThought:
    """Chain-of-thought reasoning engine with branching and backtracking.

    The engine maintains a directed acyclic graph of ``ThoughtStep`` nodes
    rooted on a *main* branch.  Calling :meth:`step` extends the current
    branch; :meth:`backtrack` rewinds to a previous node; :meth:`branch`
    forks a new named branch from any existing node.

    Parameters
    ----------
    max_depth:
        Maximum allowed reasoning depth before the engine warns.
    """

    def __init__(self, max_depth: int = 100) -> None:
        self.max_depth: int = max_depth
        self._steps: Dict[str, ThoughtStep] = {}
        self._current_branch: str = "main"
        self._current_step_id: Optional[str] = None
        self._branches: Dict[str, List[str]] = {"main": []}

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def step(self, content: str, **metadata: Any) -> ThoughtStep:
        """Append a new reasoning step on the current branch.

        Parameters
        ----------
        content:
            The reasoning content for this step.
        **metadata:
            Arbitrary metadata attached to the step.

        Returns
        -------
        ThoughtStep
            The newly created step.
        """
        parent_id = self._current_step_id
        depth = 0
        if parent_id is not None:
            parent = self._steps.get(parent_id)
            if parent is not None:
                depth = parent.depth + 1

        if depth > self.max_depth:
            logger.warning(
                "Chain-of-thought depth %d exceeds max_depth %d.",
                depth,
                self.max_depth,
            )

        thought = ThoughtStep(
            content=content,
            parent_id=parent_id,
            branch_id=self._current_branch,
            depth=depth,
            metadata=metadata,
        )

        self._steps[thought.id] = thought
        self._branches.setdefault(self._current_branch, []).append(thought.id)
        self._current_step_id = thought.id

        logger.debug("CoT step [%s] depth=%d: %s", self._current_branch, depth, content[:80])
        return thought

    def backtrack(self, steps: int = 1) -> Optional[ThoughtStep]:
        """Move the current position *steps* steps backward in the chain.

        Parameters
        ----------
        steps:
            Number of steps to walk back (must be ≥ 1).

        Returns
        -------
        ThoughtStep | None
            The step landed on, or ``None`` if backtracking goes past the
            beginning of the chain.
        """
        if steps < 1:
            raise ValueError("steps must be >= 1")

        current_id = self._current_step_id
        for _ in range(steps):
            if current_id is None:
                logger.warning("Backtracked past the beginning of the chain.")
                return None
            node = self._steps.get(current_id)
            if node is None:
                return None
            current_id = node.parent_id

        self._current_step_id = current_id
        if current_id is not None:
            logger.debug("Backtracked to step %s.", current_id[:8])
            return self._steps.get(current_id)
        return None

    def branch(self, name: str, from_step_id: Optional[str] = None) -> str:
        """Create a new reasoning branch named *name*.

        Parameters
        ----------
        name:
            Unique branch identifier.
        from_step_id:
            Step to branch from.  Defaults to the current step.

        Returns
        -------
        str
            The branch name (same as *name*).
        """
        if name in self._branches:
            logger.warning("Branch '%s' already exists — switching to it.", name)
            self._current_branch = name
            if self._branches[name]:
                self._current_step_id = self._branches[name][-1]
            return name

        anchor_id = from_step_id or self._current_step_id
        self._branches[name] = []
        self._current_branch = name
        self._current_step_id = anchor_id
        logger.debug("Created branch '%s' from step %s.", name, anchor_id[:8] if anchor_id else None)
        return name

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def current_step(self) -> Optional[ThoughtStep]:
        """Return the step at the current position."""
        if self._current_step_id is None:
            return None
        return self._steps.get(self._current_step_id)

    @property
    def trace(self) -> List[ThoughtStep]:
        """Return the full chain on the *main* branch, depth-first."""
        return self._branch_trace("main")

    def _branch_trace(self, branch_id: str) -> List[ThoughtStep]:
        """Return ordered steps for *branch_id*."""
        step_ids = self._branches.get(branch_id, [])
        return [self._steps[sid] for sid in step_ids if sid in self._steps]

    def get_branch_names(self) -> List[str]:
        """Return all branch names."""
        return list(self._branches.keys())

    def reset(self) -> None:
        """Clear all steps and branches, returning to the initial state."""
        self._steps.clear()
        self._current_branch = "main"
        self._current_step_id = None
        self._branches = {"main": []}
        logger.debug("ChainOfThought reset.")

    def __len__(self) -> int:
        return len(self._steps)

    def __repr__(self) -> str:
        return (
            f"ChainOfThought(steps={len(self._steps)}, "
            f"branches={len(self._branches)}, "
            f"current_branch={self._current_branch!r})"
        )
