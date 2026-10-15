"""One helper for backend code that isn't an agent (the API routes and the
human approval path) to call the MCP server. Shop facts still only come
from MCP; this is just a client, not a second tools layer."""

import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

HW = Path(__file__).resolve().parents[1]


def client() -> Client:
    return Client(StdioTransport(command=sys.executable, args=[str(HW / "mcp_server" / "server.py")], cwd=str(HW)))


# The API keeps one connection open for its lifetime (see main.py), so a route
# doesn't pay ~1.5 s to start the server on every call. Scripts fall back to
# a fresh connection per call.
shared: Client | None = None


async def call(name: str, args: dict | None = None) -> dict:
    if shared is not None:
        return (await shared.call_tool(name, args or {})).structured_content
    async with client() as c:
        return (await c.call_tool(name, args or {})).structured_content
