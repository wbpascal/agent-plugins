---
name: run
description: Run one agent loop (planner, executor, reviewer) on a GitHub issue or a prompt until the reviewer says done.
argument-hint: [flags] <issue-number> | <prompt> | --resume <slug>   flags: --worktree --in-place --no-plan --executor <model> --reviewer <model> --planner-effort E --executor-effort E --reviewer-effort E --max-passes N
disable-model-invocation: true
---

# Agent loop: one task

Arguments: `$ARGUMENTS`

Flags come first:

- `--executor <model>` / `--reviewer <model>`: pass the string unchanged as that role's model. Omitted: use the agent default.
- `--no-plan`: **planless run**, no planner is spawned.
- `--planner-effort <E>`: planner effort. Default `medium`.
- `--executor-effort <E>`: executor effort. Default `medium`.
- `--reviewer-effort <E>`: reviewer effort. Default `high`.
- `--max-passes <P>`: maximum executor calls. Default 3.
- `--worktree` / `--in-place`: run in a git worktree on the run's own branch, or in this checkout. Default: worktree for an issue, in place for a prompt.
- `--base <branch>`: issue mode, the PR base. Set by the handoff below; otherwise the current branch.

After the flags, the task:

- `N`, all digits: **issue mode**, GitHub issue N.
- `--resume <slug>`: **prompt mode**, continue the run in `.agent-loop/<slug>`.
- Anything else: **prompt mode**; the rest of the arguments, verbatim, is the prompt.

You are the **dispatcher**. Three agents do all reading, thinking and coding. You spawn them one at a time, route on their one-line reply, and run `git` and `gh`. You carry paths, not content: every file under `D` stays unread by you, because the reply line already holds everything routing needs.

