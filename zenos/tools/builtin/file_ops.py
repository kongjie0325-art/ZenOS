"""Built-in tools for local file operations.

Provides three tools:

* FileReadTool  -- read the contents of a file.
* FileWriteTool -- write (or overwrite) a file.
* FileListTool  -- list directory contents.
"""

from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from zenos.tools.base import BaseTool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Maximum file size that FileReadTool will read (10 MB).
_MAX_READ_SIZE: int = 10 * 1024 * 1024


@dataclass
class FileInfo:
    """Lightweight descriptor for a directory entry."""

    name: str
    path: str
    is_dir: bool
    size: int
    modified: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "is_dir": self.is_dir,
            "size": self.size,
            "modified": self.modified,
        }


def _safe_resolve(path: str, base_dir: Optional[str] = None) -> Path:
    """Resolve *path* and optionally constrain it under *base_dir*.

    Raises:
        ValueError: If *base_dir* is set and the resolved path escapes it.
    """
    p = Path(path).expanduser().resolve()
    if base_dir is not None:
        base = Path(base_dir).expanduser().resolve()
        try:
            p.relative_to(base)
        except ValueError:
            raise ValueError(
                f"Path '{path}' is outside the allowed base directory '{base_dir}'."
            )
    return p


class FileReadTool(BaseTool):
    """Read the contents of a local file.

    Parameters:
        path: Absolute or relative path to the file.
        encoding: Text encoding (default ``utf-8``).
        offset: Line number to start reading from (1-indexed).
        limit: Maximum number of lines to read.
    """

    name = "file_read"
    description = "Read the contents of a file and return it as a string."
    parameters = [
        ToolParameter(
            name="path",
            type="string",
            description="Path to the file to read.",
        ),
        ToolParameter(
            name="encoding",
            type="string",
            description="Text encoding.",
            required=False,
            default="utf-8",
        ),
        ToolParameter(
            name="offset",
            type="integer",
            description="Line number to start reading from (1-indexed).",
            required=False,
            default=1,
        ),
        ToolParameter(
            name="limit",
            type="integer",
            description="Maximum number of lines to read.",
            required=False,
            default=500,
        ),
    ]

    def __init__(self, base_dir: Optional[str] = None, max_size: int = _MAX_READ_SIZE):
        """Create the tool.

        Args:
            base_dir: If set, all paths must reside under this directory.
            max_size: Maximum file size in bytes that will be read.
        """
        self._base_dir = base_dir
        self._max_size = max_size

    def execute(self, **kwargs: Any) -> ToolResult:
        path_str: str = kwargs["path"]
        encoding: str = kwargs.get("encoding", "utf-8")
        offset: int = kwargs.get("offset", 1)
        limit: int = kwargs.get("limit", 500)

        try:
            p = _safe_resolve(path_str, self._base_dir)
        except ValueError as exc:
            return ToolResult.fail(error=str(exc))

        if not p.exists():
            return ToolResult.fail(error=f"File not found: '{p}'")
        if not p.is_file():
            return ToolResult.fail(error=f"Not a file: '{p}'")

        file_size = p.stat().st_size
        if file_size > self._max_size:
            return ToolResult.fail(
                error=(
                    f"File size ({file_size} bytes) exceeds maximum "
                    f"({self._max_size} bytes). Use offset/limit to read "
                    f"in chunks."
                )
            )

        try:
            text = p.read_text(encoding=encoding)
        except (OSError, UnicodeDecodeError) as exc:
            logger.exception("Failed to read file %s", p)
            return ToolResult.fail(error=f"Read error: {exc}")

        lines = text.splitlines()
        sliced = lines[offset - 1 : offset - 1 + limit]

        return ToolResult.ok(
            content="\n".join(sliced),
            path=str(p),
            total_lines=len(lines),
            returned_lines=len(sliced),
            encoding=encoding,
        )


