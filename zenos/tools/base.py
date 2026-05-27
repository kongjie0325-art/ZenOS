"""Base abstractions for the ZenOS tool system.

Defines the core types that every tool and its results share:

* ToolParameter  – a single input parameter descriptor.
* ToolResult     – the standardised output of a tool invocation.
* ToolSchema     – a JSON-Schema-compatible description of a tool.
* BaseTool       – abstract base class that all tools extend.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type


@dataclass
class ToolParameter:
    """Describes a single input parameter accepted by a tool.

    Attributes:
        name: Machine-readable parameter name.
        type: JSON-Schema type string (``"string"``, ``"integer"``,
            ``"boolean"``, ``"array"``, ``"object"``, etc.).
        description: Human-readable explanation of the parameter.
        required: Whether the caller *must* supply this parameter.
        default: Value used when the caller omits a required=False parameter.
        enum: Optional list of allowed values (creates a JSON Schema enum).
    """

    name: str
    type: str
    description: str = ""
    required: bool = True
    default: Any = None
    enum: Optional[List[Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-Schema *property* fragment for this parameter."""
        d: Dict[str, Any] = {
            "type": self.type,
            "description": self.description,
        }
        if self.default is not None:
            d["default"] = self.default
        if self.enum is not None:
            d["enum"] = self.enum
        return d


@dataclass
class ToolResult:
    """Standard wrapper around the outcome of a tool invocation.

    Attributes:
        success: ``True`` if the tool ran without error.
        content: The primary payload — may be a str, dict, list, or
            anything the caller expects.
        metadata: Arbitrary key-value pairs useful for debugging or
            downstream processing.
        error: Human-readable error message when *success* is ``False``.
    """

    success: bool
    content: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    # -- convenience helpers -------------------------------------------

    @classmethod
    def ok(cls, content: Any = None, **metadata: Any) -> ToolResult:
        """Create a successful result."""
        return cls(success=True, content=content, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata: Any) -> ToolResult:
        """Create a failed result."""
        return cls(success=False, error=error, metadata=metadata)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        d: Dict[str, Any] = {"success": self.success}
        if self.content is not None:
            d["content"] = self.content
        if self.metadata:
            d["metadata"] = self.metadata
        if self.error is not None:
            d["error"] = self.error
        return d


@dataclass
class ToolSchema:
    """A JSON-Schema-compatible description of a tool's interface.

    This is the object you would hand to an LLM or an OpenAPI layer so
    it knows *what* a tool does and *how* to call it.

    Attributes:
        name: Unique tool identifier.
        description: What the tool does.
        parameters: List of :class:`ToolParameter` descriptors.
    """

    name: str
    description: str
    parameters: List[ToolParameter] = field(default_factory=list)

    def to_json_schema(self) -> Dict[str, Any]:
        """Convert to a JSON Schema *function calling* object."""
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for p in self.parameters:
            properties[p.name] = p.to_dict()
            if p.required:
                required.append(p.name)

        schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema

    def to_openai_function(self) -> Dict[str, Any]:
        """Return the format expected by OpenAI's function-calling API."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.to_json_schema(),
        }


class BaseTool(abc.ABC):
    """Abstract base for every ZenOS tool.

    Subclasses must define:

    * :attr:`name`  – short identifier (``"web_search"``, ``"shell"``, …).
    * :attr:`description` – one-line summary shown to the LLM.
    * :attr:`parameters` – list of :class:`ToolParameter`.
    * :meth:`execute` – the actual work.

    Example::

        class MyTool(BaseTool):
            name = "my_tool"
            description = "Does a thing."
            parameters = [
                ToolParameter("input", "string", "Thing to process."),
            ]

            def execute(self, **kwargs):
                return ToolResult.ok(content=f"processed {kwargs['input']}")
    """

    name: str = ""
    description: str = ""
    parameters: List[ToolParameter] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool with the given keyword arguments.

        Args:
            **kwargs: Parameter values matching :attr:`parameters`.

        Returns:
            A :class:`ToolResult` describing the outcome.
        """
        ...

    def validate(self, **kwargs: Any) -> List[str]:
        """Check that *kwargs* satisfy the parameter specification.

        Returns a list of human-readable error messages (empty list means
        validation passed).

        Subclasses can override to add additional domain checks beyond
        the base required/enum validation.

        Args:
            **kwargs: The parameters to validate.

        Returns:
            List of validation error messages.
        """
        errors: List[str] = []
        param_map: Dict[str, ToolParameter] = {p.name: p for p in self.parameters}

        # Check required parameters are present.
        for param in self.parameters:
            if param.required and param.name not in kwargs:
                errors.append(f"Missing required parameter: '{param.name}'")

        # Check enum constraints.
        for param in self.parameters:
            if param.name in kwargs and param.enum is not None:
                if kwargs[param.name] not in param.enum:
                    errors.append(
                        f"Parameter '{param.name}' must be one of "
                        f"{param.enum}, got {kwargs[param.name]!r}"
                    )

        # Warn about unknown parameters.
        for key in kwargs:
            if key not in param_map:
                errors.append(f"Unknown parameter: '{key}'")

        return errors

    def get_schema(self) -> ToolSchema:
        """Return the :class:`ToolSchema` for this tool."""
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters=list(self.parameters),
        )

    def run(self, **kwargs: Any) -> ToolResult:
        """Validate then execute in one step.

        This is the preferred entry point when calling a tool programmatically.

        Args:
            **kwargs: Parameter values.

        Returns:
            :class:`ToolResult`.
        """
        errors = self.validate(**kwargs)
        if errors:
            return ToolResult.fail(error="; ".join(errors))
        try:
            return self.execute(**kwargs)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(
                error=f"{type(exc).__name__}: {exc}",
                tool=self.name,
            )
