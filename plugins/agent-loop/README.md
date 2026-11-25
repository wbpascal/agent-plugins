# agent-loop

A plugin for Claude Code and GitHub Copilot (CLI and VS Code) that runs one agent loop on one task, a GitHub issue or a prompt:

```
planner -> executor -> reviewer -> DONE | FIX | REPLAN
```

The session that invokes the skill is the dispatcher: it spawns the three agents one at a time, routes on their one-line reply, and is the only one that runs `gh` and `git push`. Agents start fresh and hand over through files in `.agent-loop/<issue or slug>/`.

## Use

From the repository whose issue you want worked on (clean tree, `gh` authenticated, current branch pushed):

### Claude Code

```
claude --plugin-dir /path/to/agent-plugins/plugins/agent-loop
/model haiku                       # a cheap dispatcher is enough
/agent-loop:run 42
```

Or install it from the GitHub marketplace repository without cloning it yourself:

```
claude plugin marketplace add https://github.com/wbpascal/agent-plugins.git
claude plugin install agent-loop@agent-plugins
```

### Copilot

```
copilot --plugin-dir /path/to/agent-plugins/plugins/agent-loop
/model claude-haiku-5.5
/agent-loop:run 42
```

The slash command may appear as `/run`. Or install the same plugin from the GitHub marketplace repository:

```
copilot plugin marketplace add https://github.com/wbpascal/agent-plugins.git
copilot plugin install agent-loop@agent-plugins
```

In VS Code, run **Chat: Install Plugin from Source** and enter `https://github.com/wbpascal/agent-plugins.git`, or let VS Code discover the plugin installed by Copilot CLI.

Copilot requires `gpt-6.2-astra` (planner; fallback `claude-opus-5.5`), `gpt-6.2-sol` (executor) and `claude-opus-5.5` (reviewer). If your Copilot plan doesn't provide a required model, the run aborts rather than substituting another model.

To override the executor, pass a model supported by your host, e.g. `/agent-loop:run 42 --executor gpt-6.2-sol --max-passes 5` on Copilot. The model string is passed through unchanged.

`--reviewer <model>` overrides the reviewer the same way.

`--no-plan` starts a planless run: no planner, the executor works from the task directly and the reviewer judges against it. It suits small tasks given to a stronger executor and reviewer, so unless you pass model or effort flags the dispatcher offers to switch to Opus (medium) executor and Fable (high) reviewer on Claude Code, or Opus 5.5 executor (medium) and reviewer (high) on Copilot. Pass `--no-plan` again with `--resume`.

Effort defaults to `medium` for `--planner-effort` and `--executor-effort`, and `high` for `--reviewer-effort`. For example: `/agent-loop:run 42 --planner-effort high --executor-effort low --reviewer-effort medium`. Values are passed through unchanged, so the host may reject a level its model does not support. On Claude Code, `CLAUDE_CODE_EFFORT_LEVEL` overrides all three.

### From a prompt

Instead of an issue number, give the task as text. Flags go before it:

```
/agent-loop:run --max-passes 5 add a --dry-run flag to the import command
```

A prompt run needs only a clean tree, not `gh` or a remote. It commits directly on your current branch, opens no PR and posts nothing. At the end the dispatcher prints the report, the commit the run started from (`git reset --hard <sha>` undoes the run) and, on `DONE`, the reviewer's `pr-body.md` for a PR you open yourself. The run lives in `.agent-loop/<slug>/`, where the slug is a short summary of the prompt. Continue an unfinished one with `/agent-loop:run --resume <slug>` from the same branch.

### In a worktree

An issue run works in its own git worktree, so your checkout stays untouched and several runs can go in parallel. Pass `--in-place` for the old behaviour, or `--worktree` to isolate a prompt run on a branch `agent/<slug>`. Uncommitted changes in your checkout are not part of the run; the dispatcher warns about them.

The session you invoke creates the worktree and hands off to a fresh dispatcher inside it:

- **In Herdr**: the worktree goes where Herdr's New worktree dialog puts it (`worktrees.directory`, default `~/.herdr/worktrees/<repo>/<branch>`) and the run starts in a new space. A resumed run opens a tab in that space.
- **In Orca**: Orca creates the worktree (under its workspace directory, linked to the issue) and starts the run in a new agent tab. A resumed run opens a new tab in that worktree. While the run goes, the worktree comment shows the running agent (`reviewer #12 call 2`) and then the outcome; a worktree run moves to in progress on the board, and to in review with its PR linked when done.
- **Claude Code elsewhere**: the worktree is `../<repo>.worktrees/<branch>` and the session moves into it.
- **Copilot elsewhere**: same path; the dispatcher prints the `cd … && copilot -i …` command for you to run.

Resume a worktree run from anywhere with the same command; the dispatcher finds its worktree. Worktrees are never removed for you, so you can come back with feedback; the final message gives the `git worktree remove` command (`orca worktree rm` in Orca).

## What a run does

1. Fetches the base branch (the current branch unless `--base`) and creates `agent/issue-<N>` from `origin/<base>`, in a worktree unless `--in-place` (issue only; a prompt run stays on the current branch unless `--worktree`), and assigns the issue to you. If someone else is already assigned, it asks before going on. The assignment stays after the run.
2. Planner writes `plan-k.md`; executor implements, tests and commits, writing `exec-k.md`; reviewer reviews the whole branch for functionality, security and maintainability, writing `review-k.md`.
3. Reviewer verdict routes the loop: `FIX` back to the executor, `REPLAN` to a fresh planner, `DONE` ends it. An executor that cannot follow the plan returns `BLOCKED`, which also goes to a fresh planner.
4. `DONE` on an issue: pushes the branch, opens a PR against the branch you started from, and posts the report as a PR comment. If that branch has an open PR, the new PR joins its [stack](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs); if that PR sits mid-stack, the run asks first, since only the top of a stack can be extended.
5. `--max-passes` executor calls used up (default 3), or an agent failing twice: no PR, branch stays local, report goes to the issue as a comment.
6. A prompt run ends the same three ways, but only prints the report and saves it as `report.md`.

`.agent-loop/` is added to `.git/info/exclude`, so the target repository's `.gitignore` is untouched. The files stay after the run for you to study.

## Report

The report shows a timeline (model, start, duration, result), plus tokens and cost per call, per role and in total, including the dispatcher.

- **Claude Code** reads transcripts under `~/.claude/projects/`. Cost is an API-equivalent estimate from `scripts/prices.json`; unknown models show `n/a`.
- **Copilot** reads transcripts under `~/.copilot/session-state/` and reports tokens and premium requests, with no plan-usage line. The Model column includes reasoning effort when recorded.

### Plan usage (optional)

Claude Code only exposes plan usage to the status line command. To add a "Plan usage: 5h +X%, 7d +Y%" line to the report, wrap your status line command in `~/.claude/settings.json`:

```json
"statusLine": { "type": "command", "command": "sh /path/to/agent-plugins/plugins/agent-loop/scripts/statusline-wrapper.sh <your existing command>" }
```

The number is account-wide, so other sessions running at the same time are included.

## Tests

From `plugins/agent-loop/`:

```
python3 -m unittest discover -s tests
```
