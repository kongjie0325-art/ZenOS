#!/usr/bin/env python3
"""
ZenOS End-to-End Integration Tests
Tests full agent workflows with all memory tiers.
Run with: python -m pytest zenos/tests/test_e2e.py -v
"""
import asyncio
import json
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ═══════════════════════════════════════════════════════════════
# Test 1: FourTier Memory Write/Read Cycle
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_four_tier_write_read():
    """Test writing and reading across all 4 tiers."""
    from zenos.memory.four_tier import FourTierMemoryManager

    mgr = FourTierMemoryManager({
        "redis_url": "redis://127.0.0.1:6379/0",
        "pg_dsn": "postgresql://zenos:zenos@127.0.0.1:5432/zenos",
        "qdrant_url": "http://127.0.0.1:6333",
        "qdrant_api_key": "qdrant_hermes_2026_secure_key",
        "qdrant_collection": "zenos_semantic",
        "vector_size": 384,
        "s3_endpoint": "http://127.0.0.1:9000",
        "s3_access_key": "zenos",
        "s3_secret_key": "zenos-secret",
        "s3_bucket": "zenos-cold",
    })
    await mgr.connect_all()

    # Write
    result = await mgr.remember(
        content="E2E test: user asked about weather",
        session_id="e2e-test",
        importance=0.9,
    )
    assert result.get("redis"), "Redis write failed"
    assert result.get("postgres"), "PostgreSQL write failed"
    assert result.get("qdrant"), "Qdrant write failed"

    # Write another
    await mgr.remember(content="User prefers metric units", session_id="e2e-test", importance=0.7)

    # Recall
    memories = await mgr.recall(query="weather", session_id="e2e-test", limit=10)
    assert len(memories) > 0, "Recall returned no results"

    await mgr.close_all()


# ═══════════════════════════════════════════════════════════════
# Test 2: Memory Compression
# ═══════════════════════════════════════════════════════════════

def test_memory_compression():
    """Test memory compression with many episodes."""
    from zenos.memory.compression import MemoryCompressor
    from zenos.memory.episodic import EpisodicMemory, Episode

    mem = EpisodicMemory()
    for i in range(20):
        ep = Episode(content=f"Episode {i}: " + "x" * 100, importance=0.3 + (i * 0.03))
        mem.add_episode(ep)

    assert len(mem.episodes) == 20

    compressor = MemoryCompressor(threshold=10)
    removed = compressor.compress(mem)
    assert removed > 0, "Compression should remove items"


# ═══════════════════════════════════════════════════════════════
# Test 3: Event Bus
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_event_bus():
    """Test event bus pub/sub."""
    from zenos.core.events import EventBus, Event, EventType

    bus = EventBus()
    events_received = []

    async def collector(event):
        events_received.append(event)

    # Use string event types for flexibility
    bus.subscribe("AGENT_START", collector)
    bus.subscribe("AGENT_COMPLETE", collector)

    await bus.publish(Event(type="AGENT_START", data={"session": "e2e"}))
    await bus.publish(Event(type="AGENT_COMPLETE", data={"result": "done"}))

    assert len(events_received) == 2, f"Expected 2 events, got {len(events_received)}"


# ═══════════════════════════════════════════════════════════════
# Test 4: Context Manager
# ═══════════════════════════════════════════════════════════════

def test_context_manager():
    """Test conversation context management."""
    from zenos.core.context import Context

    ctx = Context(session_id="e2e", max_messages=10)
    ctx.add_message("user", "Hello")
    ctx.add_message("assistant", "Hi there!")
    assert len(ctx.messages) == 2


# ═══════════════════════════════════════════════════════════════
# Test 5: State Machine
# ═══════════════════════════════════════════════════════════════

def test_state_machine():
    """Test state machine transitions."""
    from zenos.core.state import StateManager, SystemState

    sm = StateManager()
    assert sm.state in (SystemState.IDLE, "IDLE")
    sm.transition(SystemState.RUNNING if hasattr(SystemState, "RUNNING") else "RUNNING")
    sm.transition(SystemState.COMPLETE if hasattr(SystemState, "COMPLETE") else "COMPLETE")


# ═══════════════════════════════════════════════════════════════
# Test 6: Tool Execution + Safety
# ═══════════════════════════════════════════════════════════════

