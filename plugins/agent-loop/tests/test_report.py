import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import report  # noqa: E402


def line(t, mid, model, usage, kind="assistant"):
    return json.dumps({"type": kind, "timestamp": t, "message": {"id": mid, "model": model, "usage": usage}})


def usage(inp, out, read=0, w5=0, w1=0):
    return {
        "input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
        "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1},
    }


class ReportTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=".")
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.addCleanup(setattr, report, "CONFIG", report.CONFIG)
        report.CONFIG = self.tmp
        self.proj = self.tmp / "projects" / "p"
        self.sub = self.proj / "sess" / "subagents"
        self.sub.mkdir(parents=True)
        self.run = self.tmp / "repo" / ".agent-loop" / "42"
        self.run.mkdir(parents=True)
        (self.run / "run.json").write_text(json.dumps(
            {"base": "main", "sessions": [{"id": "sess", "start": "2026-01-01T10:00:00+00:00"}], "rate_limits": None}))

    def agent(self, aid, agent_type, lines):
        (self.sub / f"agent-{aid}.meta.json").write_text(json.dumps({"agentType": agent_type}))
        (self.sub / f"agent-{aid}.jsonl").write_text("\n".join(lines))

    def test_report(self):
        (self.proj / "sess.jsonl").write_text("\n".join([
            line("2026-01-01T09:00:00Z", "old", "claude-haiku-5-5", usage(1_000_000, 0)),  # before the run
            line("2026-01-01T10:00:01Z", "m1", "claude-haiku-5-5", usage(1_000_000, 0)),  # over 100K: tier 2
        ]))
        self.agent("a", "agent-loop:planner", [
            line("2026-01-01T10:01:00Z", "p1", "claude-fable-5-2", usage(999, 999)),  # superseded by next line
            line("2026-01-01T10:02:05Z", "p1", "claude-fable-5-2", usage(1_000_000, 100_000, read=1_000_000, w5=1_000_000)),
        ])
        self.agent("b", "agent-loop:reviewer", [line("2026-01-01T10:05:00Z", "r1", "claude-opus-5-5", usage(0, 1_000_000))])
        self.agent("c", "general-purpose", [line("2026-01-01T10:06:00Z", "x", "claude-opus-5-5", usage(5, 5))])
        self.agent("d", "agent-loop:executor", [line("2026-01-01T09:30:00Z", "e0", "claude-sonnet-5-5", usage(5, 5))])  # earlier run
        (self.run / "review-1.md").write_text("VERDICT: DONE\n")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report.report(SimpleNamespace(dir=str(self.run), outcome="done"))
        out = buf.getvalue()

        self.assertIn("issue #42", out)
        # planner: 8 input + 4 output + 0.2 cache read + 10 cache write
        self.assertIn("| 1 | planner 1 | claude-fable-5-2 | 10:01:00 | 1m 05s |  | 1,000,000 | 1,000,000 | 1,000,000 | 100,000 | $22.20 |", out)
        self.assertIn("| 2 | reviewer 1 | claude-opus-5-5 | 10:05:00 | 0m 00s | DONE |", out)
        self.assertIn("| dispatcher | - | 1,000,000 | 0 | 0 | 0 | $0.500 |", out)
        self.assertNotIn("executor", out)
        self.assertTrue(out.strip().endswith("Total: $42.70 API-equivalent, 5,100,000 tokens, 2 agent calls, outcome done"))

    def test_unknown_model_has_no_cost(self):
        (self.proj / "sess.jsonl").write_text(line("2026-01-01T10:00:01Z", "m1", "claude-future-9", usage(10, 10)))
        calls = report.collect(json.loads((self.run / "run.json").read_text()), {})
        self.assertIsNone(calls[0]["cost"])

    def test_plan_usage_skips_reset_window(self):
        (self.tmp / "agent-loop-statusline.json").write_text(json.dumps({"rate_limits": {
            "five_hour": {"used_percentage": 30, "resets_at": 2}, "seven_day": {"used_percentage": 12.5, "resets_at": 9}}}))
        before = {"five_hour": {"used_percentage": 90, "resets_at": 1}, "seven_day": {"used_percentage": 10, "resets_at": 9}}
        self.assertEqual(report.plan_usage(before), ["7d +2.5%"])

    def test_copilot_report(self):
        def event(time, kind, agent=None, **data):
            e = {"type": kind, "timestamp": f"2026-01-01T{time}Z", "data": data}
            if agent:
                e["agentId"] = agent
            return json.dumps(e)

        log = self.tmp / "session-state" / "sess" / "events.jsonl"
        log.parent.mkdir(parents=True)
        log.write_text("\n".join([
            event("09:59:58", "tool.execution_start", toolName="task", toolCallId="old"),
            event("09:59:59", "session.usage_record", usage={"inputTokens": 9999, "cost": 100}),
            event("10:00:00", "subagent.started", "old", agentName="planner", toolCallId="old"),
            event("10:00:01", "session.usage_record", usage={"model": "claude-haiku-5.5",
                                                              "reasoningEffort": "low", "inputTokens": 100,
                                                              "cacheReadTokens": 75, "outputTokens": 10, "cost": 0.25}),
            event("10:01:00", "tool.execution_start", toolName="task", toolCallId="p"),
            event("10:01:01", "subagent.started", "a", agentName="agent-loop:planner", toolCallId="p", model="gpt-6.2-astra"),
            event("10:01:20", "session.usage_record", "a", usage={"parentToolCallId": "p", "initiator": "sub-agent",
                  "inputTokens": 200, "cacheReadTokens": 120, "cacheWriteTokens": 50, "outputTokens": 20,
                  "reasoningTokens": 5, "reasoningEffort": "medium", "cost": 1}),
            event("10:01:50", "session.usage_record", "a", usage={"inputTokens": 10, "outputTokens": 2,
                                                                  "reasoningEffort": "high", "cost": 0.5}),
            event("10:02:05", "tool.execution_complete", toolCallId="p", success=True,
                  result={"content": "Agent replied:\r\nPLAN .agent-loop/42/plan-1.md\r\n"}),
            event("10:02:56", "subagent.started", "x", agentName="research", toolCallId="other"),
            event("10:02:57", "session.usage_record", "x", usage={"parentToolCallId": "other", "inputTokens": 9999, "cost": 100}),
            event("10:03:00", "tool.execution_start", toolName="task", toolCallId="e"),
            event("10:03:01", "subagent.started", "b", agentName="executor", toolCallId="e", model="gpt-6.2-sol",
                  executionMode="background"),
            event("10:03:02", "tool.execution_complete", toolCallId="e", success=True, result={"content": "Background agent started"}),
            event("10:03:40", "session.usage_record", "b", usage={"parentToolCallId": "e", "inputTokens": 30,
                                                                  "outputTokens": 18, "reasoningTokens": 8, "cost": 2}),
            event("10:04:03", "subagent.completed", "b", toolCallId="e", durationMs=62000),
            event("10:05:00", "session.usage_checkpoint", accountingSnapshot={"totalPremiumRequestCost": 999}),
            "{incomplete",
        ]), encoding="utf-8")
        run_file = self.run / "run.json"
        run = json.loads(run_file.read_text())
        run_file.write_text(json.dumps({**run, "host": "copilot"}))
        (self.run / "exec-1.md").write_text("STATUS: GREEN\n")
        path = self.run / "report.md"
        buf = io.StringIO()
        with mock.patch.dict(os.environ, COPILOT_HOME=str(self.tmp)), contextlib.redirect_stdout(buf), \
             mock.patch.object(report, "PRICES", self.tmp / "missing.json"), \
             mock.patch.object(report, "plan_usage", side_effect=AssertionError("Claude only")):
            report.report(SimpleNamespace(dir=str(self.run), outcome="cap", out=path))
        out = path.read_text(encoding="utf-8")
        self.assertIn("| 1 | planner 1 | gpt-6.2-astra (medium) | 10:01:00 | 1m 05s | PLAN .agent-loop/42/plan-1.md | 40 | 50 | 120 | 22 | 5 | 1.5 |", out)
        self.assertIn("| 2 | executor 1 | gpt-6.2-sol | 10:03:00 | 1m 03s | GREEN | 30 | 0 | 0 | 18 | 8 | 2 |", out)
        self.assertIn("| - | dispatcher | claude-haiku-5.5 (low) | 10:00:01 |", out)
        self.assertIn("| dispatcher | - | 25 | 0 | 75 | 10 | 0 | 0.25 |", out)
        self.assertIn("| **Total** | 2 | 95 | 50 | 195 | 50 | 13 | 3.75 |", out)
        self.assertEqual(buf.getvalue().strip(), "Total: 3.75 premium requests, 390 tokens, 2 agent calls, outcome cap")
        self.assertTrue(out.endswith(buf.getvalue()))

    def test_init_detects_host_and_session(self):
        cases = [
            ({"CLAUDE_SESSION_ID": "claude-id"}, None, None, "claude", "claude-id"),
            ({"COPILOT_AGENT_SESSION_ID": "copilot-id"}, None, None, "copilot", "copilot-id"),
            ({"CLAUDE_SESSION_ID": "claude-id"}, "copilot", "override", "copilot", "override"),
            ({}, None, "override", "claude", "override"),
            ({"COPILOT_AGENT_SESSION_ID": "copilot-id"}, None, "", "copilot", "copilot-id"),
            ({"COPILOT_AGENT_SESSION_ID": "copilot-id"}, None, "${CLAUDE_SESSION_ID}", "copilot", "copilot-id"),
            ({"COPILOT_AGENT_SESSION_ID": "copilot-id"}, None, "claude-id", "claude", "claude-id"),
        ]
        exclude = self.tmp / "git info" / "exclude"
        exclude.parent.mkdir()
        exclude.write_bytes(b"# existing entry")
        issue = b'{"number":43}'
        for n, (env, host, session, expected_host, expected_session) in enumerate(cases, 43):
            with self.subTest(host=expected_host, session=expected_session):
                d = self.run.with_name(str(n))
                args = SimpleNamespace(dir=d, base="main", host=host, session=session)
                with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(io.StringIO()), \
                     mock.patch.object(report.subprocess, "check_output", side_effect=[f"{exclude}\n", issue]) as run_cmd, \
                     mock.patch.object(report, "snapshot", return_value={"test": 1}) as snapshot:
                    report.init(args)
                run_cmd.assert_has_calls([
                    mock.call(["git", "rev-parse", "--git-path", "info/exclude"], encoding="utf-8"),
                    mock.call(["gh", "issue", "view", str(n), "--json", "number,title,body,comments,labels"]),
                ])
                self.assertEqual((d / "issue.json").read_bytes(), issue)
                run = json.loads((d / "run.json").read_text())
                self.assertEqual(run["host"], expected_host)
                self.assertEqual(run["sessions"][0]["id"], expected_session)
                self.assertEqual(snapshot.call_count, int(expected_host == "claude"))
        self.assertEqual(exclude.read_bytes(), b"# existing entry\n.agent-loop/\n")

    def test_init_prompt_and_resume(self):
        exclude = self.tmp / "exclude"
        taken = self.run.with_name("fix-parsing")
        taken.mkdir()
        env = {"CLAUDE_SESSION_ID": "s1"}

        def init(d, side_effect, **flags):
            buf = io.StringIO()
            args = SimpleNamespace(**{"dir": d, "base": None, "host": None, "session": None,
                                      "prompt": False, "resume": False, **flags})
            with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(buf), \
                 mock.patch.object(report.subprocess, "check_output", side_effect=side_effect) as run_cmd, \
                 mock.patch.object(report, "snapshot", return_value=None):
                report.init(args)
            return buf.getvalue(), run_cmd

        out, run_cmd = init(taken, ["abc123\n", f"{exclude}\n"], prompt=True)
        d = taken.with_name("fix-parsing-2")
        self.assertIn(f"Dir: {d.as_posix()}\nBase: abc123", out)
        self.assertNotIn("gh", str(run_cmd.call_args_list))
        run = json.loads((d / "run.json").read_text())
        self.assertEqual((run["base"], run["kind"]), ("abc123", "prompt"))

        (d / "task.md").write_text("Fix the parsing.")
        with mock.patch.object(report.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            out, _ = init(d, [f"{exclude}\n"], resume=True)
        self.assertIn("Base: abc123", out)
        self.assertEqual(len(json.loads((d / "run.json").read_text())["sessions"]), 2)
        with mock.patch.object(report.subprocess, "run", return_value=SimpleNamespace(returncode=1)), \
             self.assertRaises(SystemExit):
            init(d, [f"{exclude}\n"], resume=True)

    def test_worktree(self):
        import subprocess
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name).resolve() / "proj"
        repo.mkdir()
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.check_call(git + ["init", "-q", "-b", "main"], cwd=repo)
        subprocess.check_call(git + ["commit", "-q", "--allow-empty", "-m", "x"], cwd=repo)
        cwd = os.getcwd()
        os.chdir(repo)
        self.addCleanup(os.chdir, cwd)

        def worktree(branch, base=None, env=None):
            buf = io.StringIO()
            with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(buf):
                report.worktree(SimpleNamespace(branch=branch, base=base))
            return buf.getvalue()

        env = {"HC_TERMINAL_SOCKET": "", "ORCA_APP_VERSION": ""}
        out = worktree("agent/issue-7", "main", env)
        path = repo.parent / "proj.worktrees" / "agent-issue-7"
        self.assertEqual(out, f"Worktree: {path.as_posix()}\nHerdr: no\n")
        self.assertEqual(worktree("agent/issue-7", env=env), out)  # resume finds it
        with self.assertRaises(SystemExit):
            worktree("agent/missing", env=env)

        home = repo.parent / "herdr"
        home.mkdir()
        (home / "settings.json").write_text(json.dumps({"worktrees": {"directory": str(repo.parent / "wt")}}))
        herdr = repo.parent / "wt" / "proj" / "agent-fix"
        ls = json.dumps({"spaces": [{"id": "sp1", "folder": str(herdr)}]})
        real = subprocess.check_output
        with mock.patch.object(report.subprocess, "check_output",
                               side_effect=lambda cmd, **kw: ls if cmd[0] == "herdr-app" else real(cmd, **kw)):
            out = worktree("agent/fix", "HEAD", {"HC_TERMINAL_SOCKET": "s", "HERDR_APP_HOME": str(home),
                                                 "ORCA_APP_VERSION": ""})
        self.assertEqual(out, f"Worktree: {herdr.as_posix()}\nHerdr: yes\nSpace: sp1\n")

        def fake_orca(cmd, **kw):
            if cmd[0] != "orca":
                return real(cmd, **kw)
            if cmd[1:3] == ["worktree", "current"] or cmd[4:5] == ["branch:agent/known"]:
                return json.dumps({"ok": True, "result": {"worktree": {"path": "/orca/known"}}})
            raise subprocess.CalledProcessError(1, cmd)
        orca_env = {"ORCA_APP_VERSION": "1", "HC_TERMINAL_SOCKET": "s"}  # Orca wins over Herdr
        head = real(["git", "rev-parse", "HEAD"], encoding="utf-8").strip()
        with mock.patch.object(report.subprocess, "check_output", side_effect=fake_orca):
            self.assertEqual(worktree("agent/new", "main", orca_env), f"Orca: create\nStart: {head}\n")
            self.assertEqual(worktree("agent/known", env=orca_env), "Worktree: /orca/known\nOrca: launch\n")
            # A branch Orca has no worktree for falls back to a plain git worktree.
            self.assertEqual(worktree("agent/issue-7", env=orca_env), f"Worktree: {path.as_posix()}\nHerdr: no\n")

        os.chdir(path)
        d = Path(".agent-loop/7")
        with mock.patch.dict(os.environ, {"CLAUDE_SESSION_ID": "s1"}, clear=True), \
             mock.patch.object(report.subprocess, "check_output", side_effect=[f"{repo}/.git/info/exclude\n", b"{}"]), \
             mock.patch.object(report, "snapshot", return_value=None), contextlib.redirect_stdout(io.StringIO()) as buf:
            report.init(SimpleNamespace(dir=d, base="main", host=None, session=None))
        self.assertIn(f"Worktree: {path.as_posix()}", buf.getvalue())

    def test_prompt_report_heading(self):
        d = self.run.with_name("fix-parsing")
        d.mkdir()
        (d / "run.json").write_text(json.dumps({"kind": "prompt", "base": "abc", "sessions": []}))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report.report(SimpleNamespace(dir=str(d), outcome="done"))
        self.assertIn("## Agent loop report: prompt fix-parsing", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
