"""Registry - Service locator and dependency injection container."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


class Registry:
    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Callable] = {}
        self._singletons: set = set()

    def register(self, name: str, instance: Any, singleton: bool = True) -> None:
        self._services[name] = instance
        if singleton:
            self._singletons.add(name)
        logger.debug(f"Registered service: {name}")

    def register_factory(self, name: str, factory: Callable, singleton: bool = True) -> None:
        self._factories[name] = factory
        if singleton:
            self._singletons.add(name)
        logger.debug(f"Registered factory: {name}")

    def register_class(self, name: str, cls: Type[T], singleton: bool = True, **kwargs) -> None:
        def _factory():
            return cls(**kwargs)
        self.register_factory(name, _factory, singleton)

    def get(self, name: str) -> Any:
        if name in self._services:
            return self._services[name]
        if name in self._factories:
            instance = self._factories[name]()
            if name in self._singletons:
                self._services[name] = instance
            return instance
        raise KeyError(f"Service not found: {name}")

    def get_optional(self, name: str, default: Any = None) -> Any:
        try:
            return self.get(name)
        except KeyError:
            return default

    def has(self, name: str) -> bool:
        return name in self._services or name in self._factories

    def resolve(self, cls: Type[T]) -> T:
        for name, instance in self._services.items():
            if isinstance(instance, cls):
                return instance
        for name, factory in self._factories.items():
            try:
                instance = factory()
                if isinstance(instance, cls):
                    return instance
            except Exception:
                continue
        raise KeyError(f"No service of type {cls.__name__} registered")

    def remove(self, name: str) -> None:
        self._services.pop(name, None)
        self._factories.pop(name, None)
        self._singletons.discard(name)

    def clear(self) -> None:
        self._services.clear()
        self._factories.clear()
        self._singletons.clear()

    def list_services(self) -> list:
        return sorted(set(self._services.keys()) | set(self._factories.keys()))