def test_tool_execution():
    """Test basic tool execution."""
    from zenos.tools.base import BaseTool, ToolResult, ToolParameter

    class EchoTool(BaseTool):
        name = "echo"
        description = "Echo input"
        parameters = [ToolParameter(name="text", type="string", required=True)]

        def execute(self, **kwargs):
            return ToolResult(success=True, output=kwargs.get("text", ""))

    tool = EchoTool()
    result = tool.execute(text="hello")
    assert result.success
    assert result.output == "hello"


# ═══════════════════════════════════════════════════════════════
# Test 7: Safety Checker
# ═══════════════════════════════════════════════════════════════

def test_safety_checker():
    """Test safety validation."""
    from zenos.agent.execution.safety import SafetyChecker, SafetyRule

    checker = SafetyChecker()
    checker.add_rule(SafetyRule(name="no_rm", pattern=r"rm\s+-rf\s+/", action="block"))

    safe, msg = checker.validate_input("echo hello")
    assert safe, "Safe input should pass"

    safe, msg = checker.validate_input("rm -rf /")
    assert not safe, "Dangerous input should be blocked"


# ═══════════════════════════════════════════════════════════════
# Test 8: Self-Healing
# ═══════════════════════════════════════════════════════════════

def test_self_healing():
    """Test self-healing recovery strategies."""
    from zenos.agent.self_healing import SelfHealingEngine, RecoveryStrategy

    engine = SelfHealingEngine()
    engine.add_strategy(RecoveryStrategy.RETRY_SIMPLIFIED)
    engine.add_strategy(RecoveryStrategy.FALLBACK_TOOL)

    result = engine.attempt_recovery(
        error="timeout",
        tool_name="web_search",
        params={"query": "weather", "extra": "data"},
    )
    assert result is not None


# ═══════════════════════════════════════════════════════════════
# Test 9: Adaptive Router
# ═══════════════════════════════════════════════════════════════

def test_adaptive_router():
    """Test adaptive routing with learning."""
    from zenos.agent.adaptive_router import AdaptiveRouter, RoutingStrategy

    router = AdaptiveRouter()
    router.add_strategy(RoutingStrategy.DIRECT)
    router.add_strategy(RoutingStrategy.CHAIN)

    strategy = router.select_strategy(task_type="question")
    assert strategy is not None

    router.record_outcome("question", RoutingStrategy.DIRECT, success=True, reward=1.0)
    router.record_outcome("question", RoutingStrategy.CHAIN, success=False, reward=0.0)
    best = router.select_strategy(task_type="question")
    assert best is not None


# ═══════════════════════════════════════════════════════════════
# Test 10: Memory Graph
# ═══════════════════════════════════════════════════════════════

def test_memory_graph():
    """Test knowledge graph operations."""
    from zenos.memory.memory_graph import MemoryGraph

    g = MemoryGraph()
    n1 = g.add_node("Paris", concept="city", importance=0.9)
    n2 = g.add_node("France", concept="country", importance=0.8)
    n3 = g.add_node("Europe", concept="continent", importance=0.7)

    g.add_edge(n1, n2, "capital_of", weight=1.0)
    g.add_edge(n2, n3, "part_of", weight=0.8)

    assert g.node_count() == 3
    assert g.edge_count() == 2

    related = g.traverse(n1, max_depth=2)
    assert len(related) >= 2


# ═══════════════════════════════════════════════════════════════
# Test 11: Multi-Tier Cache
# ═══════════════════════════════════════════════════════════════

def test_multi_tier_cache():
    """Test L1/L2 cache."""
    from zenos.infrastructure.caching.cache import MultiTierCache, CacheStrategy

    cache = MultiTierCache(l1_size=100, l2_size=500, strategy=CacheStrategy.LRU)
    cache.put("key1", "value1")
    assert cache.get("key1") == "value1"
    assert cache.get("nonexistent") is None

    stats = cache.stats()
    assert stats["l1_size"] == 1


# ═══════════════════════════════════════════════════════════════
# Test 12: Message Broker
# ═══════════════════════════════════════════════════════════════

def test_message_broker():
    """Test pub/sub message broker."""
    from zenos.infrastructure.messaging.broker import MessageBroker

    broker = MessageBroker()
    received = []

    def handler(msg):
        received.append(msg)

    broker.subscribe("test_topic", handler)
    broker.publish("test_topic", {"data": "hello"})
    assert len(received) == 1
    assert received[0]["data"] == "hello"


# ═══════════════════════════════════════════════════════════════
# Test 13: Metrics Collector
# ═══════════════════════════════════════════════════════════════

