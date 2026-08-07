# Agent guide — __REPO_NAME__

<!-- repo-agent-harness:section:begin -->
## Working in this repo (repo-agent-harness)

This repository carries the **repo-agent-harness**: safe, deterministic, repo-aware
tooling for any coding agent. One MCP server (wired in `.mcp.json`) provides everything —
deterministic `repo_*` tools for repo facts, symbol navigation, and precise range reads.
Agents without an MCP client use the same operations as CLI tools under `agent/tools/`.

### First, in a new session
- **The harness is ready immediately.** The bundled server connects at session start; just
  orient with `repo_context_overview` and start navigating by symbol — no manual bootstrap
  call is required.

### Navigation & reading
- Use **`repo_symbols_overview`** first for symbols: names/kinds/nesting from the static
  tree-sitter index (instant, no LSP launch). Locate definitions and references with native
  search (`Grep`, `repo_search_text`) and precise reads.
- Use the **repo-agent-harness** tools for repo facts: `repo_context_overview`,
  `repo_context_status`, `repo_context_relevant_files`, `repo_search_text`, `repo_search_files`.
- **Read precise ranges** with `repo_read_range`. Never recursively read the repo or dump whole files.
- **In Claude Code:** to map an unfamiliar or multi-file region, dispatch the **`explorer`** subagent — it runs this same harness navigation read-only and hands back a cited reading list instead of flooding the session. It is the harness-native replacement for the generic built-in `Explore` agent; prefer it for any code exploration.

### Repo health
- `repo_health` reports what "healthy" means for this repo — lint/typecheck/tests for changed
  files, worktree state, LSP diagnostics, optional CI status. Configure it in `agent/health.yml`
  (add custom `command` checks; enable the `ci` check if network use is acceptable).

### Before editing
- Identify the relevant files (`repo_context_relevant_files` + `repo_symbols_overview`; in Claude Code, the `explorer` subagent does this read-only and returns a reading list).
- For cross-file changes, run `repo_impact_file` and note the risk level. If risk is "high"
  (auth/payments/migrations/security/schema), confirm the plan first.

### After editing
- Run `agent/tools/safe-diff` and `repo_verify_changed` — lint/typecheck/test for the changed files only.

### Shell discipline
- Prefer the harness tools and `agent/tools/*` over raw shell.
- Destructive commands, secret-file reads, and `curl … | sh` are **blocked** by policy
  (`agent/policies/shell.yml`).
- `git push`, `git reset --hard`, and database migrations **require confirmation**.

### Local tools (`agent/tools/`, all support `--json`)
`repo-overview` · `safe-diff` · `impact <path>` · `lint-changed` · `typecheck-changed` · `test-changed` · `health`

Tune `agent/policies/*.yml`, `agent/health.yml`, and `agent/manifest.yml` for this repo.
<!-- repo-agent-harness:section:end -->
