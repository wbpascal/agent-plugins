# proxmox

The `inspect` skill lets the agent inspect Proxmox VE clusters read-only through `scripts/proxmox.py`. `README.md` describes it from the user's side. Paths below are relative to `plugins/proxmox/`.

## Design rules

These were decided with the user; changing one is a design change, so raise it first.

- **Read-only.** The script sends GET only. Fixes are reported to the user, never applied.
- **Only the script reads the settings file** ([ADR 0001](docs/adr/0001-settings-file-holds-secrets.md)). No command takes a secret as an argument, and no output, error included, contains a secret. Secrets reach the file only by the user's own editing.
- **PDM first.** Go to a cluster for what PDM lacks or when PDM fails. A setup without PDM, possibly a single cluster or node, must keep working.
- **A cluster's settings name is its PDM remote id.** `sources` and `discover` depend on it.
- **No Proxmox Backup Server, Ceph, SDN or firewall coverage** until the user asks for it.

## Facts the code depends on

Verified against PDM source (`proxmox/proxmox-datacenter-manager`, `server/src/auth/mod.rs`, `server/src/api/remotes/mod.rs`, `lib/pdm-api-types/src/remotes.rs`):

- PDM token header: `PDMAPIToken=<user@realm!name>:<secret>`. PVE: `PVEAPIToken=<user@realm!name>=<secret>`. Both under `/api2/json`; default ports 8443 (PDM) and 8006 (PVE).
- `GET /remotes/remote` lists remotes with `id`, `type` (`pve`/`pbs`) and `nodes`, property strings `hostname=…[,fingerprint=…]` whose default key is `hostname`. PDM blanks `token` itself; the script redacts anyway.
- PDM proxies a subset of each PVE remote under `/pve/remotes/{remote}/…`. It has no node journal or syslog, cluster log, HA, backup jobs, replication, disks or services.

## Working here

- Tests, from `plugins/proxmox/`: `python3 -m unittest discover -s tests`.
- `skills/inspect/endpoints.md` is the per-symptom path list; keep `SKILL.md` free of paths.
- Test against a real PDM or cluster only with read-only tokens.