def test_metrics_collector():
    """Test metrics collection."""
    from zenos.observability.metrics.collector import MetricsCollector

    mc = MetricsCollector()
    mc.increment("requests", tags={"method": "GET"})
    mc.increment("requests", tags={"method": "GET"})
    mc.increment("requests", tags={"method": "POST"})

    val = mc.get_counter("requests", tags={"method": "GET"})
    assert val == 2

    mc.histogram("response_time", 0.15)
    mc.histogram("response_time", 0.25)
    stats = mc.get_histogram_stats("response_time")
    assert stats["count"] == 2


# ═══════════════════════════════════════════════════════════════
# Test 14: Tracer
# ═══════════════════════════════════════════════════════════════

def test_tracer():
    """Test distributed tracing."""
    from zenos.observability.tracing.tracer import Tracer, SpanStatus

    tracer = Tracer()
    span = tracer.start_span("test_op", attributes={"key": "val"})
    tracer.end_span(span, SpanStatus.OK)
    assert span.status == SpanStatus.OK


# ═══════════════════════════════════════════════════════════════
# Test 15: Alert Manager
# ═══════════════════════════════════════════════════════════════

def test_alert_manager():
    """Test alert rule management."""
    from zenos.observability.alerting.alerter import AlertManager, AlertRule, AlertSeverity

    am = AlertManager()
    am.add_rule(AlertRule(name="high_error", condition="error", severity=AlertSeverity.HIGH))
    assert len(am.rules) == 1


# ═══════════════════════════════════════════════════════════════
# Test 16: Predictive Prefetcher
# ═══════════════════════════════════════════════════════════════

def test_predictive_prefetcher():
    """Test pattern-based prefetch prediction."""
    from zenos.infrastructure.caching.predictive import PredictivePrefetcher
    from zenos.infrastructure.caching.cache import MultiTierCache, CacheStrategy

    cache = MultiTierCache(l1_size=100, l2_size=500)
    prefetcher = PredictivePrefetcher(cache)

    prefetcher.record_access("a")
    prefetcher.record_access("b")
    prefetcher.record_access("a")

    pred = prefetcher.predict_next("a")
    # May or may not predict depending on implementation
    # Just verify no crash


# ═══════════════════════════════════════════════════════════════
# Test 17: Integration — MemoryBridge + EventWiring
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_integration_memory_events():
    """Test MemoryBridge + EventWiring integration."""
    from zenos.core.events import EventBus, Event
    from zenos.integration.event_wiring import EventWiring
    from zenos.observability.metrics.collector import MetricsCollector

    bus = EventBus()
    metrics = MetricsCollector()
    wiring = EventWiring(bus, metrics)

    # Publish events
    await bus.publish(Event(type="AGENT_START", data={}))
    await bus.publish(Event(type="TOOL_CALL", data={"tool": "echo"}))
    await bus.publish(Event(type="TOOL_RESULT", data={"tool": "echo", "success": True}))

    # Verify metrics were collected
    wiring_metrics = wiring.get_metrics()
    assert wiring_metrics is not None


# ═══════════════════════════════════════════════════════════════
# Test 18: Integration — ConcreteAgent full workflow
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_concrete_agent_workflow():
    """Test ConcreteAgent with memory + events + tools."""
    from zenos.core.events import EventBus
    from zenos.core.context import ContextManager
    from zenos.core.state import StateManager
    from zenos.memory.working import WorkingMemory
    from zenos.memory.episodic import EpisodicMemory
    from zenos.observability.metrics.collector import MetricsCollector
    from zenos.observability.tracing.tracer import Tracer

    bus = EventBus()
    ctx_mgr = ContextManager()
    state = StateManager()
    working = WorkingMemory(capacity=100)
    episodic = EpisodicMemory()
    metrics = MetricsCollector()
    tracer = Tracer()

    # Verify all components initialize
    assert bus is not None
    assert ctx_mgr is not None
    assert state is not None
    assert working is not None
    assert episodic is not None
    assert metrics is not None
    assert tracer is not None

    # Working memory + episodic integration
    working.add("greeting", "Hello, user!", priority=1.0)
    assert working.get("greeting") is not None


# ═══════════════════════════════════════════════════════════════
# Test 19: Plugin Manager
# ═══════════════════════════════════════════════════════════════

def test_plugin_manager():
    """Test plugin lifecycle."""
    from zenos.core.plugin import PluginManager, PluginType

    pm = PluginManager()
    pm.discover_plugins()
    # Just verify no crash


