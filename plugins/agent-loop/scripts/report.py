#!/usr/bin/env python3
"""Bookkeeping for /agent-loop:run.

init      prepare the task directory and record the run start in <dir>/run.json
worktree  find or create the git worktree for a run branch (in Orca: say whether Orca creates or has it)
report  generate the markdown token/cost report from the host's transcripts
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CONFIG = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
PRICES = Path(__file__).with_name("prices.json")
ROLES = ("planner", "executor", "reviewer")
RESULT_FILE = {"executor": "exec", "reviewer": "review"}
KINDS = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")
COPILOT_TOKENS = {"input": "inputTokens", "cache_write": "cacheWriteTokens", "cache_read": "cacheReadTokens",
                  "output": "outputTokens", "reasoning": "reasoningTokens"}
REPLY = re.compile(r"^(?:PLAN|GREEN|RED|BLOCKED|DONE|FIX|REPLAN)(?:[^\S\r\n]+[^\r\n]*)?$", re.M)
SESSION_ENV = {"claude": "CLAUDE_SESSION_ID", "copilot": "COPILOT_AGENT_SESSION_ID"}


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def rates_for(model, prices):
    keys = [k for k in prices if model.startswith(k)]
    return prices[max(keys, key=len)] if keys else None


def tokens(usage):
    cc = usage.get("cache_creation") or {}
    w5, w1 = cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:  # older transcripts carry only the total
        w5, w1 = usage.get("cache_creation_input_tokens", 0), 0
    return {
        "input": usage.get("input_tokens", 0),
        "cache_write_5m": w5 or 0,
        "cache_write_1h": w1 or 0,
        "cache_read": usage.get("cache_read_input_tokens", 0),
        "output": usage.get("output_tokens", 0),
    }


def cost(tok, usage, rates):
    if rates is None:
        return None
    above = rates.get("above")
    # tiered models price each request by its whole prompt, cache reads and writes included
    if above and sum(tok.values()) - tok["output"] > above["prompt_tokens"]:
        rates = {**rates, **above}
    mult = rates.get("fast_multiplier", 1) if usage.get("speed") == "fast" else 1
    return sum(tok[k] * rates[k] for k in KINDS) * mult / 1e6


def read_call(path, prices, since=None):
    """Sum one transcript. Returns None when it holds nothing at or after `since`."""
    msgs, start, end = {}, None, None
    for line in path.read_text().splitlines():
        try:
            d = json.loads(line)
            t = ts(d["timestamp"])
        except (ValueError, KeyError, TypeError):
            continue
        if since and t < since:
            continue
        start, end = start or t, t
        m = d.get("message") or {}
        if d.get("type") == "assistant" and m.get("usage") and m.get("model", "<").startswith("claude"):
            # one API response spans several lines, each repeating its usage: keep the last
            msgs[m.get("id") or d.get("uuid")] = m
    if start is None:
        return None
    call = {"start": start, "end": end, "model": "", "cost": 0.0, **dict.fromkeys(KINDS, 0)}
    for m in msgs.values():
        tok = tokens(m["usage"])
        c = cost(tok, m["usage"], rates_for(m["model"], prices))
        call["model"] = m["model"]
        call["cost"] = None if c is None or call["cost"] is None else call["cost"] + c
        for k in KINDS:
            call[k] += tok[k]
    return call


def snapshot():
    try:
        return json.loads((CONFIG / "agent-loop-statusline.json").read_text()).get("rate_limits")
    except (OSError, ValueError):
        return None


def init(a):
    host = a.host or next((h for h, key in SESSION_ENV.items() if os.environ.get(key)), "claude")
    # The skill passes --session=${CLAUDE_SESSION_ID}; hosts that don't substitute it leave it empty or literal.
    given = a.session if a.session and "{" not in a.session else None
    if given and not a.host:
        host = "claude"
    session = given or os.environ.get(SESSION_ENV[host])
    if not session or not re.fullmatch(r"[a-zA-Z0-9_-]+", session):
        raise SystemExit(f"Set {SESSION_ENV[host]} or pass a valid --session.")
    d = Path(a.dir)
    prompt, resume = getattr(a, "prompt", False), getattr(a, "resume", False)
    if prompt or resume:
        if not re.fullmatch(r"(?=.*[a-z])[a-z0-9-]{1,40}(-[0-9]+)?", d.name):
            raise SystemExit("--dir must end with a slug: a-z, 0-9 and -, at most 40 characters.")
    elif not re.fullmatch(r"[0-9]+", d.name):
        raise SystemExit("--dir must end with the issue number.")
    elif not a.base:
        raise SystemExit("--base is required for an issue.")
    if prompt:
        name, n = d.name, 1
        while d.exists():
            n += 1
            d = d.with_name(f"{name}-{n}")
    f = d / "run.json"
    if resume and not (f.exists() and (d / "task.md").exists()):
        raise SystemExit(f"No prompt run to resume in {d}.")
    run = json.loads(f.read_text()) if f.exists() else {"sessions": [], "host": host}
    if run.get("host", "claude") != host:
        raise SystemExit("Existing run uses a different host.")
    start = datetime.now(timezone.utc).isoformat()
    if prompt:
        base = subprocess.check_output(["git", "rev-parse", "HEAD"], encoding="utf-8").strip()
    elif resume:
        base = run["base"]
        if subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"]).returncode != 0:
            raise SystemExit(f"Base {base} is not an ancestor of HEAD; switch to the branch that holds the run.")
    else:
        base = a.base
    exclude = Path(subprocess.check_output(["git", "rev-parse", "--git-path", "info/exclude"],
                                           encoding="utf-8").rstrip("\r\n"))
    issue = None if prompt or resume else \
        subprocess.check_output(["gh", "issue", "view", d.name, "--json", "number,title,body,comments,labels"])
    contents = exclude.read_bytes() if exclude.exists() else b""
    if b".agent-loop/" not in contents.splitlines():
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("ab") as fp:
            if contents and not contents.endswith(b"\n"):
                fp.write(b"\n")
            fp.write(b".agent-loop/\n")
    d.mkdir(parents=True, exist_ok=True)
    if issue is not None:
        (d / "issue.json").write_bytes(issue)
    run.update(host=host, base=base, kind="issue" if issue is not None else "prompt")
    run["sessions"].append({"id": session, "start": start})
    if host == "claude":
        run["rate_limits"] = snapshot()
    f.write_text(json.dumps(run, indent=2))
    print(f"Dir: {d.as_posix()}\nBase: {base}")
    # A linked worktree's .git is a file pointing into the main repository's .git/worktrees/.
    dotgit = Path(".git")
    if dotgit.is_file() and "/worktrees/" in dotgit.read_text().replace("\\", "/"):
        print(f"Worktree: {Path.cwd().as_posix()}")
    if orca("worktree", "current"):
        print("Orca: yes")


def orca(*args):
    """Result of an `orca` CLI call, or None outside Orca or when the call fails."""
    if not os.environ.get("ORCA_APP_VERSION"):
        return None
    try:
        out = subprocess.check_output(["orca", *args, "--json"], encoding="utf-8", stderr=subprocess.DEVNULL)
        return json.loads(out)["result"]
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        return None


def herdr_root():
    home = Path(os.environ.get("HERDR_APP_HOME") or Path.home() / ".config" / "herdr-app")
    try:
        root = json.loads((home / "settings.json").read_text())["worktrees"]["directory"]
    except (OSError, ValueError, KeyError, TypeError):
        root = "~/.herdr/worktrees"
    return Path(root).expanduser()


def worktree(a):
    listing = subprocess.check_output(["git", "worktree", "list", "--porcelain"], encoding="utf-8")
    trees = [dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
             for block in listing.strip().split("\n\n")]
    ref = f"refs/heads/{a.branch}"
    path = next((t["worktree"] for t in trees if t.get("branch") == ref), None)
    exists = path is not None or subprocess.run(["git", "show-ref", "--verify", "--quiet", ref]).returncode == 0
    in_orca = bool(orca("worktree", "current"))
    if in_orca:
        # Orca hides worktrees it did not create, so it must create the run's worktree itself.
        known = orca("worktree", "show", "--worktree", f"branch:{a.branch}")
        if known:
            print(f"Worktree: {Path(known['worktree']['path']).as_posix()}\nOrca: launch")
            return
        if not exists and a.base:
            start = subprocess.check_output(["git", "rev-parse", "--verify", f"{a.base}^{{commit}}"],
                                            encoding="utf-8").strip()
            print(f"Orca: create\nStart: {start}")
            return
    herdr = not in_orca and bool(os.environ.get("HC_TERMINAL_SOCKET"))
    if path is None:
        main = Path(trees[0]["worktree"])
        # Same layout as Herdr's New worktree dialog, so the space nests under its repo.
        leaf = a.branch.replace("/", "-")
        path = str((herdr_root() / main.name if herdr else main.parent / f"{main.name}.worktrees") / leaf)
        if exists:
            add = ["git", "worktree", "add", path, a.branch]
        elif a.base:
            add = ["git", "worktree", "add", "-b", a.branch, path, a.base]
        else:
            raise SystemExit(f"Branch {a.branch} does not exist; pass --base.")
        subprocess.check_call(add, stdout=subprocess.DEVNULL)
    print(f"Worktree: {Path(path).as_posix()}\nHerdr: {'yes' if herdr else 'no'}")
    if herdr:
        try:
            spaces = json.loads(subprocess.check_output(["herdr-app", "ls"], encoding="utf-8"))["spaces"]
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
            spaces = []
        space = next((s["id"] for s in spaces if s.get("folder") and Path(s["folder"]) == Path(path)), None)
        if space:
            print(f"Space: {space}")


def collect(run, prices):
    calls = []
    for s in run["sessions"]:
        since = ts(s["start"])
        for main in (CONFIG / "projects").glob(f"*/{s['id']}.jsonl"):
            c = read_call(main, prices, since)
            if c:
                calls.append({**c, "role": "dispatcher"})
            for meta in (main.with_suffix("") / "subagents").glob("agent-*.meta.json"):
                role = json.loads(meta.read_text()).get("agentType", "").split(":")[-1]
                if role not in ROLES:
                    continue
                c = read_call(meta.with_name(meta.name.replace(".meta.json", ".jsonl")), prices)
                if c and c["start"] >= since:
                    calls.append({**c, "role": role})
    return sorted(calls, key=lambda c: c["start"])


def copilot_reply(result):
    if isinstance(result, dict):
        return copilot_reply(result.get("content")) or copilot_reply(result.get("detailedContent"))
    if isinstance(result, str):
        replies = REPLY.findall(result.replace("\r\n", "\n"))
        if replies:
            return replies[-1].strip().replace("|", r"\|")
    return ""


def read_copilot(path, since):
    def call(role, start, model=""):
        return dict(role=role, start=start, end=start, model=model, cost=0.0, **dict.fromkeys(COPILOT_TOKENS, 0))

    starts, agents, agent_ids, dispatcher = {}, {}, {}, None
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
                t = ts(e["timestamp"])
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            kind, data, aid = e.get("type"), e.get("data") or {}, e.get("agentId")
            cid = data.get("toolCallId")
            if kind == "tool.execution_start" and data.get("toolName") == "task":
                starts[cid] = t
            if t < since:
                continue
            if kind == "subagent.started":
                role = re.split(r"[:/\\]", data.get("agentName") or "")[-1]
                start = starts.get(cid, t)
                if cid and role in ROLES and start >= since:
                    agents[cid] = call(role, start, data.get("model") or "")
                    agents[cid].update(end=t, background=data.get("executionMode") == "background")
                    if aid:
                        agent_ids[aid] = cid
            elif kind in ("tool.execution_complete", "subagent.completed", "subagent.failed") and cid in agents:
                c = agents[cid]
                if kind != "tool.execution_complete" or not c["background"]:
                    c.update(end=t, finished=True)
                if kind == "tool.execution_complete":
                    c["reply"] = copilot_reply(data.get("result"))
            elif kind == "session.usage_record":
                u = data.get("usage") or {}
                parent = u.get("parentToolCallId") or agent_ids.get(aid)
                if parent or aid or u.get("initiator") == "sub-agent":
                    c = agents.get(parent)
                    if c is None:
                        continue
                else:
                    dispatcher = dispatcher or call("dispatcher", t)
                    c = dispatcher
                if not c.get("finished"):
                    c["end"] = t
                c["model"] = c["model"] or u.get("model") or ""
                c["effort"] = c.get("effort") or u.get("reasoningEffort") or ""
                tok = {k: u.get(field) or 0 for k, field in COPILOT_TOKENS.items()}
                # Copilot input includes cache reads and writes; the table splits them out.
                tok["input"] = max(0, tok["input"] - tok["cache_read"] - tok["cache_write"])
                for k, n in tok.items():
                    c[k] += n
                c["cost"] += u.get("cost") or 0.0
    return list(agents.values()) + ([dispatcher] if dispatcher else [])


def collect_copilot(run):
    home = Path(os.environ.get("COPILOT_HOME") or Path.home() / ".copilot")
    calls = []
    for s in run["sessions"]:
        path = home / "session-state" / s["id"] / "events.jsonl"
        if path.is_file():
            calls.extend(read_copilot(path, ts(s["start"])))
        else:
            print("Copilot transcript missing; check COPILOT_HOME and the session ID used for init.", file=sys.stderr)
    return sorted(calls, key=lambda c: c["start"])


def result(d, role, k):
    f = d / f"{RESULT_FILE.get(role)}-{k}.md"
    if not f.exists():
        return ""
    lines = f.read_text().splitlines() or [""]
    return lines[0].split(":")[-1].strip()


def usd(c):
    return "n/a" if c is None else f"${c:.2f}" if c >= 1 else f"${c:.3f}"


def cells(c, copilot):
    if copilot:
        return [f"{c[k]:,}" for k in COPILOT_TOKENS] + [f"{c['cost']:g}"]
    return [f"{c['input']:,}", f"{c['cache_write_5m'] + c['cache_write_1h']:,}", f"{c['cache_read']:,}", f"{c['output']:,}", usd(c["cost"])]


def total(calls, kinds):
    t = {"cost": 0.0, **dict.fromkeys(kinds, 0)}
    for c in calls:
        for k in kinds:
            t[k] += c[k]
        t["cost"] = None if c["cost"] is None or t["cost"] is None else t["cost"] + c["cost"]
    return t


def table(head, rows):
    return ["| " + " | ".join(head) + " |", "|" + " --- |" * len(head)] + ["| " + " | ".join(r) + " |" for r in rows]


def plan_usage(before):
    after, parts = snapshot(), []
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        b, a = (before or {}).get(key), (after or {}).get(key)
        if b and a and b.get("resets_at") == a.get("resets_at"):  # a reset mid-run voids the delta
            parts.append(f"{label} {a['used_percentage'] - b['used_percentage']:+.1f}%")
    return parts


def report(a):
    d = Path(a.dir)
    run = json.loads((d / "run.json").read_text())
    copilot = run.get("host") == "copilot"
    kinds = COPILOT_TOKENS if copilot else KINDS
    calls = collect_copilot(run) if copilot else collect(run, json.loads(PRICES.read_text())["models"])
    columns = ["Input", "Cache write", "Cache read", "Output"] + (["Reasoning", "Premium requests"] if copilot else ["Cost"])
    agents = [c for c in calls if c["role"] != "dispatcher"]

    title = f"issue #{d.resolve().name}" if run.get("kind", "issue") == "issue" else f"prompt {d.resolve().name}"
    out = [f"## Agent loop report: {title}", "", f"**Outcome:** {a.outcome}", "", "### Timeline", ""]
    seen, rows = {}, []
    i = 0
    for c in calls if copilot else agents:
        role = c["role"]
        if role == "dispatcher":
            number, label, reply = "-", role, ""
        else:
            i += 1
            k = seen[role] = seen.get(role, 0) + 1
            number, label = str(i), f"{role} {k}"
            reply = c.get("reply") or result(d, role, k)
        secs = int((c["end"] - c["start"]).total_seconds())
        model = f"{c['model']} ({c['effort']})" if c.get("effort") else c["model"]
        rows.append([number, label, model, f"{c['start']:%H:%M:%S}", f"{secs // 60}m {secs % 60:02d}s", reply] + cells(c, copilot))
    out += table(["#", "Agent", "Model", "Start (UTC)", "Duration", "Result"] + columns, rows)

    out += ["", "### Per role", ""]
    rows = []
    for role in ROLES + ("dispatcher",):
        mine = [c for c in calls if c["role"] == role]
        if mine:
            rows.append([role, str(len(mine)) if role in ROLES else "-"] + cells(total(mine, kinds), copilot))
    grand = total(calls, kinds)
    rows.append(["**Total**", str(len(agents))] + cells(grand, copilot))
    out += table(["Role", "Calls"] + columns, rows)

    if copilot:
        price = f"{grand['cost']:g} premium requests"
        note = "Input excludes cache reads and writes. Output includes reasoning tokens."
    else:
        usage = plan_usage(run.get("rate_limits"))
        if usage:
            out += ["", f"Plan usage: {', '.join(usage)} (account-wide, approximate)."]
        price = f"{usd(grand['cost'])} API-equivalent"
        note = "Cost is an API-equivalent estimate at list prices."
    out += ["", f"{note} The dispatcher's calls that post this report are not counted.", ""]
    n = sum(grand[k] for k in kinds if k != "reasoning")
    out.append(f"Total: {price}, {n:,} tokens, {len(agents)} agent calls, outcome {a.outcome}")
    if getattr(a, "out", None):
        Path(a.out).write_text("\n".join(out) + "\n", encoding="utf-8")
        print("\n".join(out) if getattr(a, "print", False) else out[-1])
    else:
        print("\n".join(out))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("--dir", required=True)
    i.add_argument("--session")
    i.add_argument("--host", choices=SESSION_ENV)
    i.add_argument("--base")
    mode = i.add_mutually_exclusive_group()
    mode.add_argument("--prompt", action="store_true", help="new prompt run: --dir ends with a slug, base is HEAD")
    mode.add_argument("--resume", action="store_true", help="resume a prompt run, keeping its base")
    i.set_defaults(fn=init)
    w = sub.add_parser("worktree")
    w.add_argument("--branch", required=True)
    w.add_argument("--base", help="start point when the branch does not exist yet")
    w.set_defaults(fn=worktree)
    r = sub.add_parser("report")
    r.add_argument("--dir", required=True)
    r.add_argument("--outcome", required=True)
    r.add_argument("--out")
    r.add_argument("--print", action="store_true", help="with --out, print the whole report, not just the total")
    r.set_defaults(fn=report)
    args = p.parse_args()
    args.fn(args)
