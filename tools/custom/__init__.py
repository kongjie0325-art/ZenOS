"""Custom tool loader.

Loads tool definitions from YAML or JSON files and produces
:class:`BaseTool` instances dynamically.

Expected YAML/JSON schema::

    name: my_tool
    description: "Does something useful."
    parameters:
      - name: input
        type: string
        description: "Input text."
        required: true
      - name: count
        type: integer
        description: "How many."
        required: false
        default: 1
    # One of the following execution strategies:
    command: "echo {input} | head -n {count}"     # shell command template
    http:
      url: "https://api.example.com/thing"
      method: "POST"
      body: "{{input: {input}, count: {count}}}"
"""

from __future__ import annotations

import json
import logging
import os
import string
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from zenos.tools.base import BaseTool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

try:
    import yaml as _yaml

    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


class _CustomTool(BaseTool):
    """A tool dynamically created from a YAML/JSON definition.

    Supports two execution strategies:

    * **shell** -- a command template with Python ``string.Formatter``
      placeholders for each parameter.
    * **http** -- an HTTP request definition (url, method, headers, body
      template).
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: List[ToolParameter],
        command: Optional[str] = None,
        http: Optional[Dict[str, Any]] = None,
    ):
        self._name = name
        self._description = description
        self._parameters = parameters
        self._command = command
        self._http = http

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @property
    def description(self) -> str:  # type: ignore[override]
        return self._description

    @property
    def parameters(self) -> List[ToolParameter]:  # type: ignore[override]
        return self._parameters

    def execute(self, **kwargs: Any) -> ToolResult:
        if self._command:
            return self._exec_shell(**kwargs)
        if self._http:
            return self._exec_http(**kwargs)
        return ToolResult.fail(
            error=f"Tool '{self._name}' has no execution strategy."
        )

    def _exec_shell(self, **kwargs: Any) -> ToolResult:
        try:
            cmd = self._command.format(**kwargs)  # type: ignore[arg-type]
        except KeyError as exc:
            return ToolResult.fail(error=f"Missing template variable: {exc}")

        import subprocess

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                shell=True,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.fail(error="Command timed out after 60s.")
        except OSError as exc:
            return ToolResult.fail(error=f"Execution error: {exc}")

        return ToolResult.ok(
            content={
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "exit_code": proc.returncode,
            },
            command=cmd,
        )

    def _exec_http(self, **kwargs: Any) -> ToolResult:
        import urllib.error
        import urllib.parse
        import urllib.request

        http_def = self._http
        url: str = _render_template(http_def.get("url", ""), kwargs)  # type: ignore[arg-type]
        method: str = http_def.get("method", "GET").upper()  # type: ignore[union-attr]
        headers: Dict[str, str] = {}
        raw_headers = http_def.get("headers", {})  # type: ignore[union-attr]
        for k, v in raw_headers.items():
            headers[k] = _render_template(str(v), kwargs)

        body_tmpl = http_def.get("body")  # type: ignore[union-attr]
        data: Optional[bytes] = None
        if body_tmpl is not None:
            rendered = _render_template(str(body_tmpl), kwargs)
            data = rendered.encode("utf-8")
            headers.setdefault("Content-Type", "application/json")

        req = urllib.request.Request(url, data=data, method=method)
        for k, v in headers.items():
            req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_body = resp.read().decode("utf-8", errors="replace")
                status = resp.status
        except urllib.error.HTTPError as exc:
            resp_body = exc.read().decode("utf-8", errors="replace")
            status = exc.code
        except OSError as exc:
            return ToolResult.fail(error=f"HTTP error: {exc}")

        return ToolResult.ok(
            content={"status": status, "body": resp_body},
            url=url,
            method=method,
        )


def _render_template(tmpl: str, context: Dict[str, Any]) -> str:
    """Render a simple ``{param}`` template string with *context*."""
    class _SafeFormatter(string.Formatter):
        def get_field(self, field_name: str, args: Any, kwargs: Any) -> Any:
            if field_name in kwargs:
                return kwargs[field_name], field_name
            return f"{{{field_name}}}", field_name

    return _SafeFormatter().format(tmpl, **context)


class CustomToolLoader:
    """Loads custom tool definitions from YAML or JSON files.

    Usage::

        loader = CustomToolLoader()
        tool = loader.load(Path("tools/my_tool.yaml"))
        result = tool.run(input="hello", count=3)

    Or load an entire directory::

        tools = loader.load_dir(Path("tools/"))
    """

    def __init__(self, base_dir: Optional[str] = None):
        """Create the loader.

        Args:
            base_dir: Optional base directory for relative paths.
        """
        self._base_dir = Path(base_dir).expanduser().resolve() if base_dir else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, path: Union[str, Path]) -> BaseTool:
        """Load a single tool definition from *path*.

        Args:
            path: Path to a ``.yaml``, ``.yml``, or ``.json`` file.

        Returns:
            A :class:`BaseTool` instance.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file format is unsupported or the definition
                is invalid.
        """
        p = Path(path) if self._base_dir is None else self._base_dir / path
        p = p.expanduser().resolve()

        if not p.exists():
            raise FileNotFoundError(f"Tool definition not found: '{p}'")

        raw = self._read_file(p)
        return self._parse_definition(raw, str(p))

    def load_dir(self, dir_path: Union[str, Path]) -> List[BaseTool]:
        """Load all tool definitions from a directory.

        Args:
            dir_path: Path to a directory containing ``.yaml``, ``.yml``,
                or ``.json`` files.

        Returns:
            List of :class:`BaseTool` instances.
        """
        d = Path(dir_path) if self._base_dir is None else self._base_dir / dir_path
        d = d.expanduser().resolve()

        if not d.is_dir():
            raise NotADirectoryError(f"Not a directory: '{d}'")

        tools: List[BaseTool] = []
        for ext in ("*.yaml", "*.yml", "*.json"):
            for fp in sorted(d.glob(ext)):
                try:
                    tools.append(self.load(fp))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Skipping %s: %s", fp, exc)
        return tools

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_file(self, path: Path) -> Dict[str, Any]:
        """Read and parse a YAML or JSON file."""
        suffix = path.suffix.lower()
        text = path.read_text(encoding="utf-8")

        if suffix in (".yaml", ".yml"):
            if not _HAS_YAML:
                raise ValueError(
                    "PyYAML is required to load YAML tool definitions. "
                    "Install it with: pip install pyyaml"
                )
            return _yaml.safe_load(text)  # type: ignore[no-any-return]
        if suffix == ".json":
            return json.loads(text)  # type: ignore[no-any-return]
        raise ValueError(f"Unsupported file format: '{suffix}'")

    def _parse_definition(self, raw: Dict[str, Any], source: str) -> _CustomTool:
        """Validate and convert a raw definition dict into a tool."""
        name = raw.get("name")
        if not name or not isinstance(name, str):
            raise ValueError(f"Invalid or missing 'name' in {source}")

        description = raw.get("description", "")
        if not isinstance(description, str):
            raise ValueError(f"Invalid 'description' in {source}")

        parameters: List[ToolParameter] = []
        for idx, param_def in enumerate(raw.get("parameters", [])):
            try:
                parameters.append(
                    ToolParameter(
                        name=param_def["name"],
                        type=param_def.get("type", "string"),
                        description=param_def.get("description", ""),
                        required=param_def.get("required", True),
                        default=param_def.get("default"),
                    )
                )
            except KeyError:
                raise ValueError(
                    f"Parameter at index {idx} in {source} is missing 'name'."
                )

        command = raw.get("command")
        http_def = raw.get("http")

        if command is None and http_def is None:
            raise ValueError(
                f"Tool '{name}' in {source} must define 'command' or 'http'."
            )

        return _CustomTool(
            name=name,
            description=description,
            parameters=parameters,
            command=command,
            http=http_def,
        )
