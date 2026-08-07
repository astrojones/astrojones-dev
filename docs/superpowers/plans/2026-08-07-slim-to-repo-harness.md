# Astrojones Slim-Down to Repo-Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all serena proxying and cognee memory from the astrojones plugin (submodule at `astrojones/`), leaving a lean repo-harness: `repo_*` tools, safety hooks, AGENTS.md auto-harness, workflow skills.

**Architecture:** Delete 11 serena/cognee modules plus 4 cognee/onboard skills and 11 test files; surgically strip imports, call-sites, and models in the surviving modules (`server.py`, `agent_hooks.py`, `cli.py`, `perception.py`, `context.py`, `scaffold.py`, `health.py`, `symbols.py`, `models.py`, `paths.py`); drop 4 dependencies from `pyproject.toml`; update metadata/docs; bump version to `4.0.0` (breaking change). Serena moves to a standalone daemon + shim owned by the personal layer (separate plan).

**Tech Stack:** Python 3.13, FastMCP, pydantic, psutil, pyyaml, watchfiles, tree-sitter; ruff, ty, pytest. All line numbers verified against commit `7f24b78` (3.24.4).

## Global Constraints

- No new dependencies. Only removals.
- The `repo_*` MCP tool surface is unchanged, except deleting the 8 `mem_*` tools and `repo_onboard_complete`.
- The PreToolUse/PostToolUse/UserPromptSubmit safety hooks keep working: safe-shell guard + secret-read guard + verify feedback. No serena read-gate, no cognee recall, no SessionStart hook.
- Every task ends green: `cd servers/harness-mcp && uv run pytest && uv run ruff check . && uv run ty check`.
- Version bump to `4.0.0` in both `pyproject.toml` and `.claude-plugin/plugin.json` (breaking).
- `.serena` references in `deploy.py` `SKIP_DIRS` are kept — harmless, and the shim layer may still write `.serena/project.yml` per repo.
- `capture_output=True` in `symbols.py` is a subprocess arg — NOT the `capture` module — leave it alone.

---

### Task 1: Delete serena/cognee modules, skills, tests, and dead deps

**Files:**
- Delete: `servers/harness-mcp/repo_agent_harness/{serena_gate.py, serena_daemon.py, gateway.py, serena_tools.json, cognee_client.py, cognee_local.py, cognee_sync.py, cognee_local_summarize_prompt.txt, sync_ledger.py, capture.py, claude_mem_reader.py}`
- Delete: `hooks/session_start.py`
- Delete: `skills/{astrojones-cognee-doctor, astrojones-graph-tune, astrojones-mem-ingest-wisely, onboard}/`
- Delete tests: `tests/{fake_cognee.py, fake_serena.py, test_cognee_client.py, test_cognee_local.py, test_cognee_sync.py, test_gateway.py, test_gateway_http.py, test_serena_stress.py, test_serena_stress_real.py, test_mem.py, test_claude_mem_reader.py}`
- Modify: `servers/harness-mcp/pyproject.toml`, `hooks/hooks.json`

**Interfaces:** None produced (pure deletion). Later tasks remove dangling references to these modules.

- [ ] **Step 1: Delete the module, skill, hook, and test files**

