"""Context Management - Conversation and execution context.

Manages the lifecycle of conversation context including message history,
token budgeting, automatic summarization, and context window optimization.
"""

from __future__ import annotations

import time
import uuid
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Message:
    role: str          # system | user | assistant | tool
    content: str
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    tokens: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Context:
    """A single conversation/execution context."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    session_id: str = ""
    messages: List[Message] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    token_budget: int = 128000
    token_used: int = 0
    is_compressed: bool = False
    parent_id: Optional[str] = None   # for branched conversations
    tags: List[str] = field(default_factory=list)

    def add_message(self, role: str, content: str, **kwargs) -> Message:
        msg = Message(role=role, content=content, **kwargs)
        msg.tokens = self._estimate_tokens(content)
        self.messages.append(msg)
        self.token_used += msg.tokens
        self.updated_at = time.time()
        return msg

    def get_messages(self, limit: Optional[int] = None, roles: Optional[List[str]] = None) -> List[Message]:
        msgs = self.messages
        if roles:
            msgs = [m for m in msgs if m.role in roles]
        if limit:
            msgs = msgs[-limit:]
        return msgs

    def clear(self):
        self.messages.clear()
        self.token_used = 0
        self.updated_at = time.time()

    def compress(self, keep_last_n: int = 10) -> str:
        """Compress older messages into a summary. Returns summary text."""
        if len(self.messages) <= keep_last_n:
            return ""
        to_compress = self.messages[:-keep_last_n]
        summary_parts = []
        for msg in to_compress:
            content = msg.content[:200] if len(msg.content) > 200 else msg.content
            summary_parts.append(f"[{msg.role}] {content}")
        summary = "\n".join(summary_parts)
        self.messages = self.messages[-keep_last_n:]
        self.is_compressed = True
        self._recalculate_tokens()
        logger.info(f"Context {self.id}: compressed {len(to_compress)} messages")
        return summary

    def should_compress(self, threshold: float = 0.8) -> bool:
        if self.token_budget <= 0:
            return False
        return (self.token_used / self.token_budget) >= threshold

    def _recalculate_tokens(self):
        self.token_used = sum(m.tokens for m in self.messages)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'session_id': self.session_id,
            'message_count': len(self.messages),
            'token_used': self.token_used,
            'token_budget': self.token_budget,
            'is_compressed': self.is_compressed,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'tags': self.tags,
        }


class ContextManager:
    """Manages multiple contexts with LRU eviction."""

    def __init__(self, max_contexts: int = 100):
        self._contexts: Dict[str, Context] = {}
        self._max = max_contexts
        self._access_order: List[str] = []

    def create(self, session_id: str = "", token_budget: int = 128000,
               tags: Optional[List[str]] = None, **kwargs) -> Context:
        ctx = Context(session_id=session_id, token_budget=token_budget,
                      tags=tags or [], **kwargs)
        self._contexts[ctx.id] = ctx
        self._access_order.append(ctx.id)
        self._evict_if_needed()
        return ctx

    def get(self, context_id: str) -> Optional[Context]:
        if context_id in self._contexts:
            # Move to end (most recently used)
            if context_id in self._access_order:
                self._access_order.remove(context_id)
            self._access_order.append(context_id)
            return self._contexts[context_id]
        return None

    def get_or_create(self, context_id: str, **kwargs) -> Context:
        ctx = self.get(context_id)
        if ctx is None:
            ctx = self.create(**kwargs)
        return ctx

    def delete(self, context_id: str) -> bool:
        if context_id in self._contexts:
            del self._contexts[context_id]
            self._access_order.remove(context_id)
            return True
        return False

    def list_all(self) -> List[Context]:
        return list(self._contexts.values())

    def get_by_session(self, session_id: str) -> List[Context]:
        return [c for c in self._contexts.values() if c.session_id == session_id]

    def get_by_tag(self, tag: str) -> List[Context]:
        return [c for c in self._contexts.values() if tag in c.tags]

    def _evict_if_needed(self):
        while len(self._contexts) > self._max:
            oldest_id = self._access_order.pop(0)
            if oldest_id in self._contexts:
                del self._contexts[oldest_id]
                logger.debug(f"Evicted context {oldest_id}")

    def stats(self) -> Dict[str, Any]:
        total_tokens = sum(c.token_used for c in self._contexts.values())
        return {
            'total_contexts': len(self._contexts),
            'total_tokens': total_tokens,
            'compressed': sum(1 for c in self._contexts.values() if c.is_compressed),
        }
