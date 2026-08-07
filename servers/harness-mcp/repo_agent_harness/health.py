"""Configurable repository health: declarative checks over the shared core.

Checks are declared in ``agent/health.yml`` (agent-editable, like the policies)
and define what "healthy" means for the repo. Built-in kinds reuse the
verify/git cores; ``command`` runs a custom argv list (shell-policy gated);
``ci`` (opt-in, network) asks ``gh`` for the latest workflow run.

Snapshots are cached per repo root with provenance (fresh vs cache) and a
staleness probe over ``git status --porcelain`` so cached reads stay honest.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from repo_agent_harness import git, paths, policies, shell, verify
from repo_agent_harness.models import (
    CheckResult,
    HealthCheckConfig,
    HealthConfig,
    HealthSnapshot,
    HookHeartbeat,
)

# Optional dependency: keep the package importable in minimal (hook) environments.
yaml = importlib.import_module("yaml") if importlib.util.find_spec("yaml") else None

CACHE_TTL_SECONDS = 300
_MAX_OUTPUT = 4000


# ----------------------------------------------------------------------------- config


def load_config(root: str) -> HealthConfig:
    """Load health.yml from config resolution chain, falling back to built-in defaults."""
    from repo_agent_harness.paths import harness_home, repo_id  # noqa: PLC0415

    h = harness_home()
    rid = repo_id(root)
    candidates = [
        h / "repos" / rid / "health.yml",
        h / "harness-health.yml",
        Path(__file__).parent / "defaults" / "health.yml",
    ]
    if yaml is None:
        return HealthConfig()
    for path in candidates:
        if path.is_file():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                return HealthConfig.model_validate(data)
            except (yaml.YAMLError, ValidationError) as exc:
                return HealthConfig(config_error=f"{path.name} invalid, using defaults: {exc}")
    return HealthConfig()


# ----------------------------------------------------------------------------- runners


def _from_verify(root: str, cfg: HealthCheckConfig) -> CheckResult:
    """Adapt a verify.run_kind result (lint/typecheck/test) into a CheckResult."""
    data = verify.run_kind(root, cfg.kind)
    skipped = bool(data.get("skipped"))
    return CheckResult(
        id=cfg.id,
        kind=cfg.kind,
        ok=None if skipped else bool(data.get("ok")),
        skipped=skipped,
        summary=f"via {data.get('via')}",
        output=shell.truncate(str(data.get("output") or ""), _MAX_OUTPUT),
        command=data.get("command"),
    )


def _git_check(root: str, cfg: HealthCheckConfig) -> CheckResult:
    """Worktree state: branch, dirty flag, ahead/behind upstream, merge conflicts."""
    st = git.status(root)
    conflicts = git.conflicted_files(root)
    parts = [f"branch {st['branch']}", "dirty" if st["dirty"] else "clean"]
    ab = git.ahead_behind(root)
    if ab is not None:
        parts.append(f"ahead {ab[0]}, behind {ab[1]}")
    if conflicts:
        parts.append(f"{len(conflicts)} conflicted file(s)")
    return CheckResult(
        id=cfg.id,
        kind=cfg.kind,
        ok=not conflicts,
        summary="; ".join(parts),
        output="\n".join(conflicts),
    )


def _command_check(root: str, cfg: HealthCheckConfig) -> CheckResult:
    """Run a custom argv-list command, gated by the repo's shell policy."""
    if not cfg.command:
        return CheckResult(id=cfg.id, kind=cfg.kind, skipped=True, summary="no command configured")
    cmdline = " ".join(cfg.command)
    decision = policies.check_command(cmdline, root)
    if not decision.allowed or decision.requires_confirmation:
        return CheckResult(
            id=cfg.id,
            kind=cfg.kind,
            skipped=True,
            command=cmdline,
            summary=f"refused by shell policy: {decision.reason}",
        )
    res = shell.run(cfg.command, cwd=root, timeout=cfg.timeout, max_chars=_MAX_OUTPUT)
    return CheckResult(
        id=cfg.id,
        kind=cfg.kind,
        ok=res.ok,
        summary="passed" if res.ok else ("timed out" if res.timed_out else f"exit {res.code}"),
        output=(res.stdout or res.stderr).strip(),
        command=cmdline,
    )


