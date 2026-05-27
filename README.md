# ZenOS — AI Operating System

> A production-grade AI operating system with hierarchical memory, adaptive routing, self-healing, and full observability.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ZenOS v0.1.0                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │  API Layer   │  │ Agent Layer  │  │ Memory Layer │  │ Tools Layer  │       │
│  │ ─────────── │  │ ─────────── │  │ ─────────── │  │ ─────────── │       │
│  │ AgentRouter  │  │ BaseAgent   │  │ WorkingMem  │  │ BaseTool    │       │
│  │ MemoryRouter │  │ ConcreteAgent│ │ EpisodicMem │  │ WebSearch   │       │
│  │ ToolsRouter  │  │ AdaptiveRouter││ SemanticMem │  │ FileOps     │       │
│  │ SystemRouter │  │ SelfHealing │  │ ProceduralMem│ │ Shell       │       │
│  │ AuthMW       │  │ Planner     │  │ MemoryGraph │  │ HTTP        │       │
│  │ RateLimitMW  │  │ ChainOfThought││ Compressor  │  │ Adapters    │       │
│  │ LoggingMW    │  │ Reflection  │  │ Retriever   │  │ CustomLoader│       │
│  │ Schemas      │  │ Executor    │  │ HybridSearch│  │             │       │
│  │              │  │ SafetyCheck │  │ ReRanker    │  │             │       │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘       │
│         │                │                │                │               │
│  ┌──────┴────────────────┴────────────────┴────────────────┴──────┐       │
│  │                    Integration Layer                             │       │
│  │  MemoryBridge (persistence, compression, decay, context build)  │       │
│  │  EventWiring (metrics, tracing, alerting, auto-compression)     │       │
│  └───────────────────────────┬─────────────────────────────────────┘       │
│                              │                                              │
│  ┌───────────────────────────┴─────────────────────────────────────┐       │
│  │                        Core Layer                                │       │
│  │  Config (YAML/JSON/Env) │ EventBus (Pub/Sub) │ Context Manager  │       │
│  │  Plugin Manager         │ Registry (DI)      │ State Machine    │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                                                             │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────┐   │
│  │ Infrastructure       │  │ Observability        │  │ Security         │   │
│  │ ─────────────────── │  │ ─────────────────── │  │ ─────────────── │   │
│  │ TaskScheduler        │  │ MetricsCollector    │  │ JWT Auth        │   │
│  │ MultiTierCache(L1/L2)│  │ Tracer (Spans)      │  │ Audit Logger    │   │
│  │ PredictivePrefetcher │  │ AlertManager        │  │ Sandbox         │   │
│  │ AutoScaler           │  │ AlertRules/Channels │  │                 │   │
│  │ MessageBroker        │  │                     │  │                 │   │
│  │ PriorityQueue        │  │                     │  │                 │   │
│  └─────────────────────┘  └─────────────────────┘  └─────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## System Information Flow

```
User Request
    │
    ▼
[API Router] ── AuthMiddleware ── RateLimitMiddleware ── LoggingMiddleware
    │
    ▼
[ConcreteAgent.run()]
    │
    ├──► [TaskPlanner.decompose_goal()] → Task Plan
    │
    └──► Think-Act-Observe Loop (max 50 iterations)
         │
         ├── THINK ──────────────────────────────────────────────┐
         │  ├─ MemoryBridge.build_context()                     │
         │  │   ├─ EpisodicMemory.get_episodes() (recent)       │
         │  │   ├─ SemanticMemory.search() (relevant knowledge) │
         │  │   └─ Format as context string                     │
         │  ├─ ChainOfThought.step(context + goal)              │
         │  └─ Emit AGENT_THINK event                           │
         │                                                      │
         ├── ACT ────────────────────────────────────────────────┤
         │  ├─ AdaptiveRouter.select_tool(thought)               │
         │  ├─ Sync tools to Executor                           │
         │  ├─ Executor.execute_tool(tool_name, params)          │
         │  │   ├─ SafetyChecker.validate_input()               │
         │  │   ├─ func(**params)                                │
         │  │   └─ SafetyChecker.validate_output()              │
         │  ├─ On failure: SelfHealing._try_fallback()          │
         │  │   ├─ retry_simplified (strip params)              │
         │  │   ├─ fallback_tool (alternative tool)             │
         │  │   ├─ decompose_task (break into sub-tasks)        │
         │  │   └─ skip_and_continue (skip failed step)         │
         │  └─ Emit AGENT_ACT event                             │
         │                                                      │
         ├── OBSERVE ────────────────────────────────────────────┤
         │  ├─ Format observation string                        │
         │  ├─ EpisodicMemory.add_episode(result)               │
         │  └─ Emit AGENT_OBSERVE event                         │
         │                                                      │
         ├── [Every 5 iterations] ──────────────────────────────┤
         │  ├─ Reflection.reflect(goal, memory[-10:])           │
         │  ├─ Critique: issues + suggestions                   │
         │  └─ Emit AGENT_REFLECT event                         │
         │                                                      │
         └── [After loop] ──────────────────────────────────────┘
            ├─ MemoryBridge.check_and_compress()
            ├─ MemoryBridge.apply_decay()
            └─ Emit AGENT_COMPLETE event
                │
                ▼
         [EventWiring dispatches to:]
            ├─ MetricsCollector (counters, histograms)
            ├─ Tracer (spans for AGENT_* events)
            └─ AlertManager (on ERROR events)
                │
                ▼
         Response to User
```

