"""Minimal authenticated client: ask the bridge one question.

Usage:
    export BRIDGE_URL=https://your-host/mcp-ask
    export BRIDGE_KEY_FILE=./bearer.key
    python examples/ask.py "What did we decide about the release date?"

The key is read from a file, so its value never appears in argv, in the
environment, or in shell history.

Note: MCP SDK 2.0.0 types its Streamable HTTP transport against ``httpx2``, not
``httpx``. Passing an ``httpx.AsyncClient`` fails at runtime, which is why this
imports httpx2.
"""

import asyncio
import os
import sys
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8646/mcp")
KEY_FILE = Path(os.environ.get("BRIDGE_KEY_FILE", "bearer.key"))
TOOL_NAME = os.environ.get("BRIDGE_TOOL_NAME", "ask_agent")
TIMEOUT = float(os.environ.get("BRIDGE_TIMEOUT", "180"))


async def ask(question: str) -> str:
    key = KEY_FILE.read_text(encoding="utf-8").strip()
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {key}"},
        timeout=httpx2.Timeout(TIMEOUT, connect=15.0),
    ) as client:
        async with streamable_http_client(URL, http_client=client) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = [tool.name for tool in tools.tools]
                if names != [TOOL_NAME]:
                    raise SystemExit(f"expected exactly [{TOOL_NAME!r}], got {names}")
                result = await session.call_tool(TOOL_NAME, {"message": question})
                if result.is_error:
                    raise SystemExit(f"tool error: {result.content}")
                content = result.content[0] if result.content else None
                return getattr(content, "text", str(content))


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(f"usage: {sys.argv[0]} <question>")
    print(asyncio.run(ask(" ".join(sys.argv[1:]))))


if __name__ == "__main__":
    main()