def _ci_check(root: str, cfg: HealthCheckConfig) -> CheckResult:
    """Latest workflow-run status on the configured (or current) branch via gh. Network."""
    if not shell.which("gh"):
        return CheckResult(id=cfg.id, kind=cfg.kind, skipped=True, summary="gh not available")
    branch = cfg.branch or git.status(root)["branch"]
    cmd = ["gh", "run", "list", "--branch", branch, "--limit", "1", "--json", "status,conclusion,headSha"]
    res = shell.run(cmd, cwd=root, timeout=cfg.timeout, max_chars=_MAX_OUTPUT)
    if not res.ok:
        return CheckResult(
            id=cfg.id,
            kind=cfg.kind,
            skipped=True,
            command=" ".join(cmd),
            summary=f"gh failed: {(res.stderr or res.stdout).strip()[:200]}",
        )
    try:
        runs = json.loads(res.stdout or "[]")
    except ValueError:
        runs = []
    if not runs:
        return CheckResult(id=cfg.id, kind=cfg.kind, skipped=True, summary=f"no workflow runs on {branch}")
    latest = runs[0]
    if latest.get("status") != "completed":
        return CheckResult(
            id=cfg.id,
            kind=cfg.kind,
            ok=None,
            command=" ".join(cmd),
            summary=f"CI {latest.get('status')} on {branch} ({latest.get('headSha', '')[:7]})",
        )
    conclusion = latest.get("conclusion")
    return CheckResult(
        id=cfg.id,
        kind=cfg.kind,
        ok=conclusion == "success",
        command=" ".join(cmd),
        summary=f"CI {conclusion} on {branch} ({latest.get('headSha', '')[:7]})",
    )


_RUNNERS = {
    "lint": _from_verify,
    "typecheck": _from_verify,
    "test": _from_verify,
    "git": _git_check,
    "command": _command_check,
    "ci": _ci_check,
}


def _run_check(root: str, cfg: HealthCheckConfig) -> CheckResult:
    """Dispatch one check to its runner and stamp its duration."""
    start = time.monotonic()
    result = _RUNNERS[cfg.kind](root, cfg)
    return result.model_copy(update={"duration_ms": int((time.monotonic() - start) * 1000)})


# ------------------------------------------------------------------------------ cache


@dataclass
class _CacheEntry:
    snapshot: HealthSnapshot
    status_hash: str
    monotonic: float
    dirty: bool = False


_CACHE: dict[str, _CacheEntry] = {}


_CACHE_LOCKS: dict[str, threading.Lock] = {}
_CACHE_LOCKS_GUARD = threading.Lock()


def _lock_for(root: str) -> threading.Lock:
    """Return the per-root cache lock, creating it once under the meta-lock."""
    with _CACHE_LOCKS_GUARD:
        lock = _CACHE_LOCKS.get(root)
        if lock is None:
            lock = threading.Lock()
            _CACHE_LOCKS[root] = lock
        return lock


def _status_hash(root: str) -> str:
    res = shell.run(["git", "status", "--porcelain"], cwd=root, timeout=15)
    return hashlib.sha256(res.stdout.encode("utf-8")).hexdigest()


def invalidate(root: str, paths: set[str] | None = None) -> None:
    """Mark the cached snapshot for ``root`` stale (the file watcher's interface)."""
    _ = paths  # reserved: per-path invalidation granularity
    entry = _CACHE.get(root)
    if entry is not None:
        entry.dirty = True


