# ZenOS - Agent Operating System

> Cognitive Infrastructure for Autonomous AI Agents

## 架构图

```
                         ┌────────────────────┐
                         │      USER/UI       │
                         │ Web / Telegram/API │
                         └─────────┬──────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │      API Gateway / Auth     │
                    │   FastAPI + JWT + RateLimit │
                    └──────────────┬──────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │      ORCHESTRATOR         │
                     │   Agent Operating Core    │
                     │  LangGraph State Machine  │
                     └──────┬───────────┬────────┘
                            │           │
              ┌─────────────▼───┐   ┌──▼────────────────┐
              │  MODEL ROUTER   │   │ POLICY ENGINE     │
              │ cost/latency/   │   │ RBAC + ToolGuard  │
              │ capability-aware│   │ + Human Approval  │
              └──────┬──────────┘   └──────┬────────────┘
                     │                     │
     ┌───────────────▼─────────────────────▼───────────────┐
     │                    MEMORY BUS                        │
     │  Working(Redis) + Episodic(PG) + Semantic(Qdrant)   │
     │  + Artifact(S3/MinIO) + Distillation                 │
     └──────┬──────────┬──────────┬──────────┬────────────┘
            │          │          │          │
      ┌─────▼───┐ ┌────▼────┐ ┌──▼─────┐ ┌──▼─────┐
      │VectorDB │ │Postgres │ │Redis   │ │Object  │
      │Qdrant   │ │metadata │ │context │ │Storage │
      └─────────┘ └─────────┘ └────────┘ └────────┘

────────────────────────────────────────────────────────────
                    MCP TOOL BUS
────────────────────────────────────────────────────────────
  SSH │ Git │ Filesystem │ Docker │ Browser │ Cloudflare │ K8s

────────────────────────────────────────────────────────────
                EXECUTION / INFRASTRUCTURE
────────────────────────────────────────────────────────────
  Primary VPS (Orchestrator + Memory + Gateway)
  Executor Nodes (Browser / Crawler / Sandbox)
  GPU/AI Nodes (Embedding / Reranker / Local Models)

────────────────────────────────────────────────────────────
                    OBSERVABILITY
────────────────────────────────────────────────────────────
  Prometheus │ Grafana │ Loki │ Tempo │ OpenTelemetry
```

## 核心模块

| 模块 | 技术栈 | 作用 |
|------|--------|------|
| Orchestrator | Python + LangGraph | 状态机、任务调度、工作流 |
| Model Router | Python + httpx | 智能模型路由、成本优化 |
| Memory System | Redis + PG + Qdrant + S3 | 四层记忆、检索注入 |
| MCP Tool Bus | Python + MCP SDK | 工具注册、微服务化 |
| Policy Engine | Python + RBAC | 权限控制、沙箱隔离 |
| Observability | Prometheus + Grafana + Loki | 全链路追踪 |

## 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/kongjie0325-art/ZenOS.git
cd ZenOS

# 2. 配置环境变量
cp config/.env.example .env
vim .env  # 填入 API keys

# 3. 启动所有服务
docker-compose up -d

# 4. 访问
# API: http://localhost:8000
# Grafana: http://localhost:3000
# Docs: http://localhost:8000/docs
```

## 部署

```bash
# 一键安装
curl -fsSL https://raw.githubusercontent.com/kongjie0325-art/ZenOS/main/scripts/install.sh | bash

# 或手动部署
./scripts/deploy.sh
```

## License

MIT
