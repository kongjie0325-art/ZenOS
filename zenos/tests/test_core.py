"""Tests for ZenOS core modules."""

import pytest
import asyncio
import time
import tempfile
import os


class TestConfig:
    """Test configuration management."""

    def test_default_config(self):
        from zenos.core.config import Config
        config = Config()
        assert config.server.host == "0.0.0.0"
        assert config.server.port == 8000
        assert config.memory.backend == "local"
        assert config.agent.model == "gpt-4o"

    def test_config_from_dict(self):
        from zenos.core.config import Config
        config = Config.from_dict({
            'server': {'port': 9000},
            'memory': {'backend': 'redis'},
        })
        assert config.server.port == 9000
        assert config.memory.backend == "redis"

    def test_config_get_set(self):
        from zenos.core.config import Config
        config = Config()
        assert config.get('server.port') == 8000
        config.set('server.port', 9090)
        assert config.server.port == 9090

    def test_config_save_load(self):
        from zenos.core.config import Config
        config = Config()
        config.server.port = 7777
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            config.save(path)
            loaded = Config.from_file(path)
            assert loaded.server.port == 7777
        finally:
            os.unlink(path)

    def test_config_change_listener(self):
        from zenos.core.config import Config
        config = Config()
        changes = []
        config.on_change(lambda k, v: changes.append((k, v)))
        config.set('server.port', 5555)
        assert len(changes) == 1
        assert changes[0] == ('server.port', 5555)


class TestEventBus:
    """Test event bus functionality."""

    @pytest.mark.asyncio
    async def test_subscribe_publish(self):
        from zenos.core.events import EventBus, Event, EventType
        bus = EventBus()
        await bus.start()
        received = []
        bus.subscribe(EventType.AGENT_START, lambda e: received.append(e))
        await bus.publish(Event(type=EventType.AGENT_START, data={'test': 1}))
        await asyncio.sleep(0.2)
        assert len(received) == 1
        assert received[0].data['test'] == 1
        await bus.stop()

    @pytest.mark.asyncio
    async def test_publish_and_wait(self):
        from zenos.core.events import EventBus, Event, EventType
        bus = EventBus()
        results = []

        def handler(e):
            results.append(e.data)
            return "ok"

        bus.subscribe(EventType.TOOL_CALL, handler)
        res = await bus.publish_and_wait(Event(type=EventType.TOOL_CALL, data={'cmd': 'test'}))
        assert len(res) == 1
        assert res[0] == "ok"

    def test_event_history(self):
        from zenos.core.events import EventBus, Event, EventType
        bus = EventBus()
        # Manually add to history
        for i in range(5):
            bus._history.append(Event(type=EventType.AGENT_THINK, data={'i': i}))
        history = bus.get_history(limit=3)
        assert len(history) == 3

    def test_event_with_priority(self):
        from zenos.core.events import Event, EventType
        e = Event(type=EventType.SYSTEM_ERROR, data={}, priority=10)
        assert e.priority == 10
        assert e.id != ""


class TestContext:
    """Test context management."""

    def test_create_context(self):
        from zenos.core.context import ContextManager
        cm = ContextManager()
        ctx = cm.create(session_id="sess-1", token_budget=64000)
        assert ctx.session_id == "sess-1"
        assert ctx.token_budget == 64000

    def test_add_messages(self):
        from zenos.core.context import Context, ContextManager
        ctx = Context()
        ctx.add_message("system", "You are a helpful assistant.")
        ctx.add_message("user", "Hello!")
        assert len(ctx.messages) == 2
        assert ctx.messages[0].role == "system"
        assert ctx.token_used > 0

    def test_context_compression(self):
        from zenos.core.context import Context
        ctx = Context(token_budget=1000)
        for i in range(20):
            ctx.add_message("user", f"Message {i} " * 10)
        summary = ctx.compress(keep_last_n=5)
        assert len(ctx.messages) == 5
        assert ctx.is_compressed

    def test_should_compress(self):
        from zenos.core.context import Context
        ctx = Context(token_budget=100)
        ctx.token_used = 85
        assert ctx.should_compress(threshold=0.8)
        assert not ctx.should_compress(threshold=0.9)

    def test_context_manager_lru(self):
        from zenos.core.context import ContextManager
        cm = ContextManager(max_contexts=3)
        c1 = cm.create()
        c2 = cm.create()
        c3 = cm.create()
        c4 = cm.create()
        assert len(cm.list_all()) == 3
        assert cm.get(c1.id) is None  # evicted

    def test_context_by_session(self):
        from zenos.core.context import ContextManager
        cm = ContextManager()
        cm.create(session_id="s1")
        cm.create(session_id="s1")
        cm.create(session_id="s2")
        assert len(cm.get_by_session("s1")) == 2
        assert len(cm.get_by_session("s2")) == 1