def cached(root: str) -> HealthSnapshot | None:
    """Return the cached snapshot with an honest stale flag, or None. Never runs checks."""
    entry = _CACHE.get(root)
    if entry is None:
        return None
    stale = entry.dirty or _status_hash(root) != entry.status_hash
    return entry.snapshot.model_copy(update={"provenance": "cache", "stale": stale})


# -------------------------------------------------------------------------------- run


def _fresh_cache_hit(root: str, refresh: bool, only: str | None) -> HealthSnapshot | None:
    """Return the cached snapshot when it is still trustworthy, else None."""
    if refresh or only is not None:
        return None
    entry = _CACHE.get(root)
    if entry is None or entry.dirty or time.monotonic() - entry.monotonic >= CACHE_TTL_SECONDS:
        return None
    if _status_hash(root) != entry.status_hash:
        return None
    return entry.snapshot.model_copy(update={"provenance": "cache", "stale": False})


def _hook_heartbeats(root: str) -> list[HookHeartbeat]:
    """Surface per-event hook/job heartbeats so a silently dead hook shim is visible.

    Every wired event appears explicitly — ``last_success_at=None`` is the "never ran"
    signal the fail-open shims cannot give any other way. Extra stamps (async jobs like
    memify) ride along, sorted by event name. Purely informational: never affects
    ``snapshot.ok`` and degrades to the never-list on any read failure.
    """
    try:
        beats = paths.read_hook_heartbeats(root)
    except Exception:  # noqa: BLE001 - heartbeat trouble must never crash a health snapshot
        beats = {}
    now = time.time()
    entries: list[HookHeartbeat] = []
    for event in sorted(set(paths.HOOK_EVENTS) | set(beats)):
        beat = beats.get(event)
        if beat is None:
            entries.append(HookHeartbeat(event=event))
            continue
        entries.append(
            HookHeartbeat(
                event=event,
                last_success_at=datetime.fromtimestamp(beat["ts"], UTC).isoformat(timespec="seconds"),
                age_s=round(max(0.0, now - beat["ts"]), 3),
                count=beat["count"],
            )
        )
    return entries


def _compute_snapshot(
    root: str,
    only: str | None,
) -> HealthSnapshot:
    """Run the selected checks and cache the snapshot (caller holds the per-root lock)."""
    status_hash = _status_hash(root)
    cfg = load_config(root)
    selected = [c for c in cfg.checks if c.enabled and (only is None or c.id == only)]
    if only is not None and not selected:
        known = ", ".join(c.id for c in cfg.checks)
        results = [CheckResult(id=only, kind="unknown", skipped=True, summary=f"no such check id; known: {known}")]
    else:
        results = [_run_check(root, c) for c in selected]
    snapshot = HealthSnapshot(
        ok=not any(r.ok is False for r in results),
        checks=results,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        git_head=git.head(root),
        provenance="fresh",
        config_error=cfg.config_error,
        hook_heartbeats=_hook_heartbeats(root),
    )
    if only is None:
        _CACHE[root] = _CacheEntry(snapshot=snapshot, status_hash=status_hash, monotonic=time.monotonic())
    return snapshot


def run(
    root: str,
    *,
    only: str | None = None,
    refresh: bool = False,
) -> HealthSnapshot:
    """Produce a repository health snapshot from the repo's declarative checks.

    Args:
        root: Repository root directory.
        only: Run a single check by id (bypasses the cache, result not cached).
        refresh: Force a re-run even when a fresh cached snapshot exists.

    Returns:
        A HealthSnapshot; ok is False only when an executed check failed.
    """
    hit = _fresh_cache_hit(root, refresh, only)
    if hit is not None:
        return hit
    with _lock_for(root):
        # Double-check under the lock: a sibling caller may have filled the cache
        # while we waited, so we must not relaunch the (expensive) check suite.
        hit = _fresh_cache_hit(root, refresh, only)
        if hit is not None:
            return hit
        return _compute_snapshot(root, only)
