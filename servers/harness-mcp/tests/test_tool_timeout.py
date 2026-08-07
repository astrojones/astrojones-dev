"""Acceptance gate for the tool-dispatch timeout middleware (issue #23).

These drive the *real* FastMCP middleware path — every tool call funnels through
``ToolTimeoutMiddleware.on_call_tool`` — to prove a runaway tool dispatch is reaped at
the middleware's timeout instead of hanging the host, and that a sibling call stays
responsive while/after a slow one is timing out. They use the in-memory ``Client``
transport against the fixture repo, so they are deterministic Tier-1 tests.

Every test carries a hard ``pytest.mark.timeout`` backstop strictly larger than the
in-test timeout budget, so a *regression* (the middleware reverted / not firing)
FAILS the test on the timeout marker rather than hanging the whole suite.
"""

import asyncio

import pytest
from fastmcp import Client
from fastmcp.tools import Tool
from repo_agent_harness import server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def server_fixture(repo, monkeypatch):
    """Real MCP server in the fixture repo."""
    monkeypatch.chdir(repo)
    return server


def _add_slow_tool(srv, name: str, seconds: float) -> None:
    """Register a generic async tool that simply sleeps — a runaway handler."""

    async def _slow() -> str:
        await asyncio.sleep(seconds)
        return "done"

    srv.mcp.local_provider.add_tool(Tool.from_function(_slow, name=name))


@pytest.mark.timeout(20)
async def test_slow_tool_dispatch_is_reaped_at_tool_timeout(server_fixture, monkeypatch):
    """A generic tool that runs past the timeout surfaces an error within the deadline (#23).

    The middleware bounds every dispatch with ``anyio.fail_after`` and surfaces the
    resulting cancellation as a ``TimeoutError`` naming the tool. With the budget set
    well below the handler's own sleep, the call must return an ``is_error`` ToolResult
    promptly, not after the 20s pytest-timeout backstop.
    """
    monkeypatch.setattr(server, "_TOOL_TIMEOUT_S", 0.5)
    srv = server_fixture
    try:
        _add_slow_tool(srv, "slow_runaway", seconds=3600.0)
        async with Client(srv.mcp) as client:
            result = await client.call_tool("slow_runaway", {}, raise_on_error=False)
        assert getattr(result, "is_error", False) is True
        text = " ".join(getattr(c, "text", "") for c in result.content)
        assert "slow_runaway" in text
    finally:
        srv.mcp.local_provider.remove_tool("slow_runaway")


@pytest.mark.timeout(20)
async def test_sibling_tool_stays_responsive_during_slow_dispatch(server_fixture, monkeypatch):
    """A slow dispatch being reaped must not serialize/starve a concurrent sibling call (#23).

    Fired together: the runaway handler (reaped at the middleware timeout) and a fast
    generic tool. The sibling must complete normally and not be queued behind the slow
    one — proving the host heartbeat is never starved by a wedged handler.
    """
    monkeypatch.setattr(server, "_TOOL_TIMEOUT_S", 0.5)
    srv = server_fixture
    try:
        _add_slow_tool(srv, "slow_runaway", seconds=3600.0)
        async with Client(srv.mcp) as client:
            slow, fast = await asyncio.gather(
                client.call_tool("slow_runaway", {}, raise_on_error=False),
                client.call_tool("repo_context_status", {}, raise_on_error=False),
                return_exceptions=True,
            )
        # The slow call surfaced an error (timeout), the fast sibling resolved normally.
        assert isinstance(slow, Exception) or getattr(slow, "is_error", False)
        assert not isinstance(fast, Exception)
        assert getattr(fast, "is_error", False) is False
        assert fast.data.get("branch")
    finally:
        srv.mcp.local_provider.remove_tool("slow_runaway")


@pytest.mark.timeout(20)
async def test_responsive_after_slow_dispatch_timed_out(server_fixture, monkeypatch):
    """After a runaway dispatch is reaped, the next call resolves promptly — no lingering wedge (#23)."""
    monkeypatch.setattr(server, "_TOOL_TIMEOUT_S", 0.5)
    srv = server_fixture
    try:
        _add_slow_tool(srv, "slow_runaway", seconds=3600.0)
        async with Client(srv.mcp) as client:
            timed_out = await client.call_tool("slow_runaway", {}, raise_on_error=False)
            assert getattr(timed_out, "is_error", False) is True
            after = await client.call_tool("repo_context_status", {}, raise_on_error=False)
            assert getattr(after, "is_error", False) is False
            assert after.data.get("branch")
    finally:
        srv.mcp.local_provider.remove_tool("slow_runaway")
