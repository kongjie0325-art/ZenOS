"""JWT authentication middleware for ZenOS API."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from http import HTTPStatus
import base64


@dataclass
class AuthContext:
    """Authenticated user context extracted from a JWT."""

    user_id: str
    roles: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    issued_at: float = 0.0
    expires_at: float = 0.0
    claims: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if the token has expired."""
        return time.time() > self.expires_at

    def has_scope(self, scope: str) -> bool:
        """Check whether the context includes a given scope."""
        return scope in self.scopes

    def has_role(self, role: str) -> bool:
        """Check whether the context includes a given role."""
        return role in self.roles


@dataclass
class AuthResult:
    """Result of an authentication attempt."""

    authenticated: bool
    context: Optional[AuthContext] = None
    error: Optional[str] = None
    status_code: int = HTTPStatus.OK


class AuthMiddleware:
    """JWT-based authentication middleware.

    Validates Bearer tokens from the Authorization header, decodes
    the JWT payload, and produces an ``AuthContext`` for downstream
    handlers.

    This is a pure-Python implementation that does not depend on
    FastAPI or any external JWT library. In production, consider
    using ``PyJWT`` or ``python-jose`` for full spec compliance.
    """

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        issuer: str = "zenos",
        audience: Optional[str] = None,
        leeway_seconds: float = 30.0,
    ) -> None:
        """Initialize the auth middleware.

        Args:
            secret_key: HMAC secret used to verify token signatures.
            algorithm: JWT signing algorithm (only HS256 supported).
            issuer: Expected ``iss`` claim value.
            audience: Optional ``aud`` claim to validate.
            leeway_seconds: Clock-skew tolerance in seconds.
        """
        self._secret = secret_key.encode("utf-8")
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._leeway = leeway_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def authenticate(self, authorization_header: Optional[str]) -> AuthResult:
        """Authenticate a request from its Authorization header.

        Args:
            authorization_header: The raw ``Authorization`` header value.

        Returns:
            AuthResult with context on success or error details on failure.
        """
        if not authorization_header:
            return AuthResult(
                authenticated=False,
                error="Missing Authorization header",
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        scheme, _, token = authorization_header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return AuthResult(
                authenticated=False,
                error="Invalid authorization scheme; expected Bearer",
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        return self._verify_token(token)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _verify_token(self, token: str) -> AuthResult:
        """Decode and verify a JWT string."""
        parts = token.split(".")
        if len(parts) != 3:
            return AuthResult(
                authenticated=False,
                error="Invalid token format",
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        header_b64, payload_b64, signature_b64 = parts

        # Verify signature
        expected_sig = self._sign(f"{header_b64}.{payload_b64}")
        if not hmac.compare_digest(expected_sig, signature_b64):
            return AuthResult(
                authenticated=False,
                error="Invalid token signature",
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        # Decode payload
        try:
            payload = self._b64_decode_json(payload_b64)
        except Exception:
            return AuthResult(
                authenticated=False,
                error="Malformed token payload",
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        # Validate claims
        now = time.time()
        iss = payload.get("iss")
        if iss and iss != self._issuer:
            return AuthResult(
                authenticated=False,
                error="Invalid token issuer",
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        aud = payload.get("aud")
        if self._audience and aud and aud != self._audience:
            return AuthResult(
                authenticated=False,
                error="Invalid token audience",
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        exp = payload.get("exp", 0)
        if exp and now > exp + self._leeway:
            return AuthResult(
                authenticated=False,
                error="Token has expired",
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        nbf = payload.get("nbf", 0)
        if nbf and now < nbf - self._leeway:
            return AuthResult(
                authenticated=False,
                error="Token not yet valid",
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        context = AuthContext(
            user_id=payload.get("sub", "anonymous"),
            roles=payload.get("roles", []),
            scopes=payload.get("scopes", []),
            issued_at=payload.get("iat", 0),
            expires_at=exp,
            claims=payload,
        )
        return AuthResult(authenticated=True, context=context)

    def _sign(self, data: str) -> str:
        """Produce an HMAC-SHA256 signature, base64url-encoded."""
        mac = hmac.new(self._secret, data.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")

    @staticmethod
    def _b64_decode_json(data: str) -> dict[str, Any]:
        """Decode a base64url-encoded JSON object."""
        # Add padding as needed
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        raw = base64.urlsafe_b64decode(data)
        return json.loads(raw)