## Memory Architecture (3-Tier + Graph)

```
                    ┌──────────────────┐
                    │  Procedural Mem  │  Skills/Procedures (callable)
                    │  (Skill Registry)│  "How to do X"
                    └────────┬─────────┘
                             │ references
                             ▼
┌─────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Working   │───►│    Episodic      │───►│    Semantic      │
│   Memory    │    │    Memory        │    │    Memory        │
│  (Short-term)│   │  (Medium-term)   │    │  (Long-term)     │
│             │    │                  │    │                  │
│ • LRU cache │    │ • Time-indexed   │    │ • Vector search  │
│ • TTL expire│    │ • Importance     │    │ • Knowledge graph│
│ • Session   │    │ • Searchable     │    │ • Communities    │
│   scoped    │    │ • Auto-compress  │    │ • Persisted      │
└─────────────┘    └──────────────────┘    └──────────────────┘
       │                  │                       │
       │                  │    ┌──────────────┐   │
       └──────────────────┼───►│ MemoryGraph  │◄──┘
                          │    │ (Relations)  │
                          │    └──────────────┘
                          │
                   ┌──────┴───────┐
                   │MemoryBridge  │
                   │              │
                   │• Persistence │  Save/Load sessions to disk
                   │• Compression │  Threshold-based pruning
                   │• Decay       │  Exponential importance decay
                   │• Context     │  Build context from all tiers
                   └──────────────┘
```

### Memory Data Flow

```
New Information
      │
      ▼
Working Memory (immediate, fast)
      │ (TTL expire / LRU evict)
      ▼
Episodic Memory (experience log, time-indexed)
      │ (compression: low-importance pruned)
      ▼
Semantic Memory (knowledge base, searchable)
      │ (MemoryGraph builds relationships)
      ▼
MemoryGraph (knowledge graph, community clusters)
      │
      ▼
Persistence (JSON on disk, cross-session)
```

## Core Modules & Sub-Modules

### Core Layer (`core/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `config.py` | `Config`, `ServerConfig`, `MemoryConfig`, ... | Configuration management (YAML/JSON/Env, hot-reload) |
| `events.py` | `EventBus`, `Event`, `EventType` | Async pub/sub event bus (priority, wildcard, history) |
| `context.py` | `Context`, `ContextManager` | Conversation context (messages, token budget, compression) |
| `plugin.py` | `PluginManager`, `Plugin`, `PluginType` | Plugin lifecycle (discovery, loading, hooks) |
| `registry.py` | `Registry` | Service locator / DI container (singleton, factory) |
| `state.py` | `StateManager`, `SystemState` | State machine (validated transitions, snapshots) |

