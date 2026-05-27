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

## Memory Architecture

### Four-Tier Production Memory (Deployed & Tested)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FourTierMemoryManager                             │
│                                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│  │  Redis   │    │PostgreSQL│    │  Qdrant  │    │  S3/R2   │     │
│  │ (Tier 1) │    │ (Tier 2) │    │ (Tier 3) │    │ (Tier 4) │     │
│  │          │    │          │    │          │    │          │     │
│  │• Session │    │• Episodes│    │• Vectors │    │• Backups │     │
│  │  state   │    │• Tool log│    │• Semantic│    │• Archives│     │
│  │• Context │    │• Tags    │    │  search  │    │•Snapshots│     │
│  │  cache   │    │• Full-text│   │• Cluster │    │• Cold    │     │
│  │• Pub/sub │    │  search  │    │  index   │    │  storage │     │
│  │• Counters│    │• Temporal│    │          │    │          │     │
│  │          │    │  queries │    │          │    │          │     │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘     │
│       │               │               │               │            │
│       └───────────────┴───────────────┴───────────────┘            │
│                              │                                      │
│                   Unified Write/Read Path                           │
└─────────────────────────────────────────────────────────────────────┘

Write Path:
  Agent Action → Redis (immediate, <1ms) → PG (persist, ~5ms) → Qdrant (embed, ~10ms) → S3 (backup, async)

Read Path:
  Query → Redis (cache check) → PG (structured query) → Qdrant (vector search) → Merge & Rank
```

### Three-Tier Development Memory (In-Memory)

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

### Comparison

| Aspect | Three-Tier (Dev) | Four-Tier (Production) |
|--------|-----------------|----------------------|
| **Working** | In-memory LRU | Redis (distributed, persistent) |
| **Episodic** | JSON files | PostgreSQL (SQL, full-text search) |
| **Semantic** | In-memory vectors | Qdrant (ANN, billion-scale) |
| **Backup** | Manual JSON | S3 (automated, compressed, versioned) |
| **Scale** | Single machine | Distributed, multi-node |
| **Query** | Keyword + temporal | SQL + vector + hybrid |
| **Persistence** | File-based | Transactional + replicated |
| **Complexity** | Low | Higher (requires infra) |

## Core Modules & Sub-Modules

### Core Layer (`core/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `config.py` | `Config`, `ServerConfig`, `MemoryConfig` | Configuration (YAML/JSON/Env, hot-reload) |
| `events.py` | `EventBus`, `Event`, `EventType` | Async pub/sub event bus |
| `context.py` | `Context`, `ContextManager` | Conversation context management |
| `plugin.py` | `PluginManager`, `Plugin`, `PluginType` | Plugin lifecycle |
| `registry.py` | `Registry` | Service locator / DI container |
| `state.py` | `StateManager`, `SystemState` | State machine |

### Memory Layer (`memory/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `working.py` | `WorkingMemory` | Short-term LRU cache with TTL |
| `episodic.py` | `EpisodicMemory`, `Episode` | Medium-term experience log |
| `semantic.py` | `SemanticMemory`, `Knowledge` | Long-term knowledge base |
| `procedural.py` | `ProceduralMemory`, `Skill` | Skill/procedure registry |
| `compression.py` | `MemoryCompressor` | Memory compression strategies |
| `retrieval.py` | `MemoryRetriever` | Multi-strategy retrieval |
| `memory_graph.py` | `MemoryGraph` | Knowledge graph |
| `four_tier.py` | `FourTierMemoryManager` | Production 4-tier orchestration |
| `four_tier_config.py` | Connection config | Tier connection configuration |
| `storage/` | `MemoryStore`, backends | Storage backend abstractions |

### Agent Layer (`agent/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `base.py` | `BaseAgent` | Think-act-observe loop base |
| `concrete.py` | `ConcreteAgent` | Full agent with all integrations |
| `adaptive_router.py` | `AdaptiveRouter` | Multi-armed bandit routing |
| `self_healing.py` | `SelfHealingEngine` | Failure recovery |
| `planning/planner.py` | `TaskPlanner` | Goal decomposition |
| `reasoning/chain.py` | `ChainOfThought` | Chain-of-thought reasoning |
| `reasoning/reflection.py` | `Reflection` | Self-reflection |
| `execution/executor.py` | `Executor` | Tool execution |
| `execution/safety.py` | `SafetyChecker` | Input/output validation |

### Tools Layer (`tools/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `base.py` | `BaseTool`, `ToolResult` | Tool base class |
| `builtin/web_search.py` | `WebSearchTool` | Web search |
| `builtin/file_ops.py` | `FileReadTool`, `FileWriteTool` | File operations |
| `builtin/shell.py` | `ShellTool` | Shell commands |
| `builtin/http.py` | `HTTPTool` | HTTP API calls |
| `adapters/adapter.py` | `ToolAdapter` | External tool wrapper |
| `custom/loader.py` | `CustomToolLoader` | YAML/JSON tool loader |

### Infrastructure Layer (`infrastructure/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `scheduling/scheduler.py` | `TaskScheduler` | Cron/interval/one-shot scheduling |
| `caching/cache.py` | `MultiTierCache` | L1 LRU + L2 TTL cache |
| `caching/predictive.py` | `PredictivePrefetcher` | Pattern-based prefetch |
| `auto_scaler.py` | `AutoScaler` | Metric-driven auto-scaling |
| `messaging/broker.py` | `MessageBroker` | Pub/sub message broker |
| `messaging/queue.py` | `PriorityMessageQueue` | Priority message queue |

### Observability Layer (`observability/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `metrics/collector.py` | `MetricsCollector` | Counters, gauges, histograms |
| `tracing/tracer.py` | `Tracer`, `Span` | Distributed tracing |
| `alerting/alerter.py` | `AlertManager` | Rule-based alerting |

