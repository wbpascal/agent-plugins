# agent-plugins

A marketplace of plugins in `plugins/<name>/`, each one plugin for both hosts, Claude Code and GitHub Copilot (CLI and VS Code). Decisions that hold for every plugin are in `docs/adr/`; each plugin keeps its own in `plugins/<name>/docs/adr/`. `GLOSSARY-MAP.md` lists each plugin's glossary.

## Plugins

Before working on a plugin, read its `AGENTS.md`:

- `plugins/agent-loop/AGENTS.md`
- `plugins/proxmox/AGENTS.md`

## Working here

- Each plugin's `scripts/` is Python standard library only and runs on Windows, macOS and Linux, so a plugin works anywhere without installing anything.
- Keep shell commands in skills and agents portable across Bash and PowerShell.
- Validate a plugin: `claude plugin validate plugins/<name>`; the marketplace: `claude plugin validate .`
- Editing a skill or agent file: every line is paid for on each run. State the target behaviour, keep one source of truth per rule, and delete sentences the model would follow anyway.
