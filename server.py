#!/usr/bin/env python3.12
"""
Odoo AI MCP Server — DeepSeek backend
Tools:
  chat(user_message)  → sends prompt to DeepSeek, returns reply
  clear_history()     → resets conversation
  get_history()       → shows full chat history
"""

import os
import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL    = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")

mcp = FastMCP("Odoo AI Assistant")

_history: list[dict] = []

SYSTEM_PROMPT = (
    "You are an expert Odoo ERP assistant. "
    "Help users with Odoo modules, business operations, "
    "configurations, Python/OWL development, and best practices. "
    "Answer clearly and concisely."
)


def _call_deepseek(messages: list[dict]) -> str:
    url = f"{DEEPSEEK_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7,
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


@mcp.tool()
def chat(user_message: str) -> str:
    """Send a message to DeepSeek AI. Conversation history is maintained across calls."""
    _history.append({"role": "user", "content": user_message})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + _history

    reply = _call_deepseek(messages)
    _history.append({"role": "assistant", "content": reply})
    return reply


@mcp.tool()
def clear_history() -> str:
    """Clear the full conversation history and start fresh."""
    _history.clear()
    return "Conversation history cleared."


@mcp.tool()
def get_history() -> str:
    """Return the full conversation history so far."""
    if not _history:
        return "No conversation history yet."
    lines = []
    for msg in _history:
        role = "You" if msg["role"] == "user" else "AI"
        lines.append(f"[{role}]: {msg['content']}")
    return "\n\n".join(lines)


if __name__ == "__main__":
    mcp.run()
