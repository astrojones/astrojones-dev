"""Tests for the `repo-agent-harness hook <event>` CLI (Claude Code hook handlers)."""

import io
import json

from repo_agent_harness import agent_hooks, cli


def _run(payload, repo, monkeypatch, capsys, raw=None, event="pre-tool-use"):
    monkeypatch.chdir(repo)
    text = raw if raw is not None else json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    rc = cli.main(["hook", event])
    return rc, json.loads(capsys.readouterr().out)


def test_pre_denies_rm_rf(repo, monkeypatch, capsys):
    rc, out = _run({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}, repo, monkeypatch, capsys)
    assert rc == 0
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pre_allows_git_status(repo, monkeypatch, capsys):
    rc, out = _run({"tool_name": "Bash", "tool_input": {"command": "git status"}}, repo, monkeypatch, capsys)
    assert rc == 0
    assert out == {}


def test_pre_denies_secret_read(repo, monkeypatch, capsys):
    payload = {"tool_name": "Read", "tool_input": {"file_path": str(repo / ".env")}}
    rc, out = _run(payload, repo, monkeypatch, capsys)
    assert rc == 0
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pre_fails_open_on_garbage(repo, monkeypatch, capsys):
    rc, out = _run(None, repo, monkeypatch, capsys, raw="not json at all")
    assert rc == 0
    assert out == {}


def test_hook_fails_open_outside_repo(tmp_path, monkeypatch, capsys):
    payload = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
    rc, out = _run(payload, tmp_path, monkeypatch, capsys)
    assert rc == 0
    assert out == {}


def test_post_nudges_on_edit(repo, monkeypatch, capsys):
    rc, out = _run({"tool_name": "Edit", "tool_input": {}}, repo, monkeypatch, capsys, event="post-tool-use")
    assert rc == 0
    assert "verify" in out["hookSpecificOutput"]["additionalContext"].lower()


def test_post_quiet_on_read(repo, monkeypatch, capsys):
    rc, out = _run({"tool_name": "Read", "tool_input": {}}, repo, monkeypatch, capsys, event="post-tool-use")
    assert rc == 0
    assert out == {}


def _write_snapshot(repo, snap: dict) -> None:
    from repo_agent_harness import paths

    paths.perception_file(str(repo)).write_text(json.dumps(snap), encoding="utf-8")


def test_post_quiet_when_perception_green(repo, monkeypatch, capsys):
    _write_snapshot(repo, {"verdicts": [{"id": "lint", "kind": "lint", "ok": True, "summary": "passed"}], "git": {}})
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(repo / "src" / "payment.py")}}
    rc, out = _run(payload, repo, monkeypatch, capsys, event="post-tool-use")
    assert rc == 0
    assert out == {}  # green snapshot -> no nag (perception is handling verification)


def test_post_warns_when_perception_red(repo, monkeypatch, capsys):
    _write_snapshot(repo, {"verdicts": [{"id": "lint", "kind": "lint", "ok": False, "summary": "E501"}], "git": {}})
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(repo / "src" / "payment.py")}}
    rc, out = _run(payload, repo, monkeypatch, capsys, event="post-tool-use")
    assert rc == 0
    assert "lint" in out["hookSpecificOutput"]["additionalContext"]


def test_post_records_touched_and_nudges_without_snapshot(repo, monkeypatch, capsys):
    from repo_agent_harness import paths

    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(repo / "src" / "payment.py")}}
    rc, out = _run(payload, repo, monkeypatch, capsys, event="post-tool-use")
    assert rc == 0
    assert "verify" in out["hookSpecificOutput"]["additionalContext"].lower()  # no snapshot -> legacy nudge
    touched = json.loads(paths.perception_touched_file(str(repo)).read_text())
    assert "src/payment.py" in touched


def test_user_prompt_submit_reports_failure_then_silent(repo, monkeypatch, capsys):
    _write_snapshot(
        repo,
        {"verdicts": [{"id": "lint", "kind": "lint", "ok": False, "summary": "E501"}], "git": {"branch": "main"}},
    )
    rc1, out1 = _run({}, repo, monkeypatch, capsys, event="user-prompt-submit")
    assert rc1 == 0
    assert "FAILING" in out1["hookSpecificOutput"]["additionalContext"]
    # same snapshot, second turn: already surfaced -> no re-nag
    _rc2, out2 = _run({}, repo, monkeypatch, capsys, event="user-prompt-submit")
    assert out2 == {}


def test_user_prompt_submit_silent_when_green(repo, monkeypatch, capsys):
    _write_snapshot(repo, {"verdicts": [{"id": "lint", "kind": "lint", "ok": True}], "git": {"branch": "main"}})
    rc, out = _run({}, repo, monkeypatch, capsys, event="user-prompt-submit")
    assert rc == 0
    assert out == {}


def test_perception_deltas_branch_switch():
    cur = {"verdicts": [], "git": {"branch": "feature", "head": "b", "conflicted": []}}
    last = {"verdicts": [], "git": {"branch": "main", "head": "a", "conflicted": []}}
    assert any("branch switched" in line for line in agent_hooks._perception_deltas(cur, last))