```bash
cd /Users/jonah/dev/agentism/astrojones
git rm servers/harness-mcp/repo_agent_harness/serena_gate.py \
       servers/harness-mcp/repo_agent_harness/serena_daemon.py \
       servers/harness-mcp/repo_agent_harness/gateway.py \
       servers/harness-mcp/repo_agent_harness/serena_tools.json \
       servers/harness-mcp/repo_agent_harness/cognee_client.py \
       servers/harness-mcp/repo_agent_harness/cognee_local.py \
       servers/harness-mcp/repo_agent_harness/cognee_sync.py \
       servers/harness-mcp/repo_agent_harness/cognee_local_summarize_prompt.txt \
       servers/harness-mcp/repo_agent_harness/sync_ledger.py \
       servers/harness-mcp/repo_agent_harness/capture.py \
       servers/harness-mcp/repo_agent_harness/claude_mem_reader.py \
       hooks/session_start.py
git rm -r skills/astrojones-cognee-doctor skills/astrojones-graph-tune skills/astrojones-mem-ingest-wisely skills/onboard
git rm servers/harness-mcp/tests/fake_cognee.py \
       servers/harness-mcp/tests/fake_serena.py \
       servers/harness-mcp/tests/test_cognee_client.py \
       servers/harness-mcp/tests/test_cognee_local.py \
       servers/harness-mcp/tests/test_cognee_sync.py \
       servers/harness-mcp/tests/test_gateway.py \
       servers/harness-mcp/tests/test_gateway_http.py \
       servers/harness-mcp/tests/test_serena_stress.py \
       servers/harness-mcp/tests/test_serena_stress_real.py \
       servers/harness-mcp/tests/test_mem.py \
       servers/harness-mcp/tests/test_claude_mem_reader.py
```

- [ ] **Step 2: Drop the 4 dead dependencies from `servers/harness-mcp/pyproject.toml`**

Remove exactly these lines from the `dependencies` list (keep everything else):

```toml
    "serena-agent @ git+https://github.com/oraios/serena@2449313c0d7427275c4c66aedff7d4881782f713",
    "httpx>=0.27",
    "claude-agent-sdk>=0.2.120",
    "sqlmodel>=0.0.39",
```

Keep: `fastmcp>=3.0`, `mcp>=1.20`, `psutil>=5.9`, `pydantic>=2.9`, `pyyaml>=6.0`, `watchfiles>=1.0`, `tree-sitter>=0.23,<0.26`, `tree-sitter-language-pack>=0.13`.

Also remove the two now-dead ruff per-file-ignores blocks:

```toml
# Daemon manager spawns the detached Serena HTTP server (fixed argv from our own config).
"repo_agent_harness/serena_daemon.py" = ["S404"]
```

```toml
# SyncLedger.record() takes the six columns of one ledger row (kind, source_id, content_hash,
# dataset, verify_status, shipped_at) — an honest 1:1 with the table, not a refactorable clump.
"repo_agent_harness/sync_ledger.py" = ["PLR0913", "PLR0917"]
```

- [ ] **Step 3: Remove the SessionStart entry from `hooks/hooks.json`**

Delete the entire `"SessionStart": [...]` block (it ran only `session_start.py`). Update the top-level `"description"` to drop "a bounded durable-memory recall at session start (SessionStart)" — the description should now describe safe-shell + secret-read guard (PreToolUse), verify feedback (PostToolUse), and per-turn repo-state digest (UserPromptSubmit).

- [ ] **Step 4: Verify the package installs without the dropped deps**

```bash
cd servers/harness-mcp && uv sync 2>&1 | tail -5
```
Expected: resolves and installs without serena-agent/httpx/claude-agent-sdk/sqlmodel.

- [ ] **Step 5: Confirm the dangling-import state (expected failures only)**