class FileWriteTool(BaseTool):
    """Write text content to a local file.

    Creates parent directories if they do not exist.  Overwrites existing
    files by default.

    Parameters:
        path: Destination file path.
        content: Text to write.
        encoding: Text encoding (default ``utf-8``).
        append: If ``True``, append instead of overwrite.
    """

    name = "file_write"
    description = "Write text content to a file. Creates parent directories if needed."
    parameters = [
        ToolParameter(
            name="path",
            type="string",
            description="Path to the file to write.",
        ),
        ToolParameter(
            name="content",
            type="string",
            description="Text content to write.",
        ),
        ToolParameter(
            name="encoding",
            type="string",
            description="Text encoding.",
            required=False,
            default="utf-8",
        ),
        ToolParameter(
            name="append",
            type="boolean",
            description="Append to the file instead of overwriting.",
            required=False,
            default=False,
        ),
    ]

    def __init__(self, base_dir: Optional[str] = None):
        self._base_dir = base_dir

    def execute(self, **kwargs: Any) -> ToolResult:
        path_str: str = kwargs["path"]
        content: str = kwargs["content"]
        encoding: str = kwargs.get("encoding", "utf-8")
        append: bool = kwargs.get("append", False)

        try:
            p = _safe_resolve(path_str, self._base_dir)
        except ValueError as exc:
            return ToolResult.fail(error=str(exc))

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with open(p, mode, encoding=encoding) as fh:
                fh.write(content)
        except OSError as exc:
            logger.exception("Failed to write file %s", p)
            return ToolResult.fail(error=f"Write error: {exc}")

        return ToolResult.ok(
            content=None,
            path=str(p),
            bytes_written=len(content.encode(encoding)),
            appended=append,
        )


class FileListTool(BaseTool):
    """List entries in a directory.

    Parameters:
        path: Directory path.
        recursive: If ``True``, list recursively.
        max_depth: Maximum recursion depth (only when recursive=True).
        pattern: Glob pattern to filter entries (e.g. ``*.py``).
    """

    name = "file_list"
    description = "List files and directories at a given path."
    parameters = [
        ToolParameter(
            name="path",
            type="string",
            description="Directory path to list.",
        ),
        ToolParameter(
            name="recursive",
            type="boolean",
            description="List recursively.",
            required=False,
            default=False,
        ),
        ToolParameter(
            name="max_depth",
            type="integer",
            description="Maximum recursion depth.",
            required=False,
            default=5,
        ),
        ToolParameter(
            name="pattern",
            type="string",
            description="Glob pattern to filter results (e.g. '*.py').",
            required=False,
            default="*",
        ),
    ]

    def __init__(self, base_dir: Optional[str] = None):
        self._base_dir = base_dir

    def execute(self, **kwargs: Any) -> ToolResult:
        path_str: str = kwargs["path"]
        recursive: bool = kwargs.get("recursive", False)
        max_depth: int = kwargs.get("max_depth", 5)
        pattern: str = kwargs.get("pattern", "*")

        try:
            p = _safe_resolve(path_str, self._base_dir)
        except ValueError as exc:
            return ToolResult.fail(error=str(exc))

        if not p.exists():
            return ToolResult.fail(error=f"Directory not found: '{p}'")
        if not p.is_dir():
            return ToolResult.fail(error=f"Not a directory: '{p}'")

        entries: List[Dict[str, Any]] = []
        try:
            if recursive:
                for child in sorted(p.rglob(pattern)):
                    rel = child.relative_to(p)
                    depth = len(rel.parts) - 1
                    if depth > max_depth:
                        continue
                    st = child.stat()
                    entries.append(
                        FileInfo(
                            name=child.name,
                            path=str(child),
                            is_dir=child.is_dir(),
                            size=st.st_size,
                            modified=st.st_mtime,
                        ).to_dict()
                    )
            else:
                for child in sorted(p.glob(pattern)):
                    st = child.stat()
                    entries.append(
                        FileInfo(
                            name=child.name,
                            path=str(child),
                            is_dir=child.is_dir(),
                            size=st.st_size,
                            modified=st.st_mtime,
                        ).to_dict()
                    )
        except OSError as exc:
            logger.exception("Failed to list directory %s", p)
            return ToolResult.fail(error=f"List error: {exc}")

        return ToolResult.ok(
            content=entries,
            path=str(p),
            entry_count=len(entries),
        )
