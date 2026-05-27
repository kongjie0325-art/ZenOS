"""ZenOS Configuration Management.

Supports YAML/JSON config files, environment variable overrides,
and runtime hot-reload via file watcher.
"""

from __future__ import annotations

import os
import json
import threading
from pathlib import Path
from typing import Any, Optional, Dict
from dataclasses import dataclass, field

import yaml


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4
    debug: bool = False
    cors_origins: list = field(default_factory=lambda: ["*"])


@dataclass
class MemoryConfig:
    backend: str = "local"          # local | redis | qdrant
    max_working_memory: int = 100
    max_episodic_memory: int = 1000
    max_semantic_memory: int = 5000
    compression_threshold: float = 0.8
    vector_dimension: int = 1536
    redis_url: str = "redis://localhost:6379"
    qdrant_url: str = "http://localhost:6333"
    auto_compress: bool = True
    cross_session_persistence: bool = True


@dataclass
class AgentConfig:
    max_iterations: int = 50
    max_tool_calls: int = 100
    timeout_seconds: int = 300
    enable_planning: bool = True
    enable_reflection: bool = True
    enable_self_healing: bool = True
    adaptive_routing: bool = True
    model: str = "gpt-4o"
    fallback_models: list = field(default_factory=lambda: ["gpt-4o-mini", "claude-3-5-sonnet"])


@dataclass
class ObservabilityConfig:
    enable_metrics: bool = True
    enable_tracing: bool = True
    enable_alerting: bool = True
    metrics_port: int = 9090
    tracing_endpoint: str = "http://localhost:4317"
    log_level: str = "INFO"
    alert_channels: list = field(default_factory=list)


@dataclass
class SecurityConfig:
    enable_auth: bool = True
    jwt_secret: str = "change-me-in-production"
    jwt_expiry_hours: int = 24
    rate_limit_per_minute: int = 60
    enable_audit_log: bool = True
    allowed_hosts: list = field(default_factory=lambda: ["*"])


@dataclass
class InfrastructureConfig:
    enable_caching: bool = True
    cache_ttl_seconds: int = 300
    cache_max_size: int = 10000
    enable_scheduling: bool = True
    enable_messaging: bool = True
    message_queue_url: str = "redis://localhost:6379/1"
    predictive_scheduling: bool = True


class Config:
    """Central configuration manager with hot-reload support."""

    _instance: Optional['Config'] = None
    _lock = threading.Lock()

    def __init__(
        self,
        server: Optional[ServerConfig] = None,
        memory: Optional[MemoryConfig] = None,
        agent: Optional[AgentConfig] = None,
        observability: Optional[ObservabilityConfig] = None,
        security: Optional[SecurityConfig] = None,
        infrastructure: Optional[InfrastructureConfig] = None,
        raw: Optional[Dict[str, Any]] = None,
    ):
        self.server = server or ServerConfig()
        self.memory = memory or MemoryConfig()
        self.agent = agent or AgentConfig()
        self.observability = observability or ObservabilityConfig()
        self.security = security or SecurityConfig()
        self.infrastructure = infrastructure or InfrastructureConfig()
        self._raw = raw or {}
        self._listeners: list = []
        self._watcher_thread: Optional[threading.Thread] = None

    @classmethod
    def instance(cls) -> 'Config':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def from_file(cls, path: str) -> 'Config':
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        text = p.read_text()
        if p.suffix in ('.yaml', '.yml'):
            data = yaml.safe_load(text)
        elif p.suffix == '.json':
            data = json.loads(text)
        else:
            raise ValueError(f"Unsupported config format: {p.suffix}")
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Config':
        server = ServerConfig(**{k: v for k, v in data.get('server', {}).items()
                                  if k in ServerConfig.__dataclass_fields__})
        memory = MemoryConfig(**{k: v for k, v in data.get('memory', {}).items()
                                  if k in MemoryConfig.__dataclass_fields__})
        agent = AgentConfig(**{k: v for k, v in data.get('agent', {}).items()
                                if k in AgentConfig.__dataclass_fields__})
        obs = ObservabilityConfig(**{k: v for k, v in data.get('observability', {}).items()
                                      if k in ObservabilityConfig.__dataclass_fields__})
        sec = SecurityConfig(**{k: v for k, v in data.get('security', {}).items()
                                 if k in SecurityConfig.__dataclass_fields__})
        infra = InfrastructureConfig(**{k: v for k, v in data.get('infrastructure', {}).items()
                                         if k in InfrastructureConfig.__dataclass_fields__})
        return cls(server=server, memory=memory, agent=agent,
                   observability=obs, security=sec, infrastructure=infra,
                   raw=data)

    @classmethod
    def from_env(cls) -> 'Config':
        """Build config from environment variables (ZENOS_ prefix)."""
        def env_or(key: str, default: Any, type_fn=str) -> Any:
            val = os.environ.get(f"ZENOS_{key.upper()}")
            return type_fn(val) if val is not None else default

        server = ServerConfig(
            host=env_or("server_host", "0.0.0.0"),
            port=env_or("server_port", 8000, int),
        )
        memory = MemoryConfig(
            backend=env_or("memory_backend", "local"),
            max_working_memory=env_or("memory_max_working", 100, int),
        )
        agent = AgentConfig(
            model=env_or("agent_model", "gpt-4o"),
            max_iterations=env_or("agent_max_iterations", 50, int),
        )
        return cls(server=server, memory=memory, agent=agent)

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return {
            'server': asdict(self.server),
            'memory': asdict(self.memory),
            'agent': asdict(self.agent),
            'observability': asdict(self.observability),
            'security': asdict(self.security),
            'infrastructure': asdict(self.infrastructure),
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Dot-notation config access: config.get('server.port')"""
        parts = key.split('.')
        obj = self
        for part in parts:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            elif isinstance(obj, dict):
                obj = obj.get(part, default)
            else:
                return default
        return obj

    def set(self, key: str, value: Any) -> None:
        parts = key.split('.')
        obj = self
        for part in parts[:-1]:
            obj = getattr(obj, part)
        setattr(obj, parts[-1], value)
        for listener in self._listeners:
            listener(key, value)

    def on_change(self, listener) -> None:
        self._listeners.append(listener)

    def save(self, path: str) -> None:
        p = Path(path)
        data = self.to_dict()
        if p.suffix == '.json':
            p.write_text(json.dumps(data, indent=2))
        else:
            p.write_text(yaml.dump(data, default_flow_style=False))


def get_config() -> Config:
    return Config.instance()
