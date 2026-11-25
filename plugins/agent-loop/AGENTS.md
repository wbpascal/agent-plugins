# agent-loop

`/agent-loop:run <issue>` works one GitHub issue, `/agent-loop:run <prompt>` one typed prompt, through planner, executor and reviewer agents. `README.md` describes the behaviour from the user's side. This file holds what the code does not say; paths are relative to `plugins/agent-loop/`.

## Where this is going

The plugin is the first step, built to collect experience with loops. The intended end state is a standalone loop manager, parked until that experience exists:

- Elixir/Phoenix service that drives the loop, with a web UI showing the current issue, iteration, running agent and history.
- Runs inside a Kubernetes agent sandbox (https://agent-sandbox.sigs.k8s.io).
- Picks issues itself, one after another, respecting issue dependencies and an optional label filter.

Keep these out of the plugin until the user asks for them.

## Design rules

These were decided with the user; changing one is a design change, so raise it first.

- **The dispatcher carries paths, not content.** The main session spawns agents, waits, and routes on a one-line reply (`PLAN`, `GREEN`, `RED`, `BLOCKED`, `DONE`, `FIX`, `REPLAN`). It reads no plan, report or review file. This keeps it cheap enough to run on a small model.
- **Agents never call or wait on each other.** Only the dispatcher spawns. A waiting agent's prompt cache goes cold and the next turn pays full input price. This is why there is no advisor agent: the executor returns `BLOCKED` and the dispatcher starts a fresh planner.
- **Every agent starts fresh** and hands over through files in `.agent-loop/<issue or slug>/` of the target repository.
- **Only the dispatcher uses `gh` and `git push`.** The executor commits; planner and reviewer write only their own output file.
- **A worktree run hands off.** The invoked session creates the worktree, starts a fresh dispatcher inside it and ends ([ADR 0002](docs/adr/0002-worktree-runs-hand-off.md)). The plugin never removes a worktree.
- **A prompt run stays local.** It commits on the user's current branch (on `agent/<slug>` in a worktree), never pushes or calls `gh`, and prints its report instead of posting it. Its base is the commit SHA at the start, kept on `--resume`.
- **One reviewer, three mandatory sections** (functionality, security, maintainability). Splitting into specialised reviewers is an open option if the security section proves shallow in practice.
- **The reviewer reports, the executor changes code.** Large problems go to a fresh planner (`REPLAN`), small ones to the executor (`FIX`).
- **Effort defaults live in `skills/run/SKILL.md`.** Both hosts accept per-call effort, so pass it with every spawn. Frontmatter would need three spellings (`effort`, `reasoningEffort`, `reasoning-effort`), one unverified. Models stay in frontmatter because their names differ by host.

## Coupling to keep in sync

- Keep reply words in sync across `skills/run/SKILL.md`, the last line of each `agents/*.md`, exec and review headers (`STATUS:` / `VERDICT:`), and `report.py` (`REPLY`).
- File names `plan-k.md`, `exec-k.md`, `review-k.md`, `ci-k.md`, `pr-body.md` are shared by the skill, the agents and `report.py` (`RESULT_FILE`).
- The task file is `issue.json` (written by `report.py init`) or `task.md` (written by the dispatcher). The agent prompt lines `Issue number:`, `Task:`, `Base:` and `Plan: none` are shared by the skill and the agents.
- `report.py init` prints `Dir:`, `Base:`, in a linked worktree `Worktree:`, and in an Orca worktree `Orca: yes`; `report.py worktree` prints `Worktree:`, `Herdr:` and `Space:`, or in Orca `Orca: create` with `Start:`, or `Worktree:` with `Orca: launch`.; `report.py ci` prints `CI:` and, on red, `Log:`. The skill reads these lines.
- `report.py worktree` mirrors the path layout of Herdr's shipped `worktree` mod (`<worktrees.directory>/<repo>/<branch with / as ->`), so the space nests under its repo.
- Per-role models live in the same agent file: `model:` for Claude Code, `models:`/`modelPolicy:` for Copilot.
- `report.py` matches Claude Code metadata `agentType` and Copilot `subagent.started` `agentName` against `ROLES`.

## Transcript format facts

`report.py` depends on Claude Code internals, verified on version 2.1.325:

- Main transcript: `~/.claude/projects/<project>/<session-id>.jsonl`. Subagents: `<session-id>/subagents/agent-<id>.jsonl` with `agent-<id>.meta.json` beside it.
- One API response spans several transcript lines that repeat the same `message.id` and usage. Summing lines overcounts; the script keeps the last line per id.
- Usage splits cache writes into 5-minute and 1-hour tokens, priced differently.
- Plan usage (rate limit percentages) reaches only the status line command, hence `scripts/statusline-wrapper.sh`.
- Whether Claude Code transcripts record effort is unverified. The report shows only Copilot effort (`data.usage.reasoningEffort` on `session.usage_record`).

When a Claude Code update breaks the report, check these first.

### Copilot transcript facts

Unverified until the first real plugin run; record the Copilot CLI version and verify the dispatcher session ID then. Schema sampled from VS Code (`copilot-agent` 1.0.108-0):

- `$COPILOT_HOME/session-state/<session-id>/events.jsonl` (`~/.copilot` by default); session id from `COPILOT_AGENT_SESSION_ID`.
- `session.usage_record` stores model, token counts, `cost`, `duration`, `initiator`, `interactionType` and subagent `parentToolCallId` in `data.usage`. `agentId` is top-level on subagent records. Input includes cache reads/writes; output includes reasoning.
- `subagent.started` has `agentName`, `model`, `modelSelectionSource`, `executionMode` and `toolCallId`; `subagent.configured` / `subagent.selected` describe selection. Match `tool.execution_start` / `tool.execution_complete` for `task`. Background completion of `task` can be a launch acknowledgement; `subagent.completed` marks the actual end.
- `session.usage_checkpoint` carries `data.accountingSnapshot` rollups (`modelMetrics`, `agentMetrics`, `totalPremiumRequestCost`); use usage records for run-scoped totals.

## Orca facts

Verified on Orca 1.4.266: every Orca session sets `ORCA_APP_VERSION`; `orca worktree show --worktree branch:B` fails for a worktree made by `git worktree add` when the repo hides external worktrees; `worktree create --branch B` keeps `B` exactly (a taken name gets a suffix) and `--base-branch` takes a SHA. Unverified: whether `--prompt '/agent-loop:run …'` starts the skill in a new chat or terminal agent, and Copilot inside Orca.

## Working here

- Tests, from `plugins/agent-loop/`: `python3 -m unittest discover -s tests`.
- `scripts/prices.json` is copied by hand from https://platform.claude.com/docs/en/about-claude/pricing. Re-read that page before editing prices.
- Keep `skills/run/SKILL.md` shell commands portable across Bash and PowerShell.
- Editing `skills/run/SKILL.md` or `agents/*.md`: every line is paid for on each run, by the dispatcher or an agent.
- A real run opens a PR and posts comments. Test changes to the loop in a throwaway repository.
