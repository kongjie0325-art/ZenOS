"""Tool adapter base class.

Provides an abstraction layer for wrapping external tools (e.g. LangChain
tools, OpenAI function specs, MCP tool servers) so they can be used
anywhere a :class:`BaseTool` is expected.

Subclasses override three hooks:

* :meth:`adapt_input`  -- convert BaseTool-style kwargs into the format
  the underlying tool expects.
* :meth:`wrap`         -- call the underlying tool.
* :meth:`adapt_output` -- convert the raw output into a :class:`ToolResult`.
"""

from __future__ import annotations

import abc
import logging
from typing import Any, Dict, List, Optional

from zenos.tools.base import BaseTool, ToolParameter, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class ToolAdapter(BaseTool):
    """Wrap an external tool so it conforms to the ZenOS :class:`BaseTool` interface.

    This is an abstract base -- subclasses must implement :meth:`wrap`,
    and may override :meth:`adapt_input` and :meth:`adapt_output`.

    Example::

        class MyLangChainAdapter(ToolAdapter):
            def __init__(self, langchain_tool):
                super().__init__(
                    name=langchain_tool.name,
                    description=langchain_tool.description,
                    parameters=_convert_params(langchain_tool.args_schema),
                )
                self._tool = langchain_tool

            def wrap(self, **kwargs):
                return self._tool.run(**kwargs)

            def adapt_output(self, raw):
                return ToolResult.ok(content=str(raw))

    Args:
        name: Tool identifier.
        description: Human-readable description.
        parameters: List of parameter descriptors.
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Optional[List[ToolParameter]] = None,
    ):
        self._name = name
        self._description = description
        self._parameters = parameters or []

    # -- Properties (read-only) ---------------------------------------

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @property
    def description(self) -> str:  # type: ignore[override]
        return self._description

    @property
    def parameters(self) -> List[ToolParameter]:  # type: ignore[override]
        return self._parameters

    # -- Abstract interface --------------------------------------------

    @abc.abstractmethod
    def wrap(self, **kwargs: Any) -> Any:
        """Invoke the underlying tool with the adapted keyword arguments.

        Args:
            **kwargs: Input parameters (already passed through
                :meth:`adapt_input` by :meth:`execute`).

        Returns:
            Raw output from the underlying tool.  This value is then
            forwarded to :meth:`adapt_output`.
        """
        ...

    def adapt_input(self, **kwargs: Any) -> Dict[str, Any]:
        """Convert BaseTool-style kwargs into the format the underlying tool expects.

        The default implementation returns *kwargs* unchanged.  Subclasses
        override this to rename keys, inject defaults, coerce types, etc.

        Args:
            **kwargs: The parameter values supplied by the caller.

        Returns:
            Dict of adapted keyword arguments for :meth:`wrap`.
        """
        return kwargs

    def adapt_output(self, raw: Any) -> ToolResult:
        """Convert the raw output of :meth:`wrap` into a :class:`ToolResult`.

        The default implementation wraps non-ToolResult values in
        ``ToolResult.ok(content=raw)`` and passes ToolResult instances
        through unchanged.

        Args:
            raw: The return value of :meth:`wrap`.

        Returns:
            A standardised :class:`ToolResult`.
        """
        if isinstance(raw, ToolResult):
            return raw
        return ToolResult.ok(content=raw)

    # -- BaseTool implementation ---------------------------------------

    def execute(self, **kwargs: Any) -> ToolResult:
        """Adapt input, call the underlying tool, adapt output.

        Args:
            **kwargs: Parameter values matching :attr:`parameters`.

        Returns:
            :class:`ToolResult` from the wrapped tool.
        """
        adapted = self.adapt_input(**kwargs)
        try:
            raw = self.wrap(**adapted)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Wrapped tool '%s' raised an exception", self._name)
            return ToolResult.fail(
                error=f"{type(exc).__name__}: {exc}",
                tool=self._name,
            )
        try:
            return self.adapt_output(raw)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "adapt_output for tool '%s' raised an exception", self._name
            )
            return ToolResult.fail(
                error=f"Output adaptation error: {exc}",
                tool=self._name,
            )