```bash
uv run python -c "import repo_agent_harness.server" 2>&1 | tail -5
```
Expected: FAILS with `ModuleNotFoundError` (gateway/cognee imports not yet stripped — Tasks 2-4 fix this). Do not fix in this task.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor!: remove serena/cognee modules, skills, tests, deps"
```

---

### Task 2: Strip server.py of gateway/cognee/serena

**Files:**
- Modify: `servers/harness-mcp/repo_agent_harness/server.py`

**Interfaces:**
- Consumes: `perception.Perception(root)` (new signature, Task 4), `health.run(root, only, refresh)` (new signature, Task 4).
- Produces: `main()` and the unchanged `repo_*` MCP tool surface minus the 8 `mem_*` tools and `repo_onboard_complete`.

Line numbers from `7f24b78`. Work through the file top-down:

- [ ] **Step 1: Fix the import block (L33–55)**

Remove `cognee_client`, `cognee_local`, `cognee_sync`, `gateway`, `mem`, `serena_gate` from the `from repo_agent_harness import (...)` list. Keep the rest.

- [ ] **Step 2: Delete the gateway singleton (L66–70)**

```python
# Single owner of the child Serena process; created without connecting (lazy).
# The root is resolved on the first serena_* call — not here at import time — so the
# child Serena attaches to the real project even when the server process started
# elsewhere (e.g. $HOME in a cloud session, before CLAUDE_PROJECT_DIR/cwd is settled).
_serena = gateway.SerenaGateway(git.repo_root)
```

- [ ] **Step 3: Delete `_ensure_local_if_enabled` + `_bring_up_local` (L82–108)**

Both functions (local cognee Docker fallback bring-up). Delete the whole pair.

- [ ] **Step 4: Strip `_lifespan` (L111–178)**

Remove: L127 `gateway.reap_stale_serena_children(root)`, L128 `_seed_serena_languages(root)`, L132 `_autoseed_onboarding(...)` (verify exact call line), L137 → `perception.Perception(root)` (drop `gateway=_serena`), L147–164 (the `warm_task` + cognee sync block: `sync = cognee_sync.CogneeSync(root)`, `local_task`, `cognee_runtime_enabled`, `get_client`, `_bring_up_local`, `start`), and teardown L175–178 (`_cancel(local_task)`, `sync.stop()`, `_serena.aclose()`).

- [ ] **Step 5: Rewrite `_INSTRUCTIONS` (L181–216)**

Remove all serena_*/cognee/mem_* guidance (L183, 185–188, 192, 198, 204–206, 210–211). Keep the `repo_*` tool guidance. Mention the standalone serena daemon only as an external optional resource, if at all.

- [ ] **Step 6: Fix `ToolTimeoutMiddleware` (L219–251)**

Remove `gateway.tool_timeout()` (L241), `_serena.register_inflight` (L243), and `gateway.ToolTimeoutError` (L249). Inspect the middleware body: if it exists solely for serena's in-flight registry, delete the whole class and its registration; if it provides a generic timeout backstop for all tools, keep it with a plain `asyncio.TimeoutError` and a module-level `_TOOL_TIMEOUT_S` constant (default 300).

- [ ] **Step 7: Delete proxied serena tools registration (L257–258)**

```python
for _proxied in gateway.proxied_tools(_serena):
    mcp.add_tool(_proxied)
```

- [ ] **Step 8: Delete `_serena_read_gate` (L272–287) and its call site (L432–433)**

Delete the function and the `gated = _serena_read_gate(root, path)` + follow-up lines in the read-range tool.

- [ ] **Step 9: Delete `_ONBOARD_STUB` (L290), `_seed_serena_languages` (L293–329), `_autoseed_onboarding` (L332–355)**

All three are serena-onboarding machinery. Delete.

- [ ] **Step 10: Fix `repo_state` + health call (L493, L504)**

L493: `return health.run(root, only=check, refresh=refresh).model_dump() if root else _no_repo()` (drop `gateway=_serena`). L504: remove `serena_child_pid` from the docstring.

- [ ] **Step 11: Delete the durable-memory section (L707–820)**

Delete the `# --- durable memory (cognee)` section header and all 8 tools: `mem_search` (L711–724), `mem_rules` (L727–734), `mem_remember` (L737–749), `mem_ingest` (L752–774), `mem_stats` (L777–783), `mem_ontology` (L786–792), `mem_doctor` (L795–798), `repo_onboard_complete` (L801–820).

- [ ] **Step 12: Static-check and import-check**

```bash
cd servers/harness-mcp
uv run ty check repo_agent_harness/server.py
uv run ruff check repo_agent_harness/server.py
uv run python -c "import repo_agent_harness.server"
```
Expected: clean; import succeeds. (Tests still fail — Task 6 scrubs them.)

- [ ] **Step 13: Commit**

```bash
git add servers/harness-mcp/repo_agent_harness/server.py
git commit -m "refactor: strip serena/cognee from MCP server"
```