class TestRegistry:
    """Test service registry."""

    def test_register_get(self):
        from zenos.core.registry import Registry
        reg = Registry()
        reg.register("service_a", {"key": "value"})
        assert reg.get("service_a") == {"key": "value"}

    def test_factory(self):
        from zenos.core.registry import Registry
        reg = Registry()
        reg.register_factory("counter", lambda: {"count": 0})
        result = reg.get("counter")
        assert result == {"count": 0}

    def test_singleton(self):
        from zenos.core.registry import Registry
        reg = Registry()
        reg.register_factory("obj", lambda: {"id": id(object())}, singleton=True)
        a = reg.get("obj")
        b = reg.get("obj")
        assert a is b

    def test_non_singleton(self):
        from zenos.core.registry import Registry
        reg = Registry()
        reg.register_factory("obj", lambda: {"id": id(object())}, singleton=False)
        a = reg.get("obj")
        b = reg.get("obj")
        assert a is not b

    def test_missing_service(self):
        from zenos.core.registry import Registry
        reg = Registry()
        with pytest.raises(KeyError):
            reg.get("nonexistent")

    def test_resolve_by_type(self):
        from zenos.core.registry import Registry
        reg = Registry()
        reg.register("my_dict", {"key": "val"})
        result = reg.resolve(dict)
        assert result == {"key": "val"}


class TestStateManager:
    """Test state machine."""

    def test_initial_state(self):
        from zenos.core.state import StateManager, SystemState
        sm = StateManager()
        assert sm.state == SystemState.INITIALIZING

    def test_valid_transition(self):
        from zenos.core.state import StateManager, SystemState
        sm = StateManager()
        assert sm.transition(SystemState.READY) is True
        assert sm.state == SystemState.READY

    def test_invalid_transition(self):
        from zenos.core.state import StateManager, SystemState
        sm = StateManager()
        assert sm.transition(SystemState.RUNNING) is False
        assert sm.state == SystemState.INITIALIZING

    def test_transition_listener(self):
        from zenos.core.state import StateManager, SystemState
        sm = StateManager()
        transitions = []
        sm.on_transition(lambda old, new, meta: transitions.append((old, new)))
        sm.transition(SystemState.READY)
        sm.transition(SystemState.RUNNING)
        assert len(transitions) == 2

    def test_snapshot(self):
        from zenos.core.state import StateManager, SystemState
        sm = StateManager()
        sm.set_data("key", "value")
        snap = sm.snapshot()
        assert snap.state == SystemState.INITIALIZING
        assert snap.metadata.get("key") == "value"

    def test_save_load_snapshot(self):
        from zenos.core.state import StateManager, SystemState
        sm = StateManager()
        sm.transition(SystemState.READY)
        sm.set_data("test", 42)
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            sm.save_snapshot(path)
            sm2 = StateManager()
            sm2.load_snapshot(path)
            assert sm2.state == SystemState.READY
            assert sm2.get_data("test") == 42
        finally:
            os.unlink(path)


class TestPluginManager:
    """Test plugin system."""

    def test_register_plugin(self):
        from zenos.core.plugin import PluginManager, Plugin, PluginType, PluginInfo

        class MyPlugin(Plugin):
            info = PluginInfo(name="test", version="0.1.0", description="Test",
                               plugin_type=PluginType.TOOL, entry_point="")
            async def initialize(self, config): pass
            async def shutdown(self): pass

        pm = PluginManager()
        pm.register(MyPlugin())
        assert pm.get("test") is not None

    def test_get_by_type(self):
        from zenos.core.plugin import PluginManager, Plugin, PluginType, PluginInfo

        class ToolPlugin(Plugin):
            info = PluginInfo(name="tool1", version="0.1.0", description="",
                               plugin_type=PluginType.TOOL, entry_point="")
            async def initialize(self, config): pass
            async def shutdown(self): pass

        pm = PluginManager()
        pm.register(ToolPlugin())
        tools = pm.get_by_type(PluginType.TOOL)
        assert len(tools) == 1

    def test_hooks(self):
        from zenos.core.plugin import PluginManager
        pm = PluginManager()
        results = []
        pm.register_hook("test_event", lambda **kw: results.append(kw))
        # Can't easily test async hooks in sync test, but registration works
        assert "test_event" in pm._hooks

    def test_list_plugins(self):
        from zenos.core.plugin import PluginManager, Plugin, PluginType, PluginInfo

        class P(Plugin):
            info = PluginInfo(name="p1", version="1.0", description="Test",
                               plugin_type=PluginType.CUSTOM, entry_point="")
            async def initialize(self, config): pass
            async def shutdown(self): pass

        pm = PluginManager()
        pm.register(P())
        infos = pm.list_all()
        assert len(infos) == 1
        assert infos[0].name == "p1"
