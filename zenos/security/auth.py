"""Authentication Manager - JWT-based auth with role support."""

from __future__ import annotations

import hmac
import hashlib
import base64
import json
import time
import logging
import secrets
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class JWTConfig:
    secret: str = "change-me-in-production"
    algorithm: str = "HS256"
    expiry_seconds: int = 86400  # 24 hours
    issuer: str = "zenos"


@dataclass
class User:
    id: str
    username: str
    roles: List[str] = field(default_factory=lambda: ["user"])
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class AuthManager:
    """JWT authentication manager (pure Python, no PyJWT dependency)."""

    def __init__(self, config: Optional[JWTConfig] = None):
        self._config = config or JWTConfig()
        self._users: Dict[str, User] = {}
        self._revoked_tokens: set = set()

    def create_user(self, username: str, roles: Optional[List[str]] = None,
                    user_id: Optional[str] = None, **metadata) -> User:
        uid = user_id or secrets.token_hex(8)
        user = User(id=uid, username=username, roles=roles or ["user"], metadata=metadata)
        self._users[uid] = user
        logger.info(f"Created user: {username} ({uid})")
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)

    def authenticate(self, token: str) -> Optional[User]:
        """Validate token and return user."""
        payload = self.decode_token(token)
        if not payload:
            return None
        return self._users.get(payload.get('sub'))

    def create_token(self, user: User, extra_claims: Optional[Dict[str, Any]] = None) -> str:
        now = time.time()
        header = {'alg': self._config.algorithm, 'typ': 'JWT'}
        payload = {
            'sub': user.id,
            'username': user.username,
            'roles': user.roles,
            'iat': now,
            'exp': now + self._config.expiry_seconds,
            'iss': self._config.issuer,
            'jti': secrets.token_hex(16),
        }
        if extra_claims:
            payload.update(extra_claims)
        return self._encode(header, payload)

    def decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Decode and validate a JWT token."""
        try:
            parts = token.split('.')
            if len(parts) != 3:
                return None
            header_b64, payload_b64, signature_b64 = parts
            # Verify signature
            expected_sig = self._sign(f"{header_b64}.{payload_b64}")
            if not hmac.compare_digest(signature_b64, expected_sig):
                logger.warning("Token signature mismatch")
                return None
            # Decode payload
            payload = json.loads(self._b64_decode(payload_b64))
            # Check expiration
            if payload.get('exp', 0) < time.time():
                logger.info("Token expired")
                return None
            # Check revoked
            if payload.get('jti') in self._revoked_tokens:
                logger.info("Token revoked")
                return None
            return payload
        except Exception as e:
            logger.error(f"Token decode error: {e}")
            return None

    def revoke_token(self, token: str) -> bool:
        payload = self.decode_token(token)
        if payload and 'jti' in payload:
            self._revoked_tokens.add(payload['jti'])
            return True
        return False

    def has_role(self, token: str, role: str) -> bool:
        payload = self.decode_token(token)
        if not payload:
            return False
        return role in payload.get('roles', [])

    def _encode(self, header: Dict, payload: Dict) -> str:
        h = self._b64_encode(json.dumps(header, separators=(',', ':')))
        p = self._b64_encode(json.dumps(payload, separators=(',', ':')))
        sig = self._sign(f"{h}.{p}")
        return f"{h}.{p}.{sig}"

    def _sign(self, data: str) -> str:
        sig = hmac.new(
            self._config.secret.encode(),
            data.encode(),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(sig).rstrip(b'=').decode()

    @staticmethod
    def _b64_encode(data: str) -> str:
        return base64.urlsafe_b64encode(data.encode()).rstrip(b'=').decode()

    @staticmethod
    def _b64_decode(data: str) -> str:
        padding = 4 - len(data) % 4
        if padding != 4:
            data += '=' * padding
        return base64.urlsafe_b64decode(data).decode()