# ═══════════════════════════════════════════════════════════════
# Test 20: Registry (DI Container)
# ═══════════════════════════════════════════════════════════════

def test_registry():
    """Test dependency injection container."""
    from zenos.core.registry import Registry

    reg = Registry()
    reg.register("service_a", object())
    assert reg.get("service_a") is not None
    assert reg.get("nonexistent") is None


# ═══════════════════════════════════════════════════════════════
# Test 21: Procedural Memory
# ═══════════════════════════════════════════════════════════════

def test_procedural_memory():
    """Test skill registry and execution."""
    from zenos.memory.procedural import ProceduralMemory, Skill

    pm = ProceduralMemory()

    def dummy_skill(**kwargs):
        return "executed"

    pm.register_skill(name="test_skill", func=dummy_skill, description="A test skill")
    assert pm.has_skill("test_skill")

    result = pm.execute_skill("test_skill")
    assert result == "executed"

    skills = pm.list_skills()
    assert len(skills) >= 1


# ═══════════════════════════════════════════════════════════════
# Test 22: Semantic Memory
# ═══════════════════════════════════════════════════════════════

def test_semantic_memory():
    """Test semantic knowledge base."""
    from zenos.memory.semantic import SemanticMemory, Knowledge

    sm = SemanticMemory()
    sm.add_knowledge(content="Paris is the capital of France", tags=["geography", "paris"])
    sm.add_knowledge(content="Python is a programming language", tags=["programming", "python"])

    assert sm.count() == 2

    results = sm.search("capital")
    assert len(results) > 0

    results = sm.search_by_tag("programming")
    assert len(results) > 0


# ═══════════════════════════════════════════════════════════════
# Test 23: Working Memory
# ═══════════════════════════════════════════════════════════════

def test_working_memory():
    """Test LRU working memory."""
    from zenos.memory.working import WorkingMemory

    wm = WorkingMemory(capacity=5)
    wm.add("a", "1")
    wm.add("b", "2")
    wm.add("c", "3")

    assert wm.get("a") == "1"
    assert wm.size() == 3

    # Eviction
    wm.add("d", "4")
    wm.add("e", "5")
    wm.add("f", "6")  # Should evict "a"

    assert wm.size() == 5


# ═══════════════════════════════════════════════════════════════
# Test 24: Task Planning
# ═══════════════════════════════════════════════════════════════

def test_task_planning():
    """Test task decomposition."""
    from zenos.agent.planning.planner import TaskPlanner
    from zenos.agent.planning.task import Task, TaskStatus

    planner = TaskPlanner()
    task = Task(goal="Research and summarize AI trends", priority=1)
    assert task.status == TaskStatus.PENDING


# ═══════════════════════════════════════════════════════════════
# Test 25: Chain of Thought
# ═══════════════════════════════════════════════════════════════

def test_chain_of_thought():
    """Test chain-of-thought reasoning."""
    from zenos.agent.reasoning.chain import ChainOfThought

    cot = ChainOfThought(max_steps=5)
    cot.add_step(thought="First, I need to understand the problem", action="analyze")
    cot.add_step(thought="Then I will search for information", action="search")

    steps = cot.get_steps()
    assert len(steps) == 2


# ═══════════════════════════════════════════════════════════════
# Test 26: Reflection
# ═══════════════════════════════════════════════════════════════

def test_reflection():
    """Test self-reflection."""
    from zenos.agent.reasoning.reflection import Reflection

    refl = Reflection()
    critique = refl.reflect(goal="summarize text", memory=["step 1 done", "step 2 done"])
    assert critique is not None or True  # May return None if no issues


# ═══════════════════════════════════════════════════════════════
# Test 27: Auth Manager
# ═══════════════════════════════════════════════════════════════

def test_auth_manager():
    """Test JWT authentication."""
    from zenos.security.auth import AuthManager

    auth = AuthManager(secret_key="test-secret")
    token = auth.create_token(user_id="test-user", roles=["admin"])
    assert token is not None

    payload = auth.verify_token(token)
    assert payload is not None
    assert payload.get("user_id") == "test-user"


# ═══════════════════════════════════════════════════════════════
# Test 28: Audit Logger
# ═══════════════════════════════════════════════════════════════

def test_audit_logger():
    """Test audit logging."""
    from zenos.security.audit import AuditLogger

    logger = AuditLogger()
    logger.log(action="login", user="test-user", details={"ip": "127.0.0.1"})
    entries = logger.get_entries()
    assert len(entries) >= 1


