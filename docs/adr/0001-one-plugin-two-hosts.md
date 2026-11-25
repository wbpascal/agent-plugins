# One plugin, two hosts

GitHub Copilot (CLI and VS Code) loads Claude Code plugins as they are. It reads `.claude-plugin/plugin.json` and `marketplace.json`, `agents/*.md` and `skills/*/SKILL.md`, and expands `${CLAUDE_PLUGIN_ROOT}`. We therefore ship each plugin once for both hosts. There is no `.github/plugin/plugin.json`, no Agent Plugins manifest and no `*.agent.md` copies. Where a host needs its own setting, its field sits in the shared file and the other host ignores it, such as `models:` and `modelPolicy:` for Copilot next to `model:` for Claude. We keep one source of truth for every prompt, but we depend on compatibility that Copilot documents only loosely. If a Copilot update breaks this, check that compatibility first.

## Considered Options

- **Separate Copilot manifest and `*.agent.md` files.** This follows Copilot's documented layout, but every prompt would exist twice and the copies would drift.
- **Per-user model overrides in `~/.copilot/settings.json`.** This keeps Copilot-only fields out of the repository, but every user would have to configure the models before their first run.