### Memory Layer (`memory/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `working.py` | `WorkingMemory`, `WorkingMemoryEntry` | Short-term LRU cache with TTL |
| `episodic.py` | `EpisodicMemory`, `Episode` | Medium-term experience log with temporal index |
| `semantic.py` | `SemanticMemory`, `Knowledge` | Long-term knowledge base with vector search |
| `procedural.py` | `ProceduralMemory`, `Skill` | Skill/procedure registry with execution tracking |
| `compression.py` | `MemoryCompressor`, `CompressionStrategy` | Memory compression (summarize/prune/consolidate) |
| `retrieval.py` | `MemoryRetriever`, `RetrievalStrategy` | Multi-strategy retrieval (keyword/semantic/temporal/hybrid) |
| `memory_graph.py` | `MemoryGraph`, `GraphNode`, `GraphEdge` | Knowledge graph (traversal, communities) |
| `storage/memory_store.py` | `MemoryStore`, `LocalMemoryStore` | Storage backends (local JSON, Redis, Qdrant) |

### Agent Layer (`agent/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `base.py` | `BaseAgent`, `AgentContext`, `ToolDefinition` | Think-act-observe loop base |
| `concrete.py` | `ConcreteAgent` | Full agent with event/memory/metrics integration |
| `adaptive_router.py` | `AdaptiveRouter`, `StrategyStats` | Multi-armed bandit task routing |
| `self_healing.py` | `SelfHealingEngine`, `RecoveryStrategy` | Failure detection + recovery |
| `planning/planner.py` | `TaskPlanner` | Goal decomposition + task scheduling |
| `planning/task.py` | `Task`, `TaskStatus`, `TaskPriority` | Task data model |
| `reasoning/chain.py` | `ChainOfThought`, `ThoughtStep` | Chain-of-thought reasoning |
| `reasoning/reflection.py` | `Reflection`, `Critique` | Self-reflection and improvement |
| `execution/executor.py` | `Executor`, `ExecutionResult` | Tool execution (retry, batch, safety) |
| `execution/safety.py` | `SafetyChecker`, `SafetyRule` | Input/output validation |

### Tools Layer (`tools/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `base.py` | `BaseTool`, `ToolResult`, `ToolParameter` | Tool base class + schema |
| `builtin/web_search.py` | `WebSearchTool` | Web search (DuckDuckGo HTML) |
| `builtin/file_ops.py` | `FileReadTool`, `FileWriteTool`, `FileListTool` | File operations |
| `builtin/shell.py` | `ShellTool` | Shell command execution |
| `builtin/http.py` | `HTTPTool` | HTTP API calls |
| `adapters/adapter.py` | `ToolAdapter` | External tool wrapper |
| `custom/loader.py` | `CustomToolLoader` | Load tools from YAML/JSON definitions |

### Infrastructure Layer (`infrastructure/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `scheduling/scheduler.py` | `TaskScheduler` | Cron/interval/one-shot task scheduling |
| `scheduling/jobs.py` | `Job`, `JobStatus`, `JobPriority` | Job data model |
| `caching/cache.py` | `MultiTierCache`, `CacheStrategy` | L1 LRU + L2 TTL cache |
| `caching/predictive.py` | `PredictivePrefetcher` | Pattern-based prefetch |
| `auto_scaler.py` | `AutoScaler`, `ScalingPolicy` | Metric-driven auto-scaling |
| `messaging/broker.py` | `MessageBroker` | Pub/sub message broker |
| `messaging/queue.py` | `PriorityMessageQueue` | Priority message queue |

### Observability Layer (`observability/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `metrics/collector.py` | `MetricsCollector`, `MetricType` | Counters, gauges, histograms |
| `tracing/tracer.py` | `Tracer`, `Span`, `SpanStatus` | Distributed tracing |
| `alerting/alerter.py` | `AlertManager`, `AlertRule`, `AlertSeverity` | Rule-based alerting |

### Security Layer (`security/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `auth.py` | `AuthManager`, `JWTConfig` | JWT authentication (pure Python) |
| `audit.py` | `AuditLogger`, `AuditEvent` | Immutable audit trail |
| `sandbox.py` | `Sandbox`, `SandboxConfig` | Sandboxed execution (memory/CPU limits) |

### Integration Layer (`integration/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `memory_bridge.py` | `MemoryBridge` | Connects Agent ↔ Memory (persistence, compression, decay) |
| `event_wiring.py` | `EventWiring` | Connects EventBus ↔ Observability (metrics, traces, alerts) |

