---
name: inspect
description: Proxmox: read-only inspection of clusters, nodes, guests, tasks and logs via Datacenter Manager.
---

# Proxmox: read-only inspection

`PX` is `python "${CLAUDE_PLUGIN_ROOT}/scripts/proxmox.py"` (use `python3` if that is your Python 3 command; if `${CLAUDE_PLUGIN_ROOT}` is not filled in, the plugin root is two levels above this skill's base directory). Needs Python 3.11+.

Reach Proxmox only through `PX`: it alone reads the settings file and holds the API tokens, so the file's contents and the tokens stay out of this conversation. `PX` sends GET requests only; changes are the user's to make.

## Steps

1. Run `PX sources`. It lists each source (`pdm` or a cluster name) with its URLs, plus PDM remotes that have no cluster entry.
   - **No settings file:** show the user the error, offer `PX init` (copies the example to the settings path), and point to the settings docs in the error. The user fills in URLs, token IDs and secrets in an editor; secrets go into the file, never into chat. Then `PX check`, and `PX discover` prints the cluster tables to merge in.
   - **Other setup errors:** `PX check` tests every URL of every source and names what fails.
2. Route each question: start at `pdm` when it is listed, since one call covers every remote. Go to the cluster (`PX get <cluster> …`) for what PDM lacks — node journal and syslog, cluster log, HA, backup jobs, replication, disks, services — or when PDM fails or its data looks stale. Without `pdm`, start at the cluster.
3. Query with `PX get <source> <path> [key=value …]`. Pick paths from [endpoints.md](endpoints.md) by symptom; GET a directory path to list its children. Output over 50 KB is cut; narrow the query rather than paging through it.
4. Report findings with their evidence (source and path), the likely cause, and any fix as commands or UI steps for the user to run.
