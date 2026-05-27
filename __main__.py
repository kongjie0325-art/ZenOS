"""ZenOS - AI Operating System entry point."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Optional

from core.events import Event, EventType
from core.state import SystemState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("zenos")


class ZenOS:
    """Main ZenOS system orchestrator."""

    def __init__(self, config_path: Optional[str] = None):
        from core.config import Config
        from core.events import EventBus
        from core.context import ContextManager
        from core.plugin import PluginManager
        from core.registry import Registry
        from core.state import StateManager

        if config_path:
            self.config = Config.from_file(config_path)
        else:
            self.config = Config()

        self.event_bus = EventBus()
        self.context_manager = ContextManager()
        self.plugin_manager = PluginManager()
        self.registry = Registry()
        self.state = StateManager()

        self.registry.register("config", self.config)
        self.registry.register("event_bus", self.event_bus)
        self.registry.register("context_manager", self.context_manager)
        self.registry.register("plugin_manager", self.plugin_manager)
        self.registry.register("state", self.state)
        self._running = False

    async def start(self) -> None:
        logger.info("Starting ZenOS v0.1.0...")
        self.state.transition(SystemState.READY)
        await self.event_bus.start()
        await self.plugin_manager.initialize_all()
        await self.event_bus.publish(Event(type=EventType.SYSTEM_STARTUP, data={'version': '0.1.0'}))
        self.state.transition(SystemState.RUNNING)
        self._running = True
        logger.info("ZenOS started successfully")

    async def stop(self) -> None:
        logger.info("Stopping ZenOS...")
        self.state.transition(SystemState.SHUTTING_DOWN)
        await self.event_bus.publish(Event(type=EventType.SYSTEM_SHUTDOWN, data={}))
        await self.plugin_manager.shutdown_all()
        await self.event_bus.stop()
        self.state.transition(SystemState.STOPPED)
        self._running = False
        logger.info("ZenOS stopped")

    async def run_forever(self) -> None:
        await self.start()
        try:
            while self._running:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await self.stop()

    def health(self) -> dict:
        return {
            'status': self.state.state.value,
            'version': '0.1.0',
            'contexts': self.context_manager.stats(),
            'events': self.event_bus.get_stats(),
            'plugins': len(self.plugin_manager.list_all()),
        }


async def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    zenos = ZenOS(config_path=config_path)
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(zenos.stop()))
    await zenos.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
