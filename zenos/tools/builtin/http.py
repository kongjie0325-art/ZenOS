"""Built-in tool: HTTPTool.

Performs HTTP requests (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS)
with configurable headers, query parameters, body, and timeout.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Union

from zenos.tools.base import BaseTool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class HTTPTool(BaseTool):
    """Make an HTTP request and return the response.

    Parameters:
        url: The target URL.
        method: HTTP method (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS).
        headers: Request headers as key-value pairs.
        params: Query-string parameters.
        body: Request body (string or JSON-serialisable dict).
        json_body: If ``True``, send *body* as JSON with Content-Type.
        timeout: Request timeout in seconds.
        follow_redirects: Whether to follow HTTP redirects.
    """

    name = "http"
    description = (
        "Perform an HTTP request. Supports GET, POST, PUT, PATCH, DELETE, "
        "HEAD, and OPTIONS methods with custom headers, query parameters, "
        "and body."
    )
    parameters = [
        ToolParameter(
            name="url",
            type="string",
            description="Target URL for the request.",
        ),
        ToolParameter(
            name="method",
            type="string",
            description="HTTP method.",
            required=False,
            default="GET",
            enum=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        ),
        ToolParameter(
            name="headers",
            type="object",
            description="Request headers as key-value pairs.",
            required=False,
            default=None,
        ),
        ToolParameter(
            name="params",
            type="object",
            description="Query-string parameters.",
            required=False,
            default=None,
        ),
        ToolParameter(
            name="body",
            type="string",
            description="Request body (raw string).",
            required=False,
            default=None,
        ),
        ToolParameter(
            name="json_body",
            type="boolean",
            description="If true, send body as JSON with application/json Content-Type.",
            required=False,
            default=False,
        ),
        ToolParameter(
            name="timeout",
            type="integer",
            description="Timeout in seconds.",
            required=False,
            default=30,
        ),
        ToolParameter(
            name="follow_redirects",
            type="boolean",
            description="Follow HTTP redirects.",
            required=False,
            default=True,
        ),
    ]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, **kwargs: Any) -> ToolResult:
        url: str = kwargs["url"]
        method: str = kwargs.get("method", "GET").upper()
        headers: Optional[Dict[str, str]] = kwargs.get("headers")
        params: Optional[Dict[str, str]] = kwargs.get("params")
        body: Optional[Union[str, Dict[str, Any]]] = kwargs.get("body")
        json_body: bool = kwargs.get("json_body", False)
        timeout: int = kwargs.get("timeout", 30)
        follow_redirects: bool = kwargs.get("follow_redirects", True)

        # Append query parameters.
        if params:
            parsed = urllib.parse.urlparse(url)
            existing: Dict[str, List[str]] = urllib.parse.parse_qs(parsed.query)
            for k, v in params.items():
                existing[k] = [v]
            rebuilt = parsed._replace(
                query=urllib.parse.urlencode(existing, doseq=True)
            )
            url = urllib.parse.urlunparse(rebuilt)

        # Prepare body data.
        data: Optional[bytes] = None
        if body is not None:
            if json_body:
                if isinstance(body, dict):
                    data = json.dumps(body).encode("utf-8")
                else:
                    data = str(body).encode("utf-8")
                headers = headers or {}
                headers.setdefault("Content-Type", "application/json")
            else:
                data = body.encode("utf-8") if isinstance(body, str) else str(body).encode("utf-8")

        # Build request.
        req = urllib.request.Request(url, data=data, method=method)
        if headers:
            for key, value in headers.items():
                req.add_header(key, value)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_body = resp.read()
                status = resp.status
                resp_headers = dict(resp.getheaders())
        except urllib.error.HTTPError as exc:
            resp_body = exc.read()
            status = exc.code
            resp_headers = dict(exc.headers.items()) if exc.headers else {}
            logger.warning("HTTP %s %s returned %d", method, url, status)
        except urllib.error.URLError as exc:
            logger.exception("HTTP request failed")
            return ToolResult.fail(
                error=f"Request failed: {exc.reason}",
                url=url,
                method=method,
            )
        except OSError as exc:
            logger.exception("HTTP request error")
            return ToolResult.fail(
                error=f"Request error: {exc}",
                url=url,
                method=method,
            )

        # Try to decode body as text.
        try:
            content = resp_body.decode("utf-8")
            is_text = True
        except UnicodeDecodeError:
            content = resp_body.hex()
            is_text = False

        response: Dict[str, Any] = {
            "status": status,
            "headers": resp_headers,
            "body": content,
            "is_text": is_text,
            "url": url,
            "method": method,
        }

        success = 200 <= status < 400
        if success:
            return ToolResult.ok(content=response)
        return ToolResult.fail(
            error=f"HTTP {status}",
            **response,
        )
