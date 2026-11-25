# proxmox

A plugin for Claude Code and GitHub Copilot (CLI and VS Code) that lets the agent inspect Proxmox VE clusters read-only. It starts at Proxmox Datacenter Manager (PDM), which sees every cluster. It goes to a cluster itself for what PDM doesn't show: node logs, cluster log, HA, backup jobs, replication, disks and services. A single cluster without PDM works too.

Ask about a problem ("why did last night's backup of VM 104 fail?") and the agent fires the `inspect` skill on its own, or call it with `/proxmox:inspect`.

The agent reaches Proxmox only through `scripts/proxmox.py`, which:

- sends GET requests only, whatever rights a token has;
- alone reads the settings file, so tokens never enter the conversation;
- removes `token`, `secret`, `password` and `ticket` fields from answers;
- tries each node of a cluster in turn until one answers.

Requires Python 3.11 or later.

## Install

```
claude plugin marketplace add https://github.com/wbpascal/agent-plugins.git
claude plugin install proxmox@agent-plugins
```

For Copilot, use `copilot plugin …` with the same arguments.

## Settings

The settings file holds the API tokens. It lives outside any repository:

| OS | Path |
| --- | --- |
| Windows | `%APPDATA%\agent-plugins\proxmox.toml` |
| Linux, macOS | `~/.config/agent-plugins/proxmox.toml` (or under `$XDG_CONFIG_HOME`) |

Set `AGENT_PROXMOX_SETTINGS` to use another path. Outside Windows, the script refuses a file that other users can read (`chmod 600`).

### Set up

Run these commands from `plugins/proxmox/` in a checkout, or ask the agent to run them.

1. Create read-only tokens (below).
2. `python scripts/proxmox.py init` creates the file from [settings.example.toml](settings.example.toml). Or ask the agent, which offers this when the file is missing.
3. Open the file in an editor and fill in `[pdm]`, or one cluster if you have no PDM. Paste the secret yourself; don't give it to the agent.
4. `python scripts/proxmox.py check` tests every URL of every source.
5. `python scripts/proxmox.py discover` prints a `[clusters.<name>]` table for each cluster, without secrets. Merge them in and add each cluster's token.
   - **With PDM:** one table per PDM remote, with its node addresses and certificate fingerprints.
   - **Without PDM:** `discover <cluster>` reads the cluster's own node list.

### Format

```toml
[pdm]                                  # optional
urls = ["https://pdm.example.com:8443"]
token_id = "ai@pdm!analysis"
secret = "…"
fingerprints = ["AB:CD:…"]             # optional

[clusters.prod-fra]                    # name = the cluster's PDM remote id
urls = ["https://10.0.0.1:8006", "https://10.0.0.2:8006"]
token_id = "ai@pve!analysis"
secret = "…"
fingerprints = ["AB:CD:…", "EF:01:…"]  # optional, one per node
```

- **`urls`:** list every node. The script tries them in order, so a cluster stays reachable when a node is down. The port defaults to 8443 for PDM and 8006 for a cluster.
- **`fingerprints`:** the SHA-256 certificate fingerprints to accept, for self-signed certificates. The certificate must match one of them, and the token is sent only after that check. Without `fingerprints`, the system's trusted CAs are used.
  - **Find a fingerprint:** in the node's web UI under System → Certificates, or with `pvenode cert info`. When a fingerprint doesn't match, the error shows the one the server presented; compare it before pasting.
  - **Windows:** Python there trusts only the root certificates already in the Windows store. If a CA-signed node fails verification, pin its fingerprint.

### Read-only tokens

**On each cluster**, once per cluster on any node:

```bash
pveum user add ai@pve --comment "AI read-only"
pveum role add AIReadOnly --privs "Sys.Audit,Sys.Syslog,VM.Audit,Datastore.Audit,SDN.Audit,Pool.Audit,Mapping.Audit"
pveum user token add ai@pve analysis --privsep 1
pveum acl modify / --users ai@pve --roles AIReadOnly
pveum acl modify / --tokens 'ai@pve!analysis' --roles AIReadOnly
```

The built-in `PVEAuditor` role can't read logs, hence `Sys.Syslog` in a custom role.

**On PDM**, under Configuration → Access Control:

1. Add a user `ai@pdm`.
2. Give it an API token `analysis`.
3. Grant the role `Auditor` on `/` to both the user and the token `ai@pdm!analysis`.

Never reuse the token PDM uses to reach the clusters; it usually has write rights.

## Tests

From `plugins/proxmox/`:

```
python3 -m unittest discover -s tests
```
