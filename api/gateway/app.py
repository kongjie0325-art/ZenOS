"""ZenOS API Gateway - FastAPI 主应用"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ─── Request/Response Models ───

class TaskRequest(BaseModel):
    task: str
    workflow: str = "default"
    metadata: dict[str, Any] = {}


class TaskResponse(BaseModel):
    task_id: str
    state: str
    plan: list[str]
    results: dict[str, Any]
    errors: list[str]


class ToolCallRequest(BaseModel):
    tool_name: str
    params: dict[str, Any] = {}


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime: str


# ─── App ───

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # Startup
    from orchestrator.core import create_orchestrator
    app.state.orchestrator = create_orchestrator()
    yield
    # Shutdown
    pass


app = FastAPI(
    title="ZenOS - Agent Operating System",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", version="0.1.0", uptime="running")


@app.post("/api/v1/tasks", response_model=TaskResponse)
async def create_task(request: TaskRequest):
    """创建并执行任务"""
    orch = app.state.orchestrator
    ctx = orch.execute_task(
        task=request.task,
        workflow_name=request.workflow,
        metadata=request.metadata,
    )
    return TaskResponse(
        task_id=ctx.task_id,
        state=ctx.state.value,
        plan=ctx.plan,
        results=ctx.results,
        errors=ctx.errors,
    )


@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str):
    """获取任务状态"""
    orch = app.state.orchestrator
    ctx = orch.restore_task(task_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Task not found")
    return ctx.to_dict()


@app.post("/api/v1/tasks/{task_id}/rollback")
async def rollback_task(task_id: str, steps: int = 1):
    """回滚任务"""
    orch = app.state.orchestrator
    ctx = orch.rollback_task(task_id, steps)
    if not ctx:
        raise HTTPException(status_code=404, detail="Cannot rollback")
    return ctx.to_dict()


@app.post("/api/v1/tools/call")
async def call_tool(request: ToolCallRequest):
    """调用工具"""
    orch = app.state.orchestrator
    result = orch.tool_dispatcher.dispatch(request.tool_name, **request.params)
    return {
        "tool": result.tool_name,
        "success": result.success,
        "result": result.result,
        "error": result.error,
        "duration_ms": result.duration_ms,
    }


@app.get("/api/v1/memory/{task_id}")
async def get_memory(task_id: str, query: str = ""):
    """获取任务相关记忆"""
    orch = app.state.orchestrator
    if orch.memory_router:
        context = orch.memory_router.get_context(task_id, query)
        return context
    return {}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 实时通信"""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "task":
                orch = app.state.orchestrator
                ctx = orch.execute_task(
                    task=data.get("task", ""),
                    workflow=data.get("workflow", "default"),
                )
                await websocket.send_json(ctx.to_dict())
            elif action == "ping":
                await websocket.send_json({"action": "pong"})
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