### API Layer (`api/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `routes/agent.py` | `AgentRouter` | Agent CRUD + run endpoints |
| `routes/memory.py` | `MemoryRouter` | Memory search/add/delete/compress |
| `routes/tools.py` | `ToolsRouter` | Tool list/execute/register |
| `routes/system.py` | `SystemRouter` | Health/config/metrics |
| `middleware/auth.py` | `AuthMiddleware` | JWT validation |
| `middleware/rate_limit.py` | `RateLimitMiddleware` | Token bucket rate limiting |
| `middleware/logging.py` | `LoggingMiddleware` | Request/response logging |
| `schemas/agent.py` | `AgentRunRequest`, `AgentRunResponse` | Agent API schemas |
| `schemas/memory.py` | `MemorySearchRequest`, `MemorySearchResponse` | Memory API schemas |

### Models Layer (`models/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `agent.py` | `AgentModel`, `AgentRunRequest`, ... | Agent data models |
| `memory.py` | `MemoryEntryModel`, `MemorySearchRequest`, ... | Memory data models |
| `events.py` | `EventModel`, `EventBatch`, `EventFilter` | Event data models |

## Event Flow Reference

| Event Type | Publisher | Subscribers | Effect |
|------------|-----------|-------------|--------|
| `SYSTEM_STARTUP` | ZenOS | EventWiring | Initialize all subsystems |
| `AGENT_START` | ConcreteAgent | Tracer, Metrics | Start trace span, increment counter |
| `AGENT_THINK` | ConcreteAgent | Tracer, Metrics | Record thought in span |
| `AGENT_ACT` | ConcreteAgent | Tracer, Metrics, Safety | Execute tool, record result |
| `AGENT_OBSERVE` | ConcreteAgent | Tracer, Metrics, Memory | Write to episodic memory |
| `AGENT_REFLECT` | ConcreteAgent | Tracer, Metrics | Self-reflection critique |
| `AGENT_COMPLETE` | ConcreteAgent | Tracer, MemoryBridge | End span, trigger compression |
| `AGENT_ERROR` | ConcreteAgent | Tracer, AlertManager | End span with error, trigger alert |
| `TOOL_CALL` | Executor | Metrics, Safety | Validate input, count call |
| `TOOL_RESULT` | Executor | Metrics, Safety | Validate output, count result |
| `TOOL_ERROR` | Executor | Metrics, AlertManager | Count error, trigger alert |
| `MEMORY_WRITE` | MemoryBridge | EventWiring | Check compression threshold |
| `MEMORY_COMPRESS` | MemoryBridge | Metrics | Record compression stats |
| `SYSTEM_ERROR` | Any | AlertManager | Trigger alert |

## Key Design Decisions

### 1. Event-Driven Architecture
Every significant action publishes an event. Subscribers (observability, memory, alerting) react asynchronously. This decouples modules and enables:
- Real-time metrics without polluting business logic
- Automatic memory compression triggered by write patterns
- Alerting on error patterns without try/catch everywhere

### 2. Three-Tier Memory
- **Working**: Ephemeral, session-scoped, fast (LRU + TTL)
- **Episodic**: Experience log, time-indexed, searchable by keyword
- **Semantic**: Knowledge base, searchable by vector similarity, persisted to disk

Each tier has different retention, compression, and retrieval strategies. Information flows from working → episodic → semantic as it ages and proves valuable.

### 3. Adaptive Routing
Tasks are routed to strategies (direct/chain/plan/reflect) using a multi-armed bandit algorithm. The router learns which strategy works best for each task type based on observed outcomes.

### 4. Self-Healing
Tool failures trigger automatic recovery: retry with simplified params → fallback tool → task decomposition → skip and continue. Recovery strategies are ranked by historical success rate.

### 5. Memory Graph
Semantic memories are connected in a knowledge graph. Graph traversal enables context expansion (find related memories), and community detection clusters related knowledge.

## Quick Start

```bash
# Install dependencies
pip install pyyaml

# Run tests
PYTHONPATH=. python3 -m pytest tests/ -v

# Run ZenOS
python3 -m zenos

# With custom config
python3 -m zenos config/default.yaml
```

## Test Results

```
Unit tests:   54 passed (test_core: 31, test_memory: 23)
E2E tests:    6 passed (AdaptiveRouter, SelfHealing, MemoryGraph, AutoScaler, MemoryBridge, ConcreteAgent)
Total:        60 tests, 100% pass rate
```