---

### Task 3: Strip agent_hooks.py — serena gate + cognee recall

**Files:**
- Modify: `servers/harness-mcp/repo_agent_harness/agent_hooks.py`

**Interfaces:**
- Produces: `main()` (hook entry, same CLI contract `python -m repo_agent_harness.agent_hooks <event>`), `pre_tool_use()`, `session_start()`, `post_tool_use()`, `user_prompt_submit()`. `session_start(data)` no longer takes a `client` param.
- Consumes: `paths`, `git`, `policies`, `secrets` (unchanged modules).

- [ ] **Step 1: Fix the import (L22)**

`from repo_agent_harness import git, paths, policies, secrets, serena_gate` → drop `serena_gate`.

- [ ] **Step 2: Delete the TYPE_CHECKING cognee import (L24–25)**

```python
if TYPE_CHECKING:
    from repo_agent_harness.cognee_client import CogneeClient
```

- [ ] **Step 3: Delete `_serena_gate_blocks` (L56–83)**

The whole function (read-gate predicate). Also delete its docstring.

- [ ] **Step 4: Delete the gate call site in `pre_tool_use` (L110–113)**

```python
            if tool == "Read" and repo is not None:
                blocks, msg = _serena_gate_blocks(repo, path, tin)
                if blocks:
                    return _deny(msg)
```

- [ ] **Step 5: Delete the recall constants block (L230–246)**

The whole `# SessionStart recall:` comment + `_RECALL_TIMEOUT_ENV`, `_RECALL_TIMEOUT_S`, `_RECALL_TOP_K`, `_RECALL_FLAG_ENV`, `_RECALL_LINE_CHARS`, `_RECALL_MAX_LINES`.

- [ ] **Step 6: Delete `_recall_section` (L333–385)**

The whole function (cognee durable-memory recall).

- [ ] **Step 7: Delete the onboarding nudge (L411–415)**

```python
    # [0] Onboarding nudge — independent of cognee reachability/config, so it still fires
    # when cognee is unconfigured or down.
    with suppress(Exception):
        if not paths.is_cognee_onboarded(repo):
            sections.append("This repo isn't yet onboarded into durable memory — run /astrojones:onboard")
```

- [ ] **Step 8: Delete the recall call site in `session_start` (L448–455)**

```python
    # [2] Durable-memory recall — ...
    from repo_agent_harness import mem  # noqa: PLC0415 - lazy: recall already pulls mem; keep other hooks light

    recall = _recall_section(name, mem.resolve_dataset(repo), client)
    if recall:
        sections.append(recall)
```

- [ ] **Step 9: Fix the `session_start` signature (L396)**

`session_start(data, client: CogneeClient | None = None, ...)` → drop the `client` param and all uses within the function body.

- [ ] **Step 10: Fix the `main` docstring (L496)**

Drop the `serena_gate` mention in the import-light rationale comment.

- [ ] **Step 11: Import-check + ruff**

```bash
cd servers/harness-mcp
uv run python -c "import repo_agent_harness.agent_hooks"
uv run ruff check repo_agent_harness/agent_hooks.py
```
Expected: clean import; ruff clean. (Tests scrubbed in Task 6.)

- [ ] **Step 12: Commit**

```bash
git add servers/harness-mcp/repo_agent_harness/agent_hooks.py
git commit -m "refactor: strip serena gate and cognee recall from hooks"
```

---

### Task 4: Strip cli.py, perception.py, context.py, scaffold.py, health.py, symbols.py, models.py, paths.py

**Files:**
- Modify: `servers/harness-mcp/repo_agent_harness/{cli.py, perception.py, context.py, scaffold.py, health.py, symbols.py, models.py, paths.py}`
- Also check: any default `health.yml` or config template that enumerates the `diagnostics` health-check kind.

