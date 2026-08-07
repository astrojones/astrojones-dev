"""Perception daemon: auto-run cheap checks as files change, maintain a repo snapshot.

Lives inside the long-lived MCP server process (one per worktree). The ``RepoWatcher``
feeds change notifications to :meth:`Perception.note_change`; a background :meth:`run`
task debounces them, runs each ``auto``-enabled check (lint/typecheck by default; tests
opt-in) in a worker thread, recomputes git state, and writes a :class:`PerceptionSnapshot`
atomically to ``repo_state_dir(root)/perception.json``. The ``repo_state`` tool (pull) and
the delivery hooks (push) read that file.

Best-effort and fail-open throughout: a perception failure must never crash the server,
block a tool call, or stall the watcher. Checks run via ``anyio.to_thread`` so a slow
language server never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from anyio import to_thread

from repo_agent_harness import git, health, paths, verify
from repo_agent_harness.models import CheckVerdict, GitState, PerceptionSnapshot

if TYPE_CHECKING:
    from collections.abc import Iterable

LOG = logging.getLogger(__name__)

# Only these check kinds are runnable in the background via verify.run_kind; git/ci/command
# auto-running is out of scope for v1 (git state is always computed regardless).
_RUNNABLE_KINDS = {"lint", "typecheck", "test"}
# Quiet window after a change burst before refreshing, on top of the watcher's own debounce —
# coalesces a flurry of edits into a single check pass.
_COALESCE_SECONDS = 0.75


def _summary(data: dict) -> str:
    """One-line summary of a verify.run_kind result."""
    if data.get("skipped"):
        return f"skipped: {str(data.get('output') or '').strip()[:200]}" if data.get("output") else "skipped"
    if data.get("ok"):
        return "passed"
    first = next((ln for ln in str(data.get("output") or "").splitlines() if ln.strip()), "failed")
    return first[:200]


def read_snapshot(root: str) -> PerceptionSnapshot | None:
    """Load the current perception snapshot from disk, or None when absent/unreadable."""
    try:
        return PerceptionSnapshot.model_validate_json(paths.perception_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _git_state(root: str) -> GitState:
    """Snapshot branch/HEAD/dirty/conflicts for transition detection (cheap; safe in a thread)."""
    st = git.status(root)
    return GitState(
        branch=st["branch"],
        head=git.head(root),
        dirty=bool(st["dirty"]),
        conflicted=git.conflicted_files(root),
    )


def current_state(root: str) -> dict:
    """Return the current perception snapshot as a dict for the ``repo_state`` tool.

    Falls back to a git-only baseline (no check verdicts yet) when the daemon has not written
    a snapshot — so ``repo_state`` always answers, even in the brief window before the first run.
    """
    snap = read_snapshot(root)
    if snap is None:
        snap = PerceptionSnapshot(git=_git_state(root), generated_at=datetime.now(UTC).isoformat(timespec="seconds"))
    return snap.model_dump()


class Perception:
    """Owns the per-worktree perception loop: debounce changes, run checks, write the snapshot."""

    def __init__(self, root: str) -> None:
        """Bind to ``root`` (resolved)."""
        self.root = str(Path(root).resolve())
        self._dirty = asyncio.Event()
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self._pending: set[str] = set()
        self._last_run: dict[str, float] = {}
        self._last_runtime_s: dict[str, float] = {}
        self._verdicts: dict[str, CheckVerdict] = {}

    def note_change(self, changed: Iterable[str]) -> None:
        """Record changed paths and wake the run loop. Sync, non-blocking, runs on the loop thread.

        Called from the watcher's callback (same event loop), so touching the asyncio
        primitives here is safe; it must stay fast so the watch loop never stalls.
        """
        self._pending |= set(changed)
        self._dirty.set()

    def stop(self) -> None:
        """Signal the run loop to exit (also wakes it so it can observe the stop)."""
        self._stop.set()
        self._dirty.set()

    async def run(self) -> None:
        """Background loop: take a baseline snapshot, then refresh on each debounced change burst."""
        await self._safe_refresh()  # baseline so repo_state has git state from session one
        while not self._stop.is_set():
            await self._dirty.wait()
            if self._stop.is_set():
                break
            self._dirty.clear()
            await asyncio.sleep(_COALESCE_SECONDS)  # coalesce a burst into one pass
            self._pending.clear()
            await self._safe_refresh()

    async def _safe_refresh(self) -> None:
        """Run one refresh, swallowing any failure (fail-open: never crash the daemon)."""
        try:
            await self._refresh()
        except Exception:  # noqa: BLE001 — a perception failure must never propagate
            LOG.warning("perception refresh failed for %s", self.root, exc_info=True)

    async def _refresh(self) -> None:
        """Run every due auto-check, recompute git state, and write the snapshot atomically."""
        async with self._lock:
            cfg = await to_thread.run_sync(health.load_config, self.root)
            now = time.time()
            for check in cfg.checks:
                if not (check.enabled and check.auto and check.kind in _RUNNABLE_KINDS):
                    continue
                if not self._due(check.id, check.min_interval_s, check.adaptive_factor, now):
                    continue
                started = time.monotonic()
                data = await to_thread.run_sync(verify.run_kind, self.root, check.kind)
                runtime = time.monotonic() - started
                ran_at = time.time()
                self._last_run[check.id] = ran_at
                self._last_runtime_s[check.id] = runtime
                self._verdicts[check.id] = CheckVerdict(
                    id=check.id,
                    kind=check.kind,
                    ok=None if data.get("skipped") else bool(data.get("ok")),
                    summary=_summary(data),
                    command=data.get("command"),
                    ran_at=ran_at,
                    runtime_ms=int(runtime * 1000),
                )
            snapshot = PerceptionSnapshot(
                verdicts=[self._verdicts[k] for k in sorted(self._verdicts)],
                git=await to_thread.run_sync(_git_state, self.root),
                generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            )
            await to_thread.run_sync(self._write, snapshot)

    def _due(self, check_id: str, min_interval_s: float, adaptive_factor: float, now: float) -> bool:
        """True when ``check_id``'s adaptive interval has elapsed (always True on first run).

        Effective interval = max(min_interval_s, adaptive_factor * last_runtime) so a slow
        check throttles itself proportionally to how long it actually takes to run.
        """
        last = self._last_run.get(check_id)
        if last is None:
            return True
        interval = max(min_interval_s, adaptive_factor * self._last_runtime_s.get(check_id, 0.0))
        return (now - last) >= interval

    def _write(self, snapshot: PerceptionSnapshot) -> None:
        """Atomically write the snapshot (temp + os.replace) so readers never see a partial file."""
        target = paths.perception_file(self.root)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        Path(tmp).replace(target)
