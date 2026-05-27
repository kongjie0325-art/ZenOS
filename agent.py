"""
ZenOS Agent - 主 Agent 服务

集成：
- LongCat API (OpenAI 兼容格式)
- Telegram Bot
- 四层记忆系统
- 模型路由
- 状态机编排
- MCP 工具总线
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

# ─── Load .env ───
def load_env(env_path: str = "/opt/zenos/.env") -> dict[str, str]:
    """加载 .env 文件"""
    env: dict[str, str] = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    # 也读系统环境变量
    for key in env:
        env[key] = os.environ.get(key, env[key])
    return env

env = load_env()

# ─── Configuration ───
class Config:
    """ZenOS 配置"""
    # API
    API_HOST = env.get("API_HOST", "0.0.0.0")
    API_PORT = int(env.get("API_PORT", "8000"))

    # LLM
    LONGCAT_API_KEY = env.get("LONGCAT_API_KEY", "")
    LONGCAT_BASE_URL = env.get("LONGCAT_BASE_URL", "https://api.longcat.chat/openai")
    LONGCAT_ANTHROPIC_URL = env.get("LONGCAT_ANTHROPIC_URL", "https://api.longcat.chat/anthropic")
    DEFAULT_MODEL = env.get("DEFAULT_MODEL", "LongCat-2.0-Preview")
    FALLBACK_CHAIN = env.get("FALLBACK_CHAIN", "LongCat-2.0-Preview,deepseek-chat").split(",")

    # Telegram
    TELEGRAM_BOT_TOKEN = env.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_ALLOWED_USERS = env.get("TELEGRAM_ALLOWED_USERS", "").split(",")
    TELEGRAM_BOT_NAME = env.get("TELEGRAM_BOT_NAME", "zenos_bot")

    # User
    USER_FIRST_NAME = env.get("USER_FIRST_NAME", "User")
    USER_LAST_NAME = env.get("USER_LAST_NAME", "")
    USER_LANG = env.get("USER_LANG", "zh-hans")
    USER_ID = env.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0]

    # Memory
    REDIS_URL = env.get("REDIS_URL", "redis://localhost:6379/0")
    DATABASE_URL = env.get("DATABASE_URL", "postgresql://zenos:zenos@localhost:5432/zenos")
    QDRANT_URL = env.get("QDRANT_URL", "http://localhost:6333")
    QDRANT_API_KEY = env.get("QDRANT_API_KEY", "")

    # Node
    NODE_NAME = env.get("NODE_NAME", "zenos-node")
    NODE_ROLE = env.get("NODE_ROLE", "orchestrator")

    # Security
    JWT_SECRET = env.get("JWT_SECRET", "change-me")


config = Config()

# ─── LLM Client ───

class LLMClient:
    """LLM 客户端 - OpenAI 兼容格式"""

    def __init__(self, api_key: str, base_url: str, model: str = "LongCat-2.0-Preview"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """发送 chat 请求"""
        import httpx

        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    def extract_response(self, result: dict[str, Any]) -> tuple[str, list[dict]]:
        """提取回复和工具调用"""
        choice = result.get("choices", [{}])[0]
        msg = choice.get("message", {})
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls", [])
        return content, tool_calls


# ─── Telegram Bot ───

class TelegramBot:
    """Telegram Bot - 使用 python-telegram-bot"""

    def __init__(self, token: str, allowed_users: list[str]):
        self.token = token
        self.allowed_users = allowed_users
        self._handlers: list[callable] = []
        self._app = None

    def on_message(self, handler):
        """注册消息处理器"""
        self._handlers.append(handler)
        return handler

    def is_allowed(self, user_id: int | str) -> bool:
        return str(user_id) in self.allowed_users

    async def send_message(self, chat_id: int, text: str, parse_mode: str = "Markdown"):
        """发送消息"""
        import httpx
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text[:4096],  # Telegram limit
            "parse_mode": parse_mode,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(url, json=payload)

    async def send_chat_action(self, chat_id: int, action: str = "typing"):
        """发送 typing 状态"""
        import httpx
        url = f"https://api.telegram.org/bot{self.token}/sendChatAction"
        payload = {"chat_id": chat_id, "action": action}
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload)

    async def poll(self, handler_func):
        """长轮询获取消息"""
        import httpx

        offset = 0
        print(f"🤖 Telegram Bot polling started. Allowed users: {self.allowed_users}")

        while True:
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                params = {"offset": offset, "limit": 10, "timeout": 30}

                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.get(url, params=params)
                    data = resp.json()

                if not data.get("ok"):
                    await asyncio.sleep(5)
                    continue

                for update in data.get("result", []):
                    offset = update["update_id"] + 1

                    if "message" not in update:
                        continue

                    msg = update["message"]
                    user_id = str(msg.get("from", {}).get("id", ""))

                    if not self.is_allowed(user_id):
                        chat_id = msg.get("chat", {}).get("id", 0)
                        await self.send_message(chat_id, "⛔ 未授权用户")
                        continue

                    # 调用处理器
                    try:
                        await handler_func(msg)
                    except Exception as e:
                        print(f"Handler error: {e}")
                        chat_id = msg.get("chat", {}).get("id", 0)
                        await self.send_message(chat_id, f"❌ 错误: {str(e)[:200]}")

            except httpx.TimeoutException:
                continue
            except Exception as e:
                print(f"Poll error: {e}")
                await asyncio.sleep(5)


# ─── Agent System Prompt ───

SYSTEM_PROMPT = f"""你是 ZenOS，一个 Agent Operating System。

