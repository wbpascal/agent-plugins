# Worktree runs hand off to a fresh dispatcher

An issue run works in its own git worktree by default (`--in-place` opts out); a prompt run works in place unless given `--worktree`. The session that is invoked does not drive the run from outside the worktree. It creates the worktree, starts a fresh dispatcher inside it with the same arguments, prints where, and ends. Inside Herdr (`HC_TERMINAL_SOCKET` set) the worktree is a Herdr worktree created through its worktree mod, so each run gets its own space that the user can watch and attach to. Inside Orca (`ORCA_APP_VERSION` set and the checkout is an Orca worktree) Orca creates the worktree and starts the new dispatcher in its own agent tab (`orca worktree create --agent … --prompt …`, or `orca agent launch` when Orca already has the worktree). Unlike Herdr, Orca cannot adopt a worktree made with `git worktree add`: repositories may hide such external worktrees, so the plugin lets Orca choose the path. A branch that exists without an Orca worktree falls back to the path below, invisible in Orca. Orca takes precedence over Herdr, since its environment is set per session while Herdr's can be inherited. Elsewhere, Claude Code moves its own session into the worktree (`EnterWorktree`); Copilot cannot, so it prints the command for the user to run and stops. Worktrees are never removed by the plugin, because the user may resume a run with feedback.

## Considered Options

- **Dispatcher stays, agents get a `Workdir:` path.** No handoff, but every agent must `cd` and use absolute paths on each call, small models forget, and edits outside the project directory can trigger permission prompts.
- **Orca orchestration workers for the agents.** Each agent would get its own visible Orca chat, but workers ignore the plugin's agent definitions (models, tool limits), start as full sessions, reply through Orca's mailbox instead of the last line, and fall outside the transcripts the report reads.
- **Fall back to in place where the session cannot move.** Simpler on Copilot, but it silently breaks the promise that the user's checkout stays untouched.

## Consequences

The report covers only the dispatcher inside the worktree; the short handoff session is not counted.
