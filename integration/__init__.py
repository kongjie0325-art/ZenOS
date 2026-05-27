"""Integration layer - Wires all subsystems together."""

from zenos.integration.memory_bridge import MemoryBridge
from zenos.integration.event_wiring import EventWiring

__all__ = ['MemoryBridge', 'EventWiring']
