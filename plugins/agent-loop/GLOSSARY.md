# agent-loop

One agent loop works one task through planner, executor and reviewer agents until the reviewer is satisfied.

## Language

**Host**:
The agent runtime the plugin runs inside: Claude Code or GitHub Copilot (CLI, VS Code and the Copilot app). One plugin serves every host.
_Avoid_: harness, runtime, platform, target

**Dispatcher**:
The session that invoked the run skill; it spawns agents, routes on their reply, and alone talks to GitHub.
_Avoid_: orchestrator, main agent

**Task**:
The work one run carries out. Its source is either a GitHub issue or a prompt typed by the user.
_Avoid_: request, job, ad-hoc issue

**Planless run**:
A run that never spawns a planner: the executor treats the task as its plan and makes design decisions itself, and the reviewer judges against the task. Meant for small tasks given to a stronger executor and reviewer.
_Avoid_: no-plan mode, direct run, fast run

**Reply**:
The one-line final message an agent returns to the dispatcher (`PLAN`, `GREEN`, `RED`, `BLOCKED`, `DONE`, `FIX`, `REPLAN`).
_Avoid_: result, status

**Report**:
The timeline and cost summary produced when a run ends, measured in the host's own cost unit. An issue's report is posted as a comment; a prompt's report is shown to the user.
_Avoid_: summary, metrics

**Worktree**:
A separate checkout of the target repository on the run's own branch, so the user's checkout stays untouched and runs can go in parallel. An issue run uses one by default, except in the Copilot app or VS Code, which choose the session's checkout themselves; a prompt run works in place unless asked. In Herdr it is a Herdr worktree, shown as its own space; in Orca it is an Orca worktree with its own agent tab.
_Avoid_: sandbox, clone, copy

**Handoff**:
The invoking session creates the worktree, starts a fresh dispatcher inside it, and steps back. The new session is the run's dispatcher.
_Avoid_: relaunch, fork

**Finding**:
A change the reviewer requires inside the task's scope, whatever its size. The run is not done while any finding is open.
_Avoid_: blocking finding, issue, comment

**Follow-up**:
Work the reviewer sees outside the task's scope, such as a bug in untouched code or a neighbouring refactor. It is listed for the user and never done in the same run.
_Avoid_: note, non-blocking finding, nit

**Stack**:
A chain of pull requests where each one targets the branch of the one below it; the bottom one targets the trunk, such as `master`. An issue run whose base branch has an open pull request joins its own pull request to that pull request's stack.
_Avoid_: chain, dependent PR, stacked branch