def test_perception_deltas_recovery():
    cur = {"verdicts": [{"id": "lint", "kind": "lint", "ok": True}], "git": {}}
    last = {"verdicts": [{"id": "lint", "kind": "lint", "ok": False}], "git": {}}
    assert any("recovered" in line for line in agent_hooks._perception_deltas(cur, last))


def test_perception_deltas_new_conflict():
    cur = {"verdicts": [], "git": {"conflicted": ["a.py"]}}
    last = {"verdicts": [], "git": {"conflicted": []}}
    assert any("conflict" in line for line in agent_hooks._perception_deltas(cur, last))


# --------------------------------------------------------------- session-start


def _ctx(out):
    return out.get("hookSpecificOutput", {}).get("additionalContext", "")


# ------------------------------------------------------------------- dispatch & heartbeats


def test_dispatch_stamps_heartbeat_on_success(repo, monkeypatch):
    from repo_agent_harness import paths

    monkeypatch.chdir(repo)
    out = agent_hooks.dispatch("post-tool-use", {})
    assert out == {}
    assert "post-tool-use" in paths.read_hook_heartbeats(str(repo))


def test_dispatch_does_not_stamp_when_handler_raises(repo, monkeypatch, capsys):
    from repo_agent_harness import paths

    def boom(data, root=None):
        msg = "handler died"
        raise RuntimeError(msg)

    monkeypatch.setitem(agent_hooks._HANDLERS, "post-tool-use", boom)
    rc, out = _run({}, repo, monkeypatch, capsys, event="post-tool-use")
    assert rc == 0
    assert out == {}  # fail-open decision intact
    assert "post-tool-use" not in paths.read_hook_heartbeats(str(repo))


def test_dispatch_stamp_failure_never_alters_decision(repo, monkeypatch):
    def boom(root, event):
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.chdir(repo)
    monkeypatch.setattr(agent_hooks.paths, "stamp_hook_heartbeat", boom)
    out = agent_hooks.dispatch("pre-tool-use", {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_dispatch_unknown_event_defaults_to_pre_tool_use(repo, monkeypatch):
    from repo_agent_harness import paths

    monkeypatch.chdir(repo)
    out = agent_hooks.dispatch("bogus-event", {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    beats = paths.read_hook_heartbeats(str(repo))
    assert "bogus-event" not in beats  # free-form typos must not pollute the heartbeat list
    assert "pre-tool-use" in beats


def test_cli_hook_delegates_to_dispatch(repo, monkeypatch, capsys):
    """`repo-agent-harness hook post-tool-use` stamps the heartbeat — proof the CLI routes via dispatch."""
    from repo_agent_harness import paths

    rc, out = _run({}, repo, monkeypatch, capsys, event="post-tool-use")
    assert rc == 0
    assert out == {}
    assert "post-tool-use" in paths.read_hook_heartbeats(str(repo))


def test_module_main_delegates_to_dispatch(repo, monkeypatch, capsys):
    """`python -m repo_agent_harness.agent_hooks post-tool-use` stamps too (the lightweight entry)."""
    from repo_agent_harness import paths

    monkeypatch.chdir(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    rc = agent_hooks.main(["post-tool-use"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {}
    assert "post-tool-use" in paths.read_hook_heartbeats(str(repo))


# ------------------------------------------------------------------- session-start hook degradation


def _stamp(root, event, n=1):
    from repo_agent_harness import paths

    for _ in range(n):
        paths.stamp_hook_heartbeat(root, event)


def _unconfigured_client():
    return None


def test_session_start_degradation_silent_on_fresh_install(repo, monkeypatch):
    """No session-start history yet (fresh install) -> never warn about missing beats."""
    monkeypatch.chdir(repo)
    out = agent_hooks.session_start({})
    assert "Hook heartbeat warning" not in _ctx(out)


def test_session_start_warns_on_never_stamped_hooks(repo, monkeypatch):
    monkeypatch.chdir(repo)
    _stamp(str(repo), "session-start", n=3)
    ctx = _ctx(agent_hooks.session_start({}))
    (line,) = [ln for ln in ctx.splitlines() if "Hook heartbeat warning" in ln]  # one compact line
    for ev in ("pre-tool-use", "post-tool-use", "user-prompt-submit"):
        assert ev in line
    assert "session-start" not in line


def test_session_start_warns_on_stale_single_event(repo, monkeypatch):
    import time

    from repo_agent_harness import paths

    monkeypatch.chdir(repo)
    root = str(repo)
    _stamp(root, "session-start", n=3)
    for ev in ("pre-tool-use", "user-prompt-submit"):
        _stamp(root, ev)
    stale_ts = time.time() - 8 * 24 * 3600  # older than 7d AND older than the session-start stamp
    paths.hook_heartbeat_file(root, "post-tool-use").write_text(
        json.dumps({"ts": stale_ts, "count": 4}), encoding="utf-8"
    )
    ctx = _ctx(agent_hooks.session_start({}))
    (line,) = [ln for ln in ctx.splitlines() if "Hook heartbeat warning" in ln]
    assert "post-tool-use" in line
    assert "pre-tool-use" not in line
    assert "user-prompt-submit" not in line
