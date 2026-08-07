import json

from repo_agent_harness import server


def test_server_instructions_present():
    """The server ships concise, client-agnostic orientation cues."""
    text = server.mcp.instructions
    assert text
    assert "repo_context_overview" in text
    assert "repo_verify_changed" in text
    # Zero-footprint default: the navigation discipline and the explorer-preference
    # live in the always-read instructions, not in a per-repo AGENTS.md.
    assert "explorer" in text
    # Materialization is opt-in, surfaced here so the model knows the lever exists.
    assert "repo_bootstrap" in text
    # The old serena onboarding directive is gone with the gate.
    assert "serena" not in text
    assert "FIRST action" not in text


def test_tool_functions_callable(repo, monkeypatch):
    monkeypatch.chdir(repo)
    assert server.repo_context_overview()["root"] == str(repo)
    assert server.repo_policy_check_command("rm -rf /")["allowed"] is False
    assert server.repo_context_status()["branch"]


def test_tools_registered():
    import asyncio

    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    expected = {
        "repo_context_overview",
        "repo_context_status",
        "repo_context_relevant_files",
        "repo_search_text",
        "repo_search_files",
        "repo_read_range",
        "repo_impact_file",
        "repo_verify_changed",
        "repo_diff_current",
        "repo_health",
        "repo_policy_check_command",
    }
    assert expected <= names


def test_res_impact_resource(repo, monkeypatch):
    monkeypatch.chdir(repo)
    result = json.loads(server.res_impact("src/payment.py"))
    assert "risk" in result
    assert result["risk"] == "high"


# ---------------------------------------------------------------------- param aliases


def _run_tool(name: str, args: dict) -> dict:
    import asyncio

    async def go() -> dict:
        tool = await server.mcp.get_tool(name)
        return (await tool.run(args)).structured_content

    return asyncio.run(go())


def test_repo_tool_schemas_advertise_only_canonical_names():
    """The published schema keeps the canonical field names — aliases are input-only sugar."""
    import asyncio

    async def props(name: str) -> set[str]:
        return set((await server.mcp.get_tool(name)).parameters.get("properties", {}))

    assert asyncio.run(props("repo_read_range")) == {"path", "start_line", "end_line"}
    text = asyncio.run(props("repo_search_text"))
    assert "query" not in text and "pattern" in text
    assert "glob" not in asyncio.run(props("repo_search_files"))


def test_repo_tools_accept_param_aliases(repo, monkeypatch):
    """Agents' natural guesses (start/end, query, glob) route to the canonical field via run()."""
    monkeypatch.chdir(repo)
    # repo_read_range: start/end -> start_line/end_line (pyproject.toml is non-code, always readable)
    assert _run_tool("repo_read_range", {"path": "pyproject.toml", "start": 1, "end": 2}) == _run_tool(
        "repo_read_range", {"path": "pyproject.toml", "start_line": 1, "end_line": 2}
    )
    # repo_search_text: query -> pattern
    assert _run_tool("repo_search_text", {"query": "charge"}) == _run_tool("repo_search_text", {"pattern": "charge"})
    # repo_search_files: glob -> pattern
    assert _run_tool("repo_search_files", {"glob": "*.py"}) == _run_tool("repo_search_files", {"pattern": "*.py"})


def test_repo_read_range_accepts_relative_path_alias(repo, monkeypatch):
    monkeypatch.chdir(repo)
    assert _run_tool(
        "repo_read_range", {"relative_path": "pyproject.toml", "start_line": 1, "end_line": 2}
    ) == _run_tool("repo_read_range", {"path": "pyproject.toml", "start_line": 1, "end_line": 2})


def test_symbols_overview_schema_is_flat():
    import asyncio

    async def go():
        return await server.mcp.get_tool("repo_symbols_overview")

    tool = asyncio.run(go())
    props = set(tool.parameters.get("properties", {}))
    assert "inp" not in props
    assert {"path", "limit"} <= props


def test_symbols_overview_accepts_flat_params(repo, monkeypatch):
    monkeypatch.chdir(repo)
    out = _run_tool("repo_symbols_overview", {"path": "src", "limit": 50})
    assert "symbols" in out and "error" not in out