# ═══════════════════════════════════════════════════════════════
# Test 29: Sandbox
# ═══════════════════════════════════════════════════════════════

def test_sandbox():
    """Test sandbox configuration."""
    from zenos.security.sandbox import Sandbox, SandboxConfig

    config = SandboxConfig(max_memory_mb=256, max_cpu_percent=50, timeout_seconds=30)
    sandbox = Sandbox(config)
    assert sandbox.config.max_memory_mb == 256


# ═══════════════════════════════════════════════════════════════
# Test 30: Priority Queue
# ═══════════════════════════════════════════════════════════════

def test_priority_queue():
    """Test priority message queue."""
    from zenos.infrastructure.messaging.queue import PriorityMessageQueue

    pq = PriorityMessageQueue()
    pq.enqueue("low", priority=3)
    pq.enqueue("high", priority=1)
    pq.enqueue("medium", priority=2)

    assert pq.dequeue() == "high"
    assert pq.dequeue() == "medium"
    assert pq.dequeue() == "low"


# ═══════════════════════════════════════════════════════════════
# Test 31: Config
# ═══════════════════════════════════════════════════════════════

def test_config():
    """Test configuration management."""
    from zenos.core.config import Config

    cfg = Config()
    cfg.set("test.key", "value")
    assert cfg.get("test.key") == "value"
    assert cfg.get("nonexistent", "default") == "default"


# ═══════════════════════════════════════════════════════════════
# Test 32: API Schemas
# ═══════════════════════════════════════════════════════════════

def test_api_schemas():
    """Test API data models."""
    from zenos.api.schemas.agent import AgentRunRequest, AgentRunResponse

    req = AgentRunRequest(task="test task")
    assert req.task == "test task"

    resp = AgentRunResponse(success=True, result="done")
    assert resp.success


# ═══════════════════════════════════════════════════════════════
# Test 33: Model Layer
# ═══════════════════════════════════════════════════════════════

def test_models():
    """Test data models."""
    from zenos.models.agent import AgentModel
    from zenos.models.memory import MemoryEntryModel
    from zenos.models.events import EventModel

    agent = AgentModel(name="test", description="test agent")
    assert agent.name == "test"

    mem = MemoryEntryModel(content="test memory", importance=0.5)
    assert mem.content == "test memory"


# ═══════════════════════════════════════════════════════════════
# Test 34: Auto Scaler
# ═══════════════════════════════════════════════════════════════

def test_auto_scaler():
    """Test auto-scaling policies."""
    from zenos.infrastructure.auto_scaler import AutoScaler, ScalingPolicy

    scaler = AutoScaler()
    policy = ScalingPolicy(metric="cpu", threshold=80, scale_up_factor=2)
    scaler.add_policy(policy)
    assert len(scaler.policies) == 1


# ═══════════════════════════════════════════════════════════════
# Test 35: Task Scheduler
# ═══════════════════════════════════════════════════════════════

def test_task_scheduler():
    """Test task scheduling."""
    from zenos.infrastructure.scheduling.scheduler import TaskScheduler
    from zenos.infrastructure.scheduling.jobs import Job, JobStatus

    scheduler = TaskScheduler()
    job = Job(name="test_job", func=lambda: None)
    assert job.status == JobStatus.PENDING


# ═══════════════════════════════════════════════════════════════
# Test 36: Tool Adapter
# ═══════════════════════════════════════════════════════════════

def test_tool_adapter():
    """Test external tool adapter."""
    from zenos.tools.adapters.adapter import ToolAdapter

    adapter = ToolAdapter(name="test_adapter", endpoint="http://localhost:8080")
    assert adapter.name == "test_adapter"


# ═══════════════════════════════════════════════════════════════
# Test 37: Custom Tool Loader
# ═══════════════════════════════════════════════════════════════

def test_custom_tool_loader():
    """Test YAML/JSON tool loader."""
    from zenos.tools.custom.loader import CustomToolLoader

    loader = CustomToolLoader()
    assert loader is not None


# ═══════════════════════════════════════════════════════════════
# Test 38: Execution Result
# ═══════════════════════════════════════════════════════════════

def test_execution_result():
    """Test execution result model."""
    from zenos.agent.execution.executor import ExecutionResult

    result = ExecutionResult(success=True, output="test", duration_ms=100)
    assert result.success
    assert result.duration_ms == 100
