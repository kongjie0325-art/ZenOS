# ZenOS - AI Operating System

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        ZenOS v0.1.0                             │
├─────────────────────────────────────────────────────────────────┤
│  API Layer          │  Agent Layer        │  Memory Layer       │
│  ─────────          │  ──────────         │  ───────────        │
│  AgentRouter        │  BaseAgent          │  WorkingMemory      │
│  MemoryRouter       │  TaskPlanner        │  EpisodicMemory     │
│  ToolsRouter        │  ChainOfThought     │  SemanticMemory     │
│  SystemRouter       │  Reflection         │  ProceduralMemory   │
│  AuthMiddleware     │  Executor           │  MemoryCompressor   │
│  RateLimitMiddleware│  SafetyChecker      │  MemoryRetriever    │
│  LoggingMiddleware  │                     │  HybridSearch       │
│                     │                     │  ReRanker           │
├─────────────────────┼─────────────────────┼─────────────────────┤
│  Tools Layer        │  Infrastructure     │  Observability      │
│  ─────────          │  ────────────       │  ────────────       │
│  BaseTool           │  TaskScheduler      │  MetricsCollector   │
│  WebSearchTool      │  MultiTierCache     │  Tracer             │
│  FileReadTool       │  PredictivePrefetcher│  AlertManager      │
│  FileWriteTool      │  MessageBroker      │  AlertRule          │
│  ShellTool          │  PriorityQueue      │  AlertChannel       │
│  HTTPTool           │                     │                     │
├─────────────────────┴─────────────────────┴─────────────────────┤
│                          Core Layer                              │
│  Config (YAML/JSON/Env) │ EventBus (Pub/Sub) │ Context Manager   │
│  PluginManager          │ Registry (DI)      │ StateManager      │
│                         │                    │  (State Machine)  │
├─────────────────────────────────────────────────────────────────┤
│                        Security Layer                           │
│  AuthManager (JWT) │ AuditLogger │ Sandbox (Resource Limits)   │
└─────────────────────────────────────────────────────────────────┘
```

## Module Map (88 Python files, ~406KB)

| Module              | Files | Key Components                          |
|---------------------|-------|-----------------------------------------|
| core/               | 7     | Config, EventBus, Context, Plugin, Registry, State |
| memory/             | 15    | Working, Episodic, Semantic, Procedural, Compression, Retrieval, Storage |
| agent/              | 11    | BaseAgent, Planner, Reasoning, Execution, Safety |
| tools/              | 11    | BaseTool, WebSearch, FileOps, Shell, HTTP, Adapters |
| infrastructure/     | 10    | Scheduler, Cache (L1/L2), Predictive, Broker, Queue |
| api/                | 13    | Routes (4), Middleware (3), Schemas (2) |
| observability/      | 7     | Metrics, Tracing, Alerting              |
| security/           | 4     | Auth, Audit, Sandbox                    |
| models/             | 4     | Agent, Memory, Events                   |
| tests/              | 3     | test_core (31 tests), test_memory (23 tests) |

## Memory Architecture (Three-Tier)

```
Working Memory  ──►  Episodic Memory  ──►  Semantic Memory
  (short-term)       (medium-term)        (long-term)
  LRU + TTL          Temporal index       Vector search
  Session-scoped     Experience-based     Knowledge-based
       │                    │                    │
       └────────────┬───────┘                    │
                    ▼                            │
            MemoryCompressor ◄───────────────────┘
            (Summarize/Prune/Consolidate)
                    │
                    ▼
            MemoryRetriever
            (Hybrid: BM25 + Vector + Temporal)
```

## Test Results

```
54/54 tests passed (100%)
- test_core.py: 31 tests (Config, EventBus, Context, Registry, State, Plugin)
- test_memory.py: 23 tests (Working, Episodic, Semantic, Procedural, Compression)
```

## Quick Start

```bash
# Install dependencies
pip install pyyaml aiohttp

# Run tests
PYTHONPATH=/home/ubuntu/zenos python3 -m pytest tests/ -v

# Run ZenOS
PYTHONPATH=/home/ubuntu/zenos python3 -m zenos

# With custom config
PYTHONPATH=/home/ubuntu/zenos python3 -m zenos config/default.yaml
```

## Design Principles

1. **Modularity**: Each module is self-contained with clear interfaces
2. **Async-first**: EventBus, Storage backends are async-compatible
3. **Type Safety**: Full type hints, dataclasses, runtime validation
4. **Observability**: Built-in metrics, tracing, alerting at every layer
5. **Security**: JWT auth, audit logging, sandboxed execution
6. **Extensibility**: Plugin system, custom tool loader, adapter pattern
7. **Resilience**: State machine, self-healing agent, circuit breaker pattern
8. **Performance**: L1/L2 cache, predictive prefetching, LRU eviction