Substitute placeholders. Issue mode: `D` is `.agent-loop/N`, `ID` is `#N`. Prompt mode: `D` and `BASE` are the `Dir:` and `Base:` lines printed by `REPORT init`, `ID` is the last part of `D`. `WT` is the `Worktree:` line printed by `REPORT init`, if any. **In Orca** means `REPORT init` printed `Orca: yes`; when an `orca` command fails, warn the user and go on. `REPORT` is `python "${CLAUDE_PLUGIN_ROOT}/scripts/report.py"` (use `python3` if that is your Python 3 command; if `${CLAUDE_PLUGIN_ROOT}` is not filled in, the plugin root is two levels above this skill's base directory).

## 1. Preflight

Stop and tell the user which check failed. In place: `git status --porcelain` prints nothing. In a worktree: if it prints anything, warn the user that those changes are not part of the run.

Issue mode:

- `gh issue view N --json state,assignees -q '[.state, .assignees[].login] | join(" ")'` prints `OPEN` first. Unless a handoff landed here, if it lists a login other than `gh api user -q .login`, ask the user: continue or abort.
- `BASE` = `--base` or else `git branch --show-current`, and `git fetch origin BASE` succeeds (it becomes the PR base; a new branch starts at `origin/BASE`).
- Unless a handoff landed here: if `gh pr list --head BASE --state open --json number` lists exactly one PR, `BASE_PR`, and `gh api 'repos/{owner}/{repo}/stacks?pull_request=BASE_PR'` shows it in a stack below another PR, tell the user the top PR's branch, ask: abort and start from that branch to stack the PR, or continue unstacked.
- If the current branch is `agent/issue-N` (a handoff landed here), skip this check and `git switch -c` below; if `D/run.json` exists, resume. Otherwise branch `agent/issue-N` exists neither locally nor on origin. If it exists, ask the user: resume or abort. Resume means keep the files in `D`, continue their numbering, and enter the loop at the planner (executor with `--no-plan`) with the newest review or exec report as extra input; in place, first `git switch agent/issue-N`.

Prompt mode: choose `SLUG`, a summary of the prompt in at most 40 characters of `a-z`, `0-9` and `-`; on a branch `agent/X`, `SLUG` is `X`. A `--resume <slug>` runs in a worktree when branch `agent/<slug>` exists and `--in-place` was not given.

### Planless model choice

With `--no-plan` and none of `--executor`, `--executor-effort`, `--reviewer`, `--reviewer-effort` given, ask the user, before the handoff, to choose between keeping the defaults and, preselected, the strong setup: Claude Code `--executor opus --executor-effort medium --reviewer fable --reviewer-effort high`; Copilot `--executor claude-opus-5.5 --executor-effort medium --reviewer claude-opus-5.5 --reviewer-effort high`. Add the chosen flags to the run's flags.

### Worktree handoff

In a worktree run, do this before anything below. `B` is `agent/issue-N` or `agent/SLUG`. Run `REPORT worktree --branch B --base START`, with `START` = `origin/BASE` for an issue and `HEAD` for a new prompt run; omit `--base` when `B` exists. It prints `Worktree: P`, `Herdr: yes|no`, and `Space: S` when a Herdr space already shows `P`; or, in Orca, `Orca: create` and `Start: C`, or `Worktree: P` and `Orca: launch`. `CMD` is `/agent-loop:run --in-place`, then `--base BASE` (issue mode), the other flags, and the task (`N`, the prompt or `--resume <slug>`), escaped for the shell. Then:

- `Orca: create`: `orca worktree create --name NAME --branch B --base-branch C --agent claude --prompt 'CMD'`, with `--issue N` in issue mode, `--agent copilot` on Copilot, and `NAME` = `B` without `agent/`. Tell the user the run continues in the new Orca worktree, and end.
- `Orca: launch`: `orca agent launch --agent claude --worktree path:P --prompt 'CMD'` (`--agent copilot` on Copilot). Tell the user the run continues in the Orca worktree `P`, and end.
- `Herdr: yes`: `herdr-app do space.new --folder P --argv '["claude"]' --task 'CMD'` (`["copilot"]` on Copilot); with `Space: S`, `tab.new --space S` instead of `space.new`. Tell the user the run continues in the worktree `P`, and end.
- Claude Code: enter `P` with `EnterWorktree` (`path`) and continue as if invoked with `CMD`.
- Copilot: tell the user to run `cd P && copilot -i "CMD"`, and end.

### Start

Issue mode, run in order, stopping on failure:

```text
REPORT init --dir D --base BASE --session=${CLAUDE_SESSION_ID}
git switch -c agent/issue-N origin/BASE
```

Then `gh issue edit N --add-assignee @me`; if it fails, warn the user and go on.

Prompt mode, new run: run `REPORT init --dir .agent-loop/SLUG --prompt --session=${CLAUDE_SESSION_ID}`, then write the prompt verbatim to `D/task.md` with your file-writing tool.

Prompt mode, resume: run `REPORT init --dir .agent-loop/<slug> --resume --session=${CLAUDE_SESSION_ID}`. Keep the files in `D`, continue their numbering, and enter the loop at the planner (executor with `--no-plan`) with the newest review or exec report as extra input.

Prompt mode works on the current branch: no `gh`, no push.

In Orca with `WT` set: `orca worktree set --worktree current --workspace-status in-progress`.

Done when `D/run.json` and the task file exist, and in issue mode the current branch is `agent/issue-N`.

## 2. Loop

Spawn this plugin's `planner`, `executor` or `reviewer` in the foreground with the host's subagent tool. On every spawn pass the role's effort unchanged, without validation (`effort` on Claude Code, `reasoning_effort` on Copilot). Pass `model` to the executor or reviewer only when `--executor` or `--reviewer` was given. Description: `<role> ID call <k>`; in Orca, first `orca worktree set --worktree current --comment '<description>'`. Prompt (the `Issue number` line in issue mode only, the `Plan` line in a planless run only; `Task` is `D/issue.json` or `D/task.md`; `Base` is `origin/BASE` in issue mode):

```
Issue number: N
Task: <task file>
Base: BASE
Plan: none
Read: <input files from the table>
Write: <output file from the table>
```

Output files are numbered per role, starting at 1: `plan-k.md`, `exec-k.md`, `review-k.md`. "Latest" means the highest number.

| Reply | Next agent | Read |
| --- | --- | --- |
| (start) | planner | (issue only) |
| `PLAN` | executor | latest plan |
| `GREEN` or `RED` | reviewer | latest plan, latest exec |
| `BLOCKED` | planner | latest plan, latest exec |
| `FIX` | executor | latest plan, latest review |
| `REPLAN` | planner | latest plan, latest review |
| `DONE` | none: go to step 3, outcome `done` | |

Planless run: start with the executor (Read: none), and drop the plan from every Read list.

Two exits besides `DONE`:

- **Cap**: the next agent is the executor and it has already run `P` times. Outcome `cap`.
- **Abort**: an agent ends without a reply from the table. Spawn it once more with the same prompt; a second failure is outcome `aborted`.

## 3. Finish

Issue mode, outcome `done` (the reviewer has written `D/pr-body.md`):

```text
git push -u origin agent/issue-N
gh pr create --base BASE --head agent/issue-N --title '<issue title> (#N)' --body-file D/pr-body.md
(stack the PR, below)
REPORT report --dir D --outcome done --out D/report.md
gh pr comment PR_URL --body-file D/report.md
git switch BASE   (skip when WT is set)
```

Issue mode, outcome `cap` or `aborted` (branch stays local, for the user to inspect):

```text
REPORT report --dir D --outcome OUTCOME --out D/report.md
gh issue comment N --body-file D/report.md
```

Get the issue title with `gh issue view N --json title -q .title`; escape it for the shell. Use the URL from `gh pr create` as `PR_URL`, its number as `PR`.

Stack the PR: run `gh pr list --head BASE --state open --json number` again. With exactly one PR, `BASE_PR`, find its stack with `gh api 'repos/{owner}/{repo}/stacks?pull_request=BASE_PR'`. In a stack numbered `S`: `gh api -X POST repos/{owner}/{repo}/stacks/S/add -F 'pull_requests[]=PR'`. In none: `gh api -X POST repos/{owner}/{repo}/stacks -F 'pull_requests[]=BASE_PR' -F 'pull_requests[]=PR'`. With several PRs, or when a call fails, warn the user and go on; the PR stays unstacked against `BASE`. With none, do nothing.

Prompt mode, every outcome: run `REPORT report --dir D --outcome OUTCOME --out D/report.md --print`. The commits stay on the current branch.

In Orca: `orca worktree set --worktree current --comment OUTCOME`, adding, when `WT` is set and the outcome is `done`, `--workspace-status in-review` and in issue mode `--pr PR`.

Done when the report is posted (issue mode) or printed (prompt mode). Tell the user the outcome and the total line printed by `REPORT report`. Issue mode: add the PR URL if any. When `WT` is set, add `WT` and `git worktree remove WT` (in Orca `orca worktree rm --worktree path:WT`) to clean up once the user is done with it. Prompt mode: first repeat the whole printed report, then add `BASE` with `git reset --hard BASE` as the way to undo the run, and on `done` the path `D/pr-body.md`.