## 身份
- 名称：ZenOS-aote
- 节点：aote-hk-cn2 (103.149.93.192)
- 主模型：LongCat-2.0-Preview
- 用户：{config.USER_FIRST_NAME} {config.USER_LAST_NAME} ({config.USER_LANG})

## 核心能力
1. **状态机编排** - 任务通过 IDLE→PLANNING→EXECUTING→REVIEWING→DONE 流转
2. **智能模型路由** - 根据任务类型/成本/延迟选择最优模型
3. **四层记忆** - Working(Redis) + Episodic(PG) + Semantic(Qdrant) + Artifact(S3)
4. **MCP 工具总线** - 文件系统、Git、GitHub、SSH、Docker 等
5. **策略引擎** - RBAC 权限控制，危险操作需确认
6. **多节点执行** - Oracle ARM, Delux18 作为执行节点

## 行为准则
- 简洁汇报，结果导向
- 先查记忆再执行
- 危险操作二次确认
- 所有外部操作通过工具
- 执行后更新记忆

## 语言
- 默认中文回复
- 技术术语保留英文
"""


# ─── ZenOS Agent ───

class ZenOSAgent:
    """ZenOS 主 Agent"""

    def __init__(self):
        self.config = config
        self.llm = LLMClient(
            api_key=config.LONGCAT_API_KEY,
            base_url=config.LONGCAT_BASE_URL,
            model=config.DEFAULT_MODEL,
        )
        self.telegram = TelegramBot(
            token=config.TELEGRAM_BOT_TOKEN,
            allowed_users=config.TELEGRAM_ALLOWED_USERS,
        )
        self._session_memory: dict[str, list[dict]] = {}

    def get_session(self, chat_id: int) -> list[dict]:
        """获取会话记忆"""
        key = str(chat_id)
        if key not in self._session_memory:
            self._session_memory[key] = [
                {"role": "system", "content": SYSTEM_PROMPT}
            ]
        return self._session_memory[key]

    async def handle_message(self, msg: dict):
        """处理 Telegram 消息"""
        chat_id = msg.get("chat", {}).get("id", 0)
        text = msg.get("text", "")
        user = msg.get("from", {})
        username = user.get("first_name", "")

        if not text:
            return

        # Typing indicator
        await self.telegram.send_chat_action(chat_id)

        # 获取会话
        messages = self.get_session(chat_id)
        messages.append({"role": "user", "content": text})

        # 调用 LLM
        try:
            result = await self.llm.chat(messages=messages)
            content, tool_calls = self.llm.extract_response(result)

            if tool_calls:
                # 处理工具调用
                for tc in tool_calls:
                    func_name = tc.get("function", {}).get("name", "")
                    func_args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                    tool_result = await self.execute_tool(func_name, func_args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": str(tool_result),
                    })

                # 再次调用获取最终回复
                result = await self.llm.chat(messages=messages)
                content, _ = self.llm.extract_response(result)

            # 保存回复到会话
            if content:
                messages.append({"role": "assistant", "content": content})

            # 限制会话长度（保留 system + 最近 20 条）
            if len(messages) > 22:
                messages = [messages[0]] + messages[-20:]

            # 发送回复
            if content:
                await self.telegram.send_message(chat_id, content)
            else:
                await self.telegram.send_message(chat_id, "🤔 没有回复内容")

        except Exception as e:
            error_msg = f"❌ LLM 错误: {str(e)[:300]}"
            await self.telegram.send_message(chat_id, error_msg)

    async def execute_tool(self, name: str, args: dict) -> str:
        """执行工具调用"""
        tools = {
            "shell": self._tool_shell,
            "exec": self._tool_shell,
            "run_command": self._tool_shell,
            "read_file": self._tool_read_file,
            "write_file": self._tool_write_file,
            "list_files": self._tool_list_files,
            "search_files": self._tool_search_files,
            "web_search": self._tool_web_search,
            "web_fetch": self._tool_web_fetch,
            "git_status": self._tool_git_status,
            "docker_ps": self._tool_docker_ps,
            "get_time": self._tool_get_time,
            "get_system_info": self._tool_system_info,
        }

        handler = tools.get(name)
        if handler:
            try:
                return await handler(**args)
            except Exception as e:
                return f"Tool error: {e}"
        return f"Unknown tool: {name}"

    async def _tool_shell(self, command: str, **kwargs) -> str:
        import subprocess
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip() or result.stderr.strip()
        return output[:2000] if output else "(no output)"

    async def _tool_read_file(self, path: str, **kwargs) -> str:
        with open(path) as f:
            return f.read()[:2000]

    async def _tool_write_file(self, path: str, content: str, **kwargs) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return f"Written {len(content)} chars to {path}"

    async def _tool_list_files(self, path: str = ".", **kwargs) -> str:
        import glob
        files = glob.glob(os.path.join(path, "*"))[:50]
        return "\n".join(os.path.basename(f) for f in files)

    async def _tool_search_files(self, pattern: str, path: str = ".", **kwargs) -> str:
        import subprocess
        result = subprocess.run(
            ["grep", "-r", "-l", pattern, path],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()[:1000] or "No matches"

    async def _tool_web_search(self, query: str, **kwargs) -> str:
        return f"Web search: {query} (not implemented)"

    async def _tool_web_fetch(self, url: str, **kwargs) -> str:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            return resp.text[:2000]

    async def _tool_git_status(self, path: str = "/opt/zenos", **kwargs) -> str:
        import subprocess
        result = subprocess.run(
            ["git", "-C", path, "status", "--short"],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() or "Clean"

    async def _tool_docker_ps(self, **kwargs) -> str:
        import subprocess
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}} {{.Status}}"],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()

    async def _tool_get_time(self, **kwargs) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    async def _tool_system_info(self, **kwargs) -> str:
        import subprocess
        # CPU
        cpu = subprocess.run(["nproc"], capture_output=True, text=True).stdout.strip()
        # Memory
        mem = subprocess.run(["free", "-h"], capture_output=True, text=True).stdout.strip()
        # Disk
        disk = subprocess.run(["df", "-h", "/"], capture_output=True, text=True).stdout.strip()
        # Uptime
        uptime = subprocess.run(["uptime", "-p"], capture_output=True, text=True).stdout.strip()
        return f"CPU: {cpu} cores\\nMem:\\n{mem}\\nDisk:\\n{disk}\\nUptime: {uptime}"

    async def run(self):
        """启动 Agent"""
        print(f"""
╔══════════════════════════════════════════╗
║          ZenOS Agent v0.1.0             ║
║     Agent Operating System               ║
╠══════════════════════════════════════════╣
║ Node: {config.NODE_NAME:<33} ║
║ Role: {config.NODE_ROLE:<33} ║
║ Model: {config.DEFAULT_MODEL:<32} ║
║ Telegram: {config.TELEGRAM_BOT_NAME:<28} ║
╚══════════════════════════════════════════╝
        """)

        # 启动 Telegram polling
        await self.telegram.poll(self.handle_message)


# ─── Main Entry ───

async def main():
    agent = ZenOSAgent()
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
