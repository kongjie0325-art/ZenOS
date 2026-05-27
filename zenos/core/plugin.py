"""Plugin System - Extensible plugin architecture.

Supports lifecycle hooks, dependency injection, hot-loading,
and plugin isolation.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class PluginType(Enum):
    TOOL = "tool"
    MEMORY = "memory"
    AGENT = "agent"
    MIDDLEWARE = "middleware"
    OBSERVABILITY = "observability"
    CUSTOM = "custom"


@dataclass
class PluginInfo:
    name: str
    version: str
    description: str
    plugin_type: PluginType
    author: str = ""
    dependencies: List[str] = field(default_factory=list)
    entry_point: str = ""          # module.path:ClassName
    config: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


class Plugin(ABC):
    """Base class for all plugins."""

    info: PluginInfo

    @abstractmethod
    async def initialize(self, config: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        ...

    async def health_check(self) -> bool:
        return True

    def get_config_schema(self) -> Dict[str, Any]:
        return {}


class PluginManager:
    """Manages plugin lifecycle: discovery, loading, initialization."""

    def __init__(self, plugin_dirs: Optional[List[str]] = None):
        self._plugins: Dict[str, Plugin] = {}
        self._info: Dict[str, PluginInfo] = {}
        self._hooks: Dict[str, List[Callable]] = {}
        self._plugin_dirs = plugin_dirs or []
        self._initialized = False

    def register(self, plugin: Plugin) -> None:
        name = plugin.info.name
        if name in self._plugins:
            logger.warning(f"Plugin {name} already registered, replacing")
        self._plugins[name] = plugin
        self._info[name] = plugin.info
        logger.info(f"Registered plugin: {name} v{plugin.info.version}")

    def unregister(self, name: str) -> Optional[Plugin]:
        plugin = self._plugins.pop(name, None)
        self._info.pop(name, None)
        if plugin:
            logger.info(f"Unregistered plugin: {name}")
        return plugin

    async def load_from_directory(self, directory: str) -> int:
        """Load all plugins from a directory. Returns count loaded."""
        loaded = 0
        p = Path(directory)
        if not p.exists():
            logger.warning(f"Plugin directory not found: {directory}")
            return 0
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))

        for init_file in p.glob("*/__init__.py"):
            plugin_dir = init_file.parent
            manifest_file = plugin_dir / "plugin.yaml"
            if manifest_file.exists():
                try:
                    info = self._load_manifest(manifest_file)
                    if not info.enabled:
                        continue
                    module_path = f"{plugin_dir.name}.{info.entry_point}"
                    mod = importlib.import_module(module_path.rsplit(':', 1)[0])
                    class_name = info.entry_point.rsplit(':', 1)[-1] if ':' in info.entry_point else None
                    if class_name:
                        plugin_class = getattr(mod, class_name)
                    else:
                        # Find first Plugin subclass
                        plugin_class = None
                        for attr_name in dir(mod):
                            attr = getattr(mod, attr_name)
                            if isinstance(attr, type) and issubclass(attr, Plugin) and attr is not Plugin:
                                plugin_class = attr
                                break
                    if plugin_class:
                        plugin = plugin_class()
                        self.register(plugin)
                        loaded += 1
                except Exception as e:
                    logger.error(f"Failed to load plugin from {plugin_dir}: {e}")
        return loaded

    async def initialize_all(self, configs: Optional[Dict[str, Dict]] = None) -> None:
        configs = configs or {}
        for name, plugin in self._plugins.items():
            if not plugin.info.enabled:
                continue
            try:
                await plugin.initialize(configs.get(name, plugin.info.config))
                logger.info(f"Initialized plugin: {name}")
            except Exception as e:
                logger.error(f"Failed to initialize plugin {name}: {e}")
        self._initialized = True

    async def shutdown_all(self) -> None:
        for name, plugin in self._plugins.items():
            try:
                await plugin.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down plugin {name}: {e}")
        self._initialized = False

    def register_hook(self, event: str, handler: Callable) -> None:
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(handler)

    async def execute_hooks(self, event: str, **kwargs) -> List[Any]:
        results = []
        for handler in self._hooks.get(event, []):
            try:
                if hasattr(handler, '__await__') or callable(getattr(handler, '__call__', None)):
                    import asyncio
                    if asyncio.iscoroutinefunction(handler):
                        result = await handler(**kwargs)
                    else:
                        result = handler(**kwargs)
                else:
                    result = handler(**kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"Hook error for {event}: {e}")
        return results

    def get(self, name: str) -> Optional[Plugin]:
        return self._plugins.get(name)

    def get_by_type(self, plugin_type: PluginType) -> List[Plugin]:
        return [p for p in self._plugins.values() if p.info.plugin_type == plugin_type]

    def list_all(self) -> List[PluginInfo]:
        return list(self._info.values())

    def _load_manifest(self, path: Path) -> PluginInfo:
        import yaml
        data = yaml.safe_load(path.read_text())
        return PluginInfo(
            name=data['name'],
            version=data.get('version', '0.1.0'),
            description=data.get('description', ''),
            plugin_type=PluginType(data.get('type', 'custom')),
            author=data.get('author', ''),
            dependencies=data.get('dependencies', []),
            entry_point=data.get('entry_point', ''),
            config=data.get('config', {}),
            enabled=data.get('enabled', True),
        )
