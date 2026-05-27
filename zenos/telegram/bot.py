"""
ZenOS Telegram Bot Module
=========================
Telegram bot gateway for ZenOS AI Agent.
Receives messages, calls LLM API directly, streams responses back.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Optional

import httpx
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

# ─── Configuration ───

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_USERS = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
ZENOS_API_URL = os.environ.get("ZENOS_API_URL", "http://127.0.0.1:8000")
BOT_NAME = os.environ.get("BOT_NAME", "ZenOS")

# LLM Configuration
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "longcat")
LLM_API_KEY = os.environ.get("LLM_API_KEY", os.environ.get("LONGCAT_API_KEY", ""))
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.longcat.chat/openai/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "LongCat-2.0-Preview")

# Parse allowed users
ALLOWED_USER_IDS: set[int] = set()
if TELEGRAM_ALLOWED_USERS:
    for uid in TELEGRAM_ALLOWED_USERS.split(","):
        uid = uid.strip()
        if uid.isdigit():
            ALLOWED_USER_IDS.add(int(uid))


# ─── Helpers ───

def is_authorized(user_id: int) -> bool:
    """Check if user is authorized."""
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


def split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split long message into Telegram-safe chunks."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:]
    return chunks


async def call_llm(messages: list[dict[str, str]], model: str = None) -> dict[str, Any]:
    """Call LLM API directly."""
    if not LLM_API_KEY:
        return {"error": "LLM_API_KEY not configured"}

    model = model or LLM_MODEL
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {"content": content, "model": model, "usage": data.get("usage", {})}
            else:
                return {"error": f"LLM API error {resp.status_code}: {resp.text[:300]}"}
    except httpx.TimeoutException:
        return {"error": "LLM API timeout (120s)"}
    except Exception as e:
        return {"error": f"LLM API call failed: {e}"}


async def call_llm_stream(
    messages: list[dict[str, str]],
    model: str = None,
):
    """Call LLM API with streaming."""
    if not LLM_API_KEY:
        yield {"error": "LLM_API_KEY not configured"}
        return

    model = model or LLM_MODEL
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": True,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{LLM_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    yield {"error": f"LLM API error {resp.status_code}: {await resp.aread()[:300]}"}
                    return

                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield {"content": content}
                        except json.JSONDecodeError:
                            continue
    except httpx.TimeoutException:
        yield {"error": "LLM API timeout (120s)"}
    except Exception as e:
        yield {"error": f"LLM API call failed: {e}"}


# ─── Command Handlers ───

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user = update.effective_user
    if not user or not is_authorized(user.id):
        if user:
            await update.message.reply_text("⛔ Unauthorized.")
        return

    welcome = (
        f"🤖 *{BOT_NAME} AI Agent*\n\n"
        f"Welcome, {user.first_name}!\n\n"
        f"Send me any message and I'll process it.\n\n"
        f"Commands:\n"
        f"/start — This message\n"
        f"/status — System status\n"
        f"/model — Show current model\n"
        f"/help — Help info"
    )
    await update.message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    user = update.effective_user
    if not user or not is_authorized(user.id):
        return
    help_text = (
        "📖 *ZenOS Bot Help*\n\n"
        "Simply type your question or task.\n\n"
        "Examples:\n"
        "• `Check system status`\n"
        "• `What's the weather like?`\n"
        "• `Help me write a Python script`\n"
        "• `Search for latest AI news`\n\n"
        "Long responses are split automatically.\n"
        f"Current model: `{LLM_MODEL}`"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    user = update.effective_user
    if not user or not is_authorized(user.id):
        return

    import subprocess
    import datetime

    # System info
    uptime = subprocess.getoutput("uptime -p 2>/dev/null || uptime")
    load = subprocess.getoutput("cat /proc/loadavg | awk '{print $1, $2, $3}'")
    mem = subprocess.getoutput("free -h | awk '/Mem:/{print $3\"/\"$2}'")
    disk = subprocess.getoutput("df -h / | awk 'NR==2{print $3\"/\"$2\" (\"$5\")\"}'")
    zenos_health = "unknown"

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{ZENOS_API_URL}/health")
            if resp.status_code == 200:
                data = resp.json()
                zenos_health = f"✅ {data.get('status', 'ok')} (v{data.get('version', '?')})"
            else:
                zenos_health = f"⚠️ HTTP {resp.status_code}"
    except Exception:
        zenos_health = "❌ Unreachable"

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_text = (
        f"📊 *ZenOS System Status*\n"
        f"`{now}`\n\n"
        f"🤖 Bot: `{BOT_NAME}`\n"
        f"🧠 Model: `{LLM_MODEL}`\n"
        f"🔗 ZenOS API: {zenos_health}\n"
        f"⏱ Uptime: `{uptime}`\n"
        f"📈 Load: `{load}`\n"
        f"💾 Memory: `{mem}`\n"
        f"💿 Disk: `{disk}`"
    )
    await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /model command."""
    user = update.effective_user
    if not user or not is_authorized(user.id):
        return
    await update.message.reply_text(
        f"🧠 Current model: `{LLM_MODEL}`\n"
        f"Provider: `{LLM_PROVIDER}`\n"
        f"API: `{LLM_BASE_URL}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages — call LLM and reply."""
    user = update.effective_user
    if not user:
        return
    if not is_authorized(user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    text = update.message.text.strip() if update.message.text else ""
    if not text:
        return

    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[{task_id}] User {user.id} ({user.first_name}): {text[:100]}")

    # Send "thinking" message
    thinking_msg = await update.message.reply_text(
        f"🤔 Thinking... (task `{task_id}`)",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Build messages
    messages = [
        {
            "role": "system",
            "content": (
                f"You are {BOT_NAME}, an AI assistant running on a Debian 12 VPS. "
                f"You have access to system tools and can help with various tasks. "
                f"Be concise and helpful. Respond in Chinese if the user writes in Chinese."
            ),
        },
        {"role": "user", "content": text},
    ]

    # Call LLM with streaming for better UX
    full_response = ""
    last_edit_time = time.time()
    edit_interval = 1.5  # Edit message every 1.5 seconds minimum

    try:
        async for chunk in call_llm_stream(messages):
            if "error" in chunk:
                full_response = f"❌ Error: {chunk['error']}"
                break
            full_response += chunk.get("content", "")

            # Throttle edits to avoid rate limiting
            now = time.time()
            if now - last_edit_time >= edit_interval and full_response:
                display_text = full_response + " ▌"
                if len(display_text) <= 4000:
                    try:
                        await thinking_msg.edit_text(
                            display_text[:4000],
                            parse_mode=ParseMode.MARKDOWN,
                        )
                        last_edit_time = now
                    except Exception:
                        pass  # Ignore edit failures during streaming

        # Final response
        if not full_response:
            full_response = "⚠️ No response from LLM."

    except Exception as e:
        full_response = f"❌ Error: {e}"
        logger.error(f"[{task_id}] Error: {e}", exc_info=True)

    # Send final response
    duration = time.time() - (last_edit_time - edit_interval)
    chunks = split_message(full_response)

    try:
        header = f"✅ Task `{task_id}` ({duration:.1f}s)\n\n"
        await thinking_msg.edit_text(
            header + chunks[0],
            parse_mode=ParseMode.MARKDOWN,
        )
        for chunk in chunks[1:]:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Failed to send final response: {e}")
        try:
            await thinking_msg.edit_text(full_response[:4096])
        except Exception:
            try:
                await update.message.reply_text(full_response[:4096])
            except Exception:
                pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    logger.error(f"Bot error: {context.error}", exc_info=context.error)


# ─── Bot Application ───

def create_bot() -> Application:
    """Create and configure the Telegram bot."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    return app


async def run_bot() -> None:
    """Run the bot (async entry point)."""
    app = create_bot()

    await app.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("status", "System status"),
        BotCommand("model", "Show model info"),
        BotCommand("help", "Help information"),
    ])

    logger.info(f"ZenOS Telegram Bot starting... Model: {LLM_MODEL}")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


def main() -> None:
    """Synchronous entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
