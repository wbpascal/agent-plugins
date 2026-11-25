# Settings file holds the secrets, read only by the script

The plugin needs one API token for PDM and one per cluster. It keeps them in a per-user TOML file outside any repository (`%APPDATA%\agent-plugins\proxmox.toml`, `~/.config/agent-plugins/proxmox.toml`). Only `scripts/proxmox.py` reads that file. The skill reaches Proxmox only through that script, so tokens never enter the agent's context or the transcript. The script sends GET requests only, so access stays read-only even if a token has more rights than it should. The user writes the file in an editor; the agent may create it from the example but never sees a secret.

## Considered Options

- **Claude Code `userConfig` with `sensitive: true`.** It stores secrets in the keychain, but it passes them only to MCP servers and hooks, not to scripts the agent runs. Its keys are fixed in the manifest, so it can't hold a variable list of clusters. Copilot has nothing like it.
- **Environment variables.** Simple, but a variable list of clusters needs a naming scheme, Windows users set them less easily, and an agent can print them with `env`.
- **MCP server.** It would hide the tokens as well, but users would have to configure it once per host, and Copilot's plugin MCP config can't read a per-user file portably.
- **`curl` with the token in the command.** Every request would put the secret in the transcript.

## Consequences

Secrecy depends on the agent following the skill and not reading the file itself; hosts don't enforce it. Using GET only is enforced in code.
