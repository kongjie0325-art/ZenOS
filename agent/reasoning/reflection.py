from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Critique:
    """Structured output of a self-reflection pass."""

    summary: str
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    confidence: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"Critique(confidence={self.confidence:.2f}, "
            f"issues={len(self.issues)}, suggestions={len(self.suggestions)})"
        )


class Reflection:
    """Self-reflection module that critiques and improves agent behaviour.

    The module maintains a history of critiques so that improvement
    suggestions can be tracked over time.

    Parameters
    ----------
    max_history:
        Maximum number of ``Critique`` objects to retain.
    """

    def __init__(self, max_history: int = 100) -> None:
        self.max_history: int = max_history
        self._critique_history: List[Critique] = []

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def reflect(self, goal: str, memory: List[Dict[str, Any]]) -> str:
        """Analyse recent *memory* entries with respect to *goal*.

        Parameters
        ----------
        goal:
            The agent's current objective.
        memory:
            Recent memory entries (each a dict with at least a ``role``
            and ``content`` key).

        Returns
        -------
        str
            A human-readable reflection summary.
        """
        critique = self.critique(goal, memory)
        self._store_critique(critique)

        summary_parts = [f"Reflection on goal: {goal}", critique.summary]
        if critique.issues:
            summary_parts.append("Issues:\n" + "\n".join(f"  - {i}" for i in critique.issues))
        if critique.suggestions:
            summary_parts.append("Suggestions:\n" + "\n".join(f"  - {s}" for s in critique.suggestions))

        result = "\n".join(summary_parts)
        logger.debug("Reflection produced: %s", result[:120])
        return result

    def critique(
        self, goal: str, memory: List[Dict[str, Any]], context: Optional[Dict[str, Any]] = None
    ) -> Critique:
        """Produce a structured ``Critique`` of recent behaviour.

        Parameters
        ----------
        goal:
            The agent's objective.
        memory:
            Recent memory entries to evaluate.
        context:
            Optional extra context for the critique.

        Returns
        -------
        Critique
            Structured critique with issues, suggestions, and confidence.
        """
        issues: List[str] = []
        suggestions: List[str] = []

        # Heuristic: check for repeated failed actions
        action_failures = sum(
            1 for m in memory if m.get("role") == "action" and not m.get("content")
        )
        if action_failures > 2:
            issues.append(f"Detected {action_failures} empty/failed action results recently.")
            suggestions.append("Consider revising the action strategy or adding error handling.")

        # Heuristic: check for stagnation (no new observations)
        observations = [m for m in memory if m.get("role") == "observation"]
        if len(observations) >= 3:
            unique_obs = {m.get("content", "") for m in observations[-3:]}
            if len(unique_obs) <= 1:
                issues.append("Observations appear stagnant — the agent may be stuck in a loop.")
                suggestions.append("Introduce a new approach or break the goal into smaller sub-goals.")

        # Heuristic: goal relevance
        thought_entries = [m for m in memory if m.get("role") == "thought"]
        if thought_entries and goal:
            last_thought = thought_entries[-1].get("content", "")
            if last_thought and goal.lower() not in last_thought.lower():
                issues.append("Latest thought may have drifted from the original goal.")
                suggestions.append("Re-anchor reasoning to the original goal statement.")

        confidence = 1.0 - (len(issues) * 0.15)
        confidence = max(0.0, min(1.0, confidence))

        summary = (
            f"Analysed {len(memory)} memory entries. "
            f"Found {len(issues)} issue(s) and {len(suggestions)} suggestion(s). "
            f"Confidence: {confidence:.0%}."
        )

        return Critique(
            summary=summary,
            issues=issues,
            suggestions=suggestions,
            confidence=confidence,
        )

    def improve(self, critique: Critique) -> List[str]:
        """Return actionable improvement items derived from *critique*.

        Parameters
        ----------
        critique:
            A ``Critique`` object (typically from :meth:`critique`).

        Returns
        -------
        list[str]
            Ordered list of improvement actions.
        """
        improvements: List[str] = []

        for issue in critique.issues:
            improvements.append(f"Address: {issue}")

        for suggestion in critique.suggestions:
            improvements.append(f"Implement: {suggestion}")

        if not improvements:
            improvements.append("No improvements needed — current trajectory looks good.")

        logger.info("Generated %d improvement item(s).", len(improvements))
        return improvements

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    @property
    def history(self) -> List[Critique]:
        """Return the full critique history."""
        return list(self._critique_history)

    def _store_critique(self, critique: Critique) -> None:
        """Append a critique to history, evicting oldest if over limit."""
        self._critique_history.append(critique)
        if len(self._critique_history) > self.max_history:
            self._critique_history.pop(0)

    def reset_history(self) -> None:
        """Clear critique history."""
        self._critique_history.clear()

    def __repr__(self) -> str:
        return f"Reflection(history_size={len(self._critique_history)})"