### Security Layer (`security/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `auth.py` | `AuthManager` | JWT authentication |
| `audit.py` | `AuditLogger` | Immutable audit trail |
| `sandbox.py` | `Sandbox` | Sandboxed execution |

### Integration Layer (`integration/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `memory_bridge.py` | `MemoryBridge` | Agent ↔ Memory bridge |
| `event_wiring.py` | `EventWiring` | EventBus ↔ Observability wiring |

### API Layer (`api/`)
| Module | Class | Purpose |
|--------|-------|---------|
| `routes/agent.py` | `AgentRouter` | Agent endpoints |
| `routes/memory.py` | `MemoryRouter` | Memory endpoints |
| `routes/tools.py` | `ToolsRouter` | Tool endpoints |
| `routes/system.py` | `SystemRouter` | System endpoints |
| `middleware/auth.py` | `AuthMiddleware` | JWT validation |
| `middleware/rate_limit.py` | `RateLimitMiddleware` | Rate limiting |
| `middleware/logging.py` | `LoggingMiddleware` | Request logging |

## Event Flow Reference

| Event Type | Publisher | Subscribers | Effect |
|------------|-----------|-------------|--------|
| `SYSTEM_STARTUP` | ZenOS | EventWiring | Initialize all subsystems |
| `AGENT_START` | ConcreteAgent | Tracer, Metrics | Start trace span |
| `AGENT_THINK` | ConcreteAgent | Tracer, Metrics | Record thought |
| `AGENT_ACT` | ConcreteAgent | Tracer, Metrics, Safety | Execute tool |
| `AGENT_OBSERVE` | ConcreteAgent | Tracer, Metrics, Memory | Write to episodic memory |
| `AGENT_REFLECT` | ConcreteAgent | Tracer, Metrics | Self-reflection |
| `AGENT_COMPLETE` | ConcreteAgent | Tracer, MemoryBridge | End span, trigger compression |
| `AGENT_ERROR` | ConcreteAgent | Tracer, AlertManager | End span with error |
| `TOOL_CALL` | Executor | Metrics, Safety | Validate input |
| `TOOL_RESULT` | Executor | Metrics, Safety | Validate output |
| `MEMORY_WRITE` | MemoryBridge | EventWiring | Check compression |
| `MEMORY_COMPRESS` | MemoryBridge | Metrics | Record stats |

## Key Design Decisions

### 1. Event-Driven Architecture
Every significant action publishes an event. Subscribers react asynchronously. This decouples modules and enables real-time metrics, automatic memory compression, and pattern-based alerting.

### 2. Four-Tier Memory
- **Tier 1 (Redis)**: Ephemeral session state, real-time counters, pub/sub
- **Tier 2 (PostgreSQL)**: Structured episodes, full-text search, tool logs
- **Tier 3 (Qdrant)**: Vector similarity search, semantic retrieval
- **Tier 4 (S3/MinIO)**: Backups, archives, cold storage

### 3. Adaptive Routing
Multi-armed bandit algorithm learns which strategy (direct/chain/plan/reflect) works best for each task type.

### 4. Self-Healing
Automatic recovery: retry simplified → fallback tool → task decomposition → skip and continue.

### 5. Memory Graph
Semantic memories connected in a knowledge graph for context expansion and community detection.

## Deployment

### Production (aote-hk-cn2)

```bash
# Infrastructure (Docker)
docker run -d --name zenos-redis -p 6379:6379 redis:7-alpine
docker run -d --name zenos-postgres -p 5432:5432 -e POSTGRES_USER=zenos -e POSTGRES_PASSWORD=zenos -e POSTGRES_DB=zenos postgres:16-alpine
docker run -d --name zenos-qdrant -p 6333:6333 -e QDRANT__SERVICE__API_KEY=qdrant_hermes_2026_secure_key qdrant/qdrant:v1.18
docker run -d --name zenos-minio -p 9000-9001:9000-9001 -e MINIO_ROOT_USER=zenos -e MINIO_ROOT_PASSWORD=zenos-secret minio/minio:latest

# ZenOS
git clone https://github.com/kongjie0325-art/ZenOS.git /opt/zenos
cd /opt/zenos && python3 -m venv .venv
.venv/bin/pip install -e ".[four-tier]"
.venv/bin/pip install pytest pytest-asyncio

# Run tests
.venv/bin/python -m pytest zenos/tests/ -v

# Run four-tier integration test
.venv/bin/python zenos/memory/deploy_four_tier.py
```

### Development

```bash
pip install pyyaml
PYTHONPATH=. python3 -m pytest tests/ -v
python3 -m zenos
```

## Test Results

```
Core unit tests:     31 passed (config, events, context, registry, state, plugin)
Memory unit tests:   23 passed (working, episodic, semantic, procedural, compressor)
Four-tier integration: 5/5 tiers passed (Redis, PG, Qdrant, MinIO, Manager)
Total:               54 unit tests + integration tests, 100% pass rate
```

## Module Dependency Graph

```
                    ┌─────────────┐
                    │   __main__  │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │     API     │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────┴────┐      ┌────┴────┐      ┌────┴────┐
    │  Agent   │      │  Tools  │      │  Memory │
    └────┬────┘      └────┬────┘      └────┬────┘
         │                │                │
         └────────────────┼────────────────┘
                          │
                   ┌──────┴──────┐
                   │ Integration │
                   └──────┬──────┘
                          │
              ┌───────────┼───────────┐
              │           │           │
         ┌────┴────┐ ┌───┴────┐ ┌───┴────┐
         │  Core   │ │ Infra  │ │Observ. │
         └─────────┘ └────────┘ └────────┘
```