**Interfaces:**
- Produces: `health.run(root, only=None, refresh=False)` (no `gateway` param); `Perception(root)` (no `gateway`); `models.PerceptionSnapshot` without `serena_child_pid`; `models.HealthSnapshot` without `in_flight`; `models` without `MemSearchIn/MemSearchResult/MemMigrateResult/InFlightCall`; `paths` without cognee helpers; `cli.py` without the 5 dead subcommands.
- Consumes: nothing new.

- [ ] **Step 1: cli.py — imports + dead subcommands**

Import block L15–31: remove `cognee_local`, `gateway`, `mem`, `serena_daemon`.
Delete `_cognee_local` dispatcher (L59–71). Delete subparsers: `gateway-snapshot` (L155–159), `serena-daemon` (L204–209), `cognee-local` (L210–216), `migrate-serena-memories` (L217–224), `memify` (L225–231). Delete the early cognee-local dispatch in `main` (L272–275). Delete the 4 dispatch-table entries (L303–316): `gateway-snapshot`, `migrate-serena-memories`, `memify`, `serena-daemon`. Fix the `health` dispatch entry to drop `gateway=_serena` if present.

- [ ] **Step 2: perception.py — drop the gateway**

Delete L32 `from repo_agent_harness.gateway import SerenaGateway` (keep the TYPE_CHECKING block and `Iterable` import). Constructor L88–91: `__init__(self, root: str) -> None`, drop `gateway` param, `self._gateway = gateway`, and the docstring's gateway sentence. Snapshot L158–163: remove `serena_child_pid=getattr(self._gateway, "_child_pid", None),`.

- [ ] **Step 3: context.py — drop serena language keys**

Delete `SERENA_LANG_KEY` (L150–172) and `serena_languages` (L186–198). Keep `detect_languages` (used by `overview`). Edit the `relevant_files` "method" string (L355–356): drop "use Serena (find_symbol / find_referencing_symbols) for symbol-level relevance" — replace with a plain description of the heuristic.

- [ ] **Step 4: scaffold.py — drop the serena migration**

Delete `_is_harness_installed_serena` (L77–79) and the migration block in `_install_mcp_json` (L91–95).

- [ ] **Step 5: health.py — drop diagnostics + gateway**

Delete module docstring serena sentence (L7). Delete `DiagnosticsGateway` protocol (L44–48). Delete `_tally_diagnostics`/`_count_diagnostics` (L182–208) and `_diagnostics_check` (L211–235). In `_run_check` (L248–252): drop the `gateway` param and the `diagnostics` branch, keep the duration stamp. Delete `_in_flight` (L320–332). In `_compute_snapshot`/`run` (L365–421): drop the `gateway` param everywhere, remove `in_flight=_in_flight(gateway)` (L386), fix docstrings. Scrub the `diagnostics` kind from `models.HealthCheckConfig` (kind enum) and any default `health.yml`/config that lists it — grep `diagnostics` beyond health.py to find them all.

- [ ] **Step 6: symbols.py — docstring rewrite**

Rewrite the module docstring (L1–13) to remove the Serena/cognee framing: the static index is the primary symbol source; the LSP stays reserved for semantic operations (references, implementations, diagnostics, renames). Leave `capture_output=True` (L124) untouched.

- [ ] **Step 7: models.py — delete cognee/serena models + fields**

Delete `MemSearchIn` (L64), `MemSearchResult` (L139), `MemMigrateResult` (L186), `InFlightCall` (L306), and any other `Mem*`/cognee transport models. Remove `serena_child_pid` from `PerceptionSnapshot` (L289). Remove `in_flight` from `HealthSnapshot` (L339–340). Remove the cognee-related comment near L115.

- [ ] **Step 8: paths.py — delete cognee helpers**

Delete `COGNEE_ONBOARDED_FILE` (L123), `cognee_onboarded_file` (L126–129), `cognee_endpoint_file` (L131–138), the sync-ledger path helper (L140–147), `is_cognee_onboarded` (L150–158), `onboarded_dataset` (L160–175), `mark_cognee_onboarded` (L177–180), plus the comments at L120–122. Keep `repo_state_dir` (still used by `symbols.json`).

