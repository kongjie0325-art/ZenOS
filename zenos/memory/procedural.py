from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

__all__ = ["Skill", "ProceduralMemory"]


@dataclass
class Skill:
    """Represents a procedural skill that can be executed.

    Attributes:
        id: Unique identifier for the skill.
        name: Human-readable name of the skill.
        description: What the skill does.
        func: The callable that executes the skill.
        metadata: Arbitrary metadata (tags, version, etc.).
        created_at: When the skill was registered.
        usage_count: How many times the skill has been executed.
        importance: Scalar from 0.0 to 1.0 indicating significance.
    """

    name: str
    func: Callable[..., Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    usage_count: int = 0
    importance: float = 0.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.importance <= 1.0:
            raise ValueError(
                f"importance must be between 0 and 1, got {self.importance}"
            )


class ProceduralMemory:
    """Registry and executor for procedural skills.

    Skills are stored by id and can also be looked up by name. The registry
    tracks usage counts and provides filtering by tags and importance.
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._name_index: dict[str, str] = {}  # name -> id

    def register_skill(self, skill: Skill) -> str:
        """Register a skill in procedural memory.

        Args:
            skill: The skill to register.

        Returns:
            The id of the registered skill.
        """
        self._skills[skill.id] = skill
        self._name_index[skill.name] = skill.id
        return skill.id

    def get_skill(self, skill_id_or_name: str) -> Skill | None:
        """Look up a skill by id or name.

        Args:
            skill_id_or_name: Either the skill id or its name.

        Returns:
            The matching skill, or None.
        """
        if skill_id_or_name in self._skills:
            return self._skills[skill_id_or_name]
        sid = self._name_index.get(skill_id_or_name)
        if sid is not None:
            return self._skills.get(sid)
        return None

    def list_skills(
        self,
        tag: str | None = None,
        min_importance: float = 0.0,
    ) -> list[Skill]:
        """List registered skills, optionally filtered.

        Args:
            tag: If provided, only return skills that have this tag in
                their metadata ``tags`` list.
            min_importance: Minimum importance threshold.

        Returns:
            Matching skills sorted by usage count descending.
        """
        results: list[Skill] = []
        for skill in self._skills.values():
            if skill.importance < min_importance:
                continue
            if tag is not None:
                tags = skill.metadata.get("tags", [])
                if tag not in tags:
                    continue
            results.append(skill)
        results.sort(key=lambda s: -s.usage_count)
        return results

    def execute_skill(
        self, skill_id_or_name: str, *args: Any, **kwargs: Any
    ) -> Any:
        """Execute a skill by id or name.

        Increments the skill's usage count on successful execution.

        Args:
            skill_id_or_name: The skill id or name.
            *args: Positional arguments forwarded to the skill callable.
            **kwargs: Keyword arguments forwarded to the skill callable.

        Returns:
            The return value of the skill callable.

        Raises:
            KeyError: If the skill is not found.
        """
        skill = self.get_skill(skill_id_or_name)
        if skill is None:
            raise KeyError(f"Skill not found: {skill_id_or_name!r}")
        result = skill.func(*args, **kwargs)
        skill.usage_count += 1
        return result

    def __len__(self) -> int:
        return len(self._skills)
