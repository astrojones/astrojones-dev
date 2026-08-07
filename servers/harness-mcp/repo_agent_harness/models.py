"""Pydantic models: MCP tool inputs and the repo-health subsystem."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RelevantFilesIn(BaseModel):
    """Input model for repo_context_relevant_files."""

    task: str = Field(..., description="Natural-language description of the task")
    max_files: int = Field(8, ge=1, le=50)


class SearchTextIn(BaseModel):
    """Input model for repo_search_text."""

    pattern: str = Field(..., description="Substring or ripgrep pattern")
    paths: list[str] | None = Field(None, description="Optional path scope")
    limit: int = Field(20, ge=1, le=200)


class SearchFilesIn(BaseModel):
    """Input model for repo_search_files."""

    pattern: str = Field(..., description="Glob, e.g. '*.py' or 'src/*'")
    limit: int = Field(20, ge=1, le=200)


class ReadRangeIn(BaseModel):
    """Input model for repo_read_range."""

    path: str = Field(..., description="Repo-relative file path")
    start_line: int = Field(1, ge=1)
    end_line: int = Field(200, ge=1)


class ImpactIn(BaseModel):
    """Input model for repo_impact_file."""

    path: str = Field(..., description="Repo-relative file path")


class VerifyIn(BaseModel):
    """Input model for repo_verify_changed."""

    mode: str = Field("auto", description="Verification mode")


class DiffIn(BaseModel):
    """Input model for repo_diff_current."""

    context_lines: int = Field(3, ge=0, le=10)


class CheckCommandIn(BaseModel):
    """Input model for repo_policy_check_command."""

    command: str = Field(..., description="The shell command to evaluate against policy")


CheckKind = Literal["lint", "typecheck", "test", "git", "ci", "command"]


class HealthCheckConfig(BaseModel):
    """One declarative health check from agent/health.yml.

    The ``auto``/``min_interval_s``/``adaptive_factor`` trio governs the perception
    daemon (perception.py), which auto-runs ``auto=True`` checks in the background as
    files change. The effective minimum gap between runs is
    ``max(min_interval_s, adaptive_factor * last_runtime_s)`` so a slow check (a big
    test suite) throttles itself proportionally to how long it actually takes, while a
    fast check (lint) stays responsive. These fields are inert for ``repo_health`` /
    ``repo_verify_changed``, which always run on demand.
    """

    id: str
    kind: CheckKind
    enabled: bool = True
    command: list[str] | None = Field(None, description="argv list for kind=command (never a shell string)")
    timeout: int = Field(120, ge=1, le=600)
    branch: str | None = Field(None, description="branch for kind=ci; defaults to the current branch")
    auto: bool = Field(False, description="auto-run this check in the background as files change (perception daemon)")
    min_interval_s: float = Field(0, ge=0, description="hard floor on seconds between background auto-runs")
    adaptive_factor: float = Field(
        0, ge=0, description="background min interval also >= adaptive_factor * the check's last runtime"
    )


def _default_checks() -> list[HealthCheckConfig]:
    # lint/typecheck are cheap and pure -> auto-run them in the background (perception);
    # tests can have side effects and cost, so they stay opt-in (auto=False) per repo.
    return [
        HealthCheckConfig(id="lint", kind="lint", auto=True, adaptive_factor=8),
        HealthCheckConfig(id="typecheck", kind="typecheck", auto=True, adaptive_factor=8),
        HealthCheckConfig(id="tests", kind="test"),
        HealthCheckConfig(id="worktree", kind="git"),
        HealthCheckConfig(id="ci", kind="ci", enabled=False),
    ]


class HealthConfig(BaseModel):
    """The repo's health-check configuration (agent/health.yml), with safe defaults."""

    version: int = 1
    checks: list[HealthCheckConfig] = Field(default_factory=_default_checks)
    config_error: str | None = Field(None, description="set when agent/health.yml failed to parse")


# --------------------------------------------------------------------------- perception


class CheckVerdict(BaseModel):
    """The latest background result of one auto-run check (perception daemon)."""

    id: str
    kind: CheckKind
    ok: bool | None = Field(None, description="True pass, False fail, None skipped/never-run")
    summary: str = ""
    command: str | None = None
    ran_at: float = Field(0, description="epoch seconds when this verdict was produced")
    runtime_ms: int = 0


class GitState(BaseModel):
    """A point-in-time view of the worktree's git state, for transition detection."""

    branch: str = ""
    head: str = Field("", description="short HEAD sha")
    dirty: bool = False
    conflicted: list[str] = Field(default_factory=list, description="files with merge conflicts")


class PerceptionSnapshot(BaseModel):
    """The harness's current perception of the repo, maintained by the perception daemon.

    Written atomically to ``repo_state_dir(root)/perception.json`` whenever the daemon
    refreshes it; read by the ``repo_state`` tool (pull) and the delivery hooks (push).
    """

    verdicts: list[CheckVerdict] = Field(default_factory=list)
    git: GitState = Field(default_factory=GitState)
    generated_at: str = Field("", description="ISO-8601 UTC timestamp of this snapshot")


class CheckResult(BaseModel):
    """Outcome of one health check; ok=None means skipped/unavailable."""

    id: str
    kind: str
    ok: bool | None = None
    skipped: bool = False
    summary: str = ""
    output: str = ""
    command: str | None = None
    duration_ms: int = 0


class HookHeartbeat(BaseModel):
    """Last successful run of one Claude Code hook event (or async job like memify).

    ``last_success_at is None`` means "never ran" — surfaced explicitly because the hook
    shims fail open by contract, so a silently dead hook leaves no other trace. ``count``
    is best-effort/lossy (see paths.stamp_hook_heartbeat); only ts/existence is contractual.
    """

    event: str
    last_success_at: str | None = Field(None, description="ISO-8601 UTC timestamp; None = never ran")
    age_s: float | None = None
    count: int = 0


class HealthSnapshot(BaseModel):
    """A repository health snapshot with freshness provenance."""

    ok: bool
    checks: list[CheckResult]
    generated_at: str = Field(..., description="ISO-8601 UTC timestamp of the run")
    git_head: str = Field("", description="short HEAD sha at run time")
    provenance: Literal["fresh", "cache"] = "fresh"
    stale: bool = Field(False, description="True when the worktree changed since this snapshot was generated")
    config_error: str | None = None
    hook_heartbeats: list[HookHeartbeat] = Field(
        default_factory=list, description="per-hook-event last-success stamps; last_success_at=None means never ran"
    )