- [ ] **Step 9: Full static gate**

```bash
cd servers/harness-mcp
uv run ty check
uv run ruff check .
uv run python -c "import repo_agent_harness.server, repo_agent_harness.cli, repo_agent_harness.agent_hooks"
```
Expected: ty clean, ruff clean, imports succeed.

- [ ] **Step 10: Commit**

```bash
git add servers/harness-mcp/repo_agent_harness/
git commit -m "refactor: strip serena/cognee from cli, perception, context, scaffold, health, models, paths"
```

---

### Task 5: Update plugin metadata + docs

**Files:**
- Modify: `.claude-plugin/plugin.json`, `README.md`, `AGENTS.md`, `CHANGELOG.md`, `servers/harness-mcp/repo_agent_harness/templates/mcp.json`, `servers/harness-mcp/pyproject.toml` (version only)

**Interfaces:** None (documentation + metadata only).

- [ ] **Step 1: Bump versions to 4.0.0**

`pyproject.toml`: `version = "3.24.4"` → `version = "4.0.0"`. `.claude-plugin/plugin.json`: `"version": "3.24.4"` → `"version": "4.0.0"`.

- [ ] **Step 2: plugin.json description + keywords**

Remove "proxied serena_* code navigation" from `description`; remove `"serena"` from `keywords`. Description should read: the repo agent harness as a Claude Code plugin: bundled auto-connecting MCP server (deterministic `repo_*` tools), safety hooks, generic coding-workflow skills and subagents.

- [ ] **Step 3: README.md**

Edit: L28 (remove "Serena, proxied ... as `serena_*` tools"), L31–32 (drop the `.serena/` gitignore sentence — no longer bundled; keep the "zero-footprint" claim), L68 (replace "locate with Serena" with `repo_symbols_overview` + native search), and any other serena/cognee mentions found by `grep -niE 'serena|cognee|gateway|mem_' README.md`.

- [ ] **Step 4: AGENTS.md**

