"""End-to-end concurrency regression tests for the harness MCP server.

These guard the reported failure mode — "the server hangs when parallel agents use
it" — by exercising the real FastMCP server (in-memory transport) under concurrent
load. Every test carries a hard ``timeout`` backstop so a regression fails loudly
instead of hanging the suite.
"""

import asyncio

import pytest
from fastmcp import Client
from repo_agent_harness import server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ------------------------------------------------------------------- server-level e2e


@pytest.fixture
def server_fixture(repo, monkeypatch):
    """Run the real MCP server in the fixture repo."""
    monkeypatch.chdir(repo)
    return server


@pytest.mark.timeout(45)
async def test_parallel_mixed_load_completes(server_fixture):
    """A burst of mixed concurrent tool calls all complete — no threadpool/event-loop deadlock."""
    srv = server_fixture
    async with Client(srv.mcp) as client:
        calls = []
        for _ in range(8):
            calls.extend(
                (
                    client.call_tool("repo_context_status", {}),
                    client.call_tool("repo_search_files", {"pattern": "*.py", "limit": 5}),
                    client.call_tool("repo_symbols_overview", {"path": "src", "limit": 50}),
                )
            )
        results = await asyncio.gather(*calls, return_exceptions=True)
    errors = [repr(r) for r in results if isinstance(r, Exception)]
    assert not errors, errors
    assert len(results) == 24