Rewrite: L8 (serena tool surface), L12–17 (onboarding + durable memory — remove; onboarding is now the personal layer's serena daemon, and durable memory is mempalace), L21–22 (Serena-first symbol guidance — replace with `repo_symbols_overview`/`repo_context_relevant_files` + native search), L26 (explorer subagent description — drop "this same Serena+harness navigation" → "harness navigation"), L34 (locate with Serena), L61–62 (deps list — remove serena-agent/httpx/sqlmodel/claude-agent-sdk; external services — remove cognee/Serena/claude-mem), L68 (CLI examples — drop `cognee-local`), L82–84 (memory-path isolation + safety + durable memory — remove serena-gate sentence and cognee resilience; keep shell-policy), L88 (module list — drop gateway/serena_daemon/serena_gate/mem/cognee_*/claude_mem_reader/sync_ledger), L90 (skills list — drop onboard + 3 cognee skills). Delete the `<!-- astrojones:onboard:begin -->` ... `<!-- astrojones:onboard:end -->` comment block (L53/L94) — the onboard skill is deleted.

- [ ] **Step 5: templates/mcp.json**

Update `_comment`: remove "Serena is launched and proxied by the harness itself (serena_* tools)".

- [ ] **Step 6: CHANGELOG.md**

Add at top:

```markdown
## [4.0.0] - 2026-08-07

### Removed (breaking)
- Serena proxying: `serena_gate.py`, `serena_daemon.py`, `gateway.py`, `serena_tools.json`, the `serena-agent` pin.
- Cognee durable memory: `cognee_client.py`, `cognee_local.py`, `cognee_sync.py`, `sync_ledger.py`, `capture.py`, `claude_mem_reader.py`, the `mem_*` tools, `repo_onboard_complete`, the `onboard` skill and the 3 cognee skills, the SessionStart recall hook.
- Dependencies: `serena-agent`, `httpx`, `claude-agent-sdk`, `sqlmodel`.
- The serena read-gate inside the PreToolUse hook (nudging now lives in the personal layer via `serena-hooks remind`).

### Notes
- Serena is now a standalone daemon (`serena start-project-server`) managed by the personal layer; the MCP shim surfaces read-only `serena_*` tools from outside this plugin.
- Durable memory is owned by mempalace.
```

- [ ] **Step 7: Sweep for stragglers**

```bash
grep -rniE 'serena|serena_gate|serena_daemon|serena_tools|cognee|claude_mem|sync_ledger' README.md AGENTS.md CHANGELOG.md .claude-plugin/plugin.json servers/harness-mcp/repo_agent_harness/templates/ | grep -v '^Binary'
```
Expected: no matches (or only intentionally-kept mentions like this CHANGELOG entry — adjust CHANGELOG phrasing to use past-tense "removed" language, which the sweep legitimately catches; verify each remaining hit is in the CHANGELOG's removed-notes).

- [ ] **Step 8: Commit**

```bash
git add .
git commit -m "docs: update metadata and docs for serena/cognee removal; bump 4.0.0"
```

---

### Task 6: Fix remaining tests + full suite green

**Files:**
- Modify: `servers/harness-mcp/tests/{test_server.py, test_hooks.py, test_cli.py, test_health.py, test_context.py, test_perception.py, test_concurrency.py, test_tool_timeout.py, test_invariants.py, test_paths.py, test_pre_tool_use_shim.py, test_scaffold.py, conftest.py}`

**Interfaces:** Consumes the Task 2–4 module changes; produces a fully green suite.

Reference counts of serena/cognee/gateway/mem mentions per file (from `7f24b78`): `test_server.py` 68, `test_hooks.py` 87, `test_concurrency.py` 62, `test_tool_timeout.py` 25, `test_health.py` 13, `test_paths.py` 15, `test_pre_tool_use_shim.py` 13, `test_scaffold.py` 8, `test_invariants.py` 7, `test_context.py` 2.

- [ ] **Step 1: Run the suite to see the failure list**

```bash
cd servers/harness-mcp && uv run pytest -x -q 2>&1 | tail -30
```
Expected: import errors / collection failures referencing deleted modules. This is the work list.

- [ ] **Step 2: test_server.py — drop serena/cognee/mem coverage**

Delete: tests of `_serena_read_gate`, `_seed_serena_languages`, `_autoseed_onboarding`, `_bring_up_local`, the proxied-tools registration, the `mem_*` tools, `repo_onboard_complete`, and any fixture creating a `SerenaGateway`. Update tests of `_lifespan` to the new (no-gateway) shape. Update `_INSTRUCTIONS`-content assertions to the rewritten text.

- [ ] **Step 3: test_hooks.py — drop gate + recall coverage**

Delete: `_serena_gate_blocks` tests, `_recall_section` tests (and their `fake_cognee`/`fake_serena` fixtures), the cognee-recall fixture, and the onboarding-nudge assertion in `session_start` tests. Update `session_start` calls to the no-`client` signature. Keep safe-shell + secret-read denial tests intact (they must still pass).

- [ ] **Step 4: test_concurrency.py + test_tool_timeout.py — drop gateway fixtures**

Remove `SerenaGateway`/gateway fixtures and serena-specific concurrency tests. Keep any generic tool-concurrency/timeout tests (update the timeout middleware expectations to the Task 2 Step 6 decision).

- [ ] **Step 5: test_health.py — drop diagnostics + in-flight**

Delete `_diagnostics_check`/`_tally_diagnostics`/`_in_flight` tests and the `DiagnosticsGateway` fake. Update `health.run(...)` calls to the no-`gateway` signature. If a `diagnostics` kind test exists, delete it.

- [ ] **Step 6: test_paths.py, test_pre_tool_use_shim.py, test_scaffold.py, test_invariants.py, test_context.py, test_cli.py, test_perception.py**

- `test_paths.py`: delete `is_cognee_onboarded`/`mark_cognee_onboarded`/`cognee_onboarded_file`/`cognee_endpoint_file`/sync-ledger path tests.
- `test_pre_tool_use_shim.py`: delete the onboarded-fixture tests (gate gone); keep shell/secret refusal tests.
- `test_scaffold.py`: delete the serena-migration tests (`_is_harness_installed_serena`).
- `test_invariants.py`: remove any module-inventory/import assertions referencing deleted modules.
- `test_context.py`: delete `test_serena_languages_maps_and_dedupes`; fix the `relevant_files` method-string assertion to the new text.
- `test_cli.py`: delete tests of `cognee-local`/`serena-daemon`/`memify`/`migrate-serena-memories`/`gateway-snapshot` subcommands.
- `test_perception.py`: update `Perception(...)` constructor calls; remove `serena_child_pid` snapshot assertions.

- [ ] **Step 7: conftest.py**

Update the `_LEAKY_ENV_PREFIXES` comment (drop the `REPO_AGENT_HARNESS_NO_SERENA_GATE` example; the prefixes themselves stay — `REPO_AGENT_HARNESS_` and `COGNEE_` are harmless and still isolate).

- [ ] **Step 8: Full gate**

```bash
cd servers/harness-mcp
uv run pytest
uv run ruff check .
uv run ty check
```
Expected: all green — pytest passes, ruff clean, ty clean.

- [ ] **Step 9: Commit**

```bash
git add servers/harness-mcp/tests/
git commit -m "test: scrub serena/cognee fixtures; suite green"
```

---

### Task 7: Manual smoke test

**Files:** none (verification only; fix commits if issues found)

**Interfaces:** Consumes everything from Tasks 1–6.

- [ ] **Step 1: Start the MCP server standalone**

```bash
cd servers/harness-mcp && uv run repo-agent-harness-mcp &
sleep 2
kill %1
```
Expected: starts and terminates cleanly, no import errors, no serena/cognee log lines.

- [ ] **Step 2: Hook smoke tests**

```bash
cd /tmp && mkdir -p smoke-repo && cd smoke-repo && git init -q .
printf 'SECRET=AKIAABCDEFGHIJKLMNOP\n' > .env
printf 'echo hello\n' > script.sh
uv run --project /Users/jonah/dev/agentism/astrojones/servers/harness-mcp python -m repo_agent_harness.agent_hooks pre_tool_use --tool Bash --command "echo hello"   # allowed
uv run --project /Users/jonah/dev/agentism/astrojones/servers/harness-mcp python -m repo_agent_harness.agent_hooks pre_tool_use --tool Read --file_path .env   # denied (secret)
```
Expected: first allowed, second denied by the secret guard. (Verify the actual CLI arg names from `agent_hooks.py` `main()` — adapt the invocation to match.)

- [ ] **Step 3: Repo-state + health tools**

With the server running and a session context set, call `repo_context_overview`, `repo_symbols_overview`, `repo_impact_file`, `repo_health` — all respond with no serena/cognee in output. (If no MCP client is handy, run `uv run repo-agent-harness health` from a test repo via the CLI.)

- [ ] **Step 4: No artifacts**

```bash
find /tmp/smoke-repo -name '.serena' -o -name 'cognee*' | head
grep -rniE 'cognee|serena_gate' /Users/jonah/dev/agentism/astrojones/servers/harness-mcp/repo_agent_harness/ | grep -v symbols.py
```
Expected: no `.serena` dir, no cognee files; no source refs except `symbols.py`'s kept subprocess arg.

- [ ] **Step 5: Version + tag**

```bash
git tag v4.0.0 && git log --oneline -8
```
Expected: 6–7 feature commits since `7f24b78` (Tasks 1–6), tagged `v4.0.0`.

- [ ] **Step 6: Fix anything surfaced; commit**

```bash
git add -A && git commit -m "fix: smoke-test findings"
```
(Only if findings; otherwise skip.)
