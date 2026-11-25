# Endpoints by symptom

Paths go after `PX get <source>`. `{node}`, `{vmid}`, `{upid}` and `{storage}` come from earlier answers; `/cluster/resources type=vm` or PDM's `/resources/list` tells which node a guest is on. Times are Unix epoch seconds. GET a directory path to list its children.

## PDM (`pdm`)

| Need | Path |
| --- | --- |
| Everything across remotes: guests, nodes, storage, with status | `/resources/list` |
| Counts of running, stopped and failed items | `/resources/status` |
| Remotes and their node addresses | `/remotes/remote` |
| Recent tasks across remotes | `/remotes/tasks/list` |
| One remote: cluster state, resources, tasks | `/pve/remotes/{remote}/cluster-status`, `/resources`, `/tasks` |
| One remote: task log | `/pve/remotes/{remote}/tasks/{upid}/log` |
| One remote: node status, metrics | `/pve/remotes/{remote}/nodes/{node}/status`, `/rrddata` |
| One remote: guest config, pending changes, metrics | `/pve/remotes/{remote}/qemu/{vmid}/config`, `/pending`, `/rrddata` (`lxc` likewise) |

## Cluster (`<cluster>`)

**Node offline, quorum lost**
- `/cluster/status`: `quorate` on the cluster entry, `online` per node
- `/cluster/log max=100`
- `/nodes/{node}/journal lastentries=200` (also `since=`, `until=`)
- `/nodes/{node}/services`, `/nodes/{node}/status`

**Guest won't start, crashes or is slow**
- `/nodes/{node}/qemu/{vmid}/status/current`, `/config`, `/pending` (`lxc` likewise)
- `/nodes/{node}/tasks vmid={vmid} errors=1`, then `/nodes/{node}/tasks/{upid}/log`
- `/nodes/{node}/qemu/{vmid}/rrddata timeframe=hour cf=AVERAGE`, and `/nodes/{node}/rrddata` for the host

**Storage full or unavailable**
- `/nodes/{node}/storage`: active, enabled, usage per storage
- `/storage`: storage configuration
- `/nodes/{node}/disks/list`, `/nodes/{node}/disks/smart disk=/dev/sdX`
- `/nodes/{node}/disks/zfs`, `/nodes/{node}/disks/zfs/{pool}`, `/nodes/{node}/disks/lvm`, `/nodes/{node}/disks/lvmthin`

**Backup or other task failed**
- `/cluster/tasks`, `/nodes/{node}/tasks errors=1 limit=50` (also `typefilter=vzdump`, `since=`)
- `/nodes/{node}/tasks/{upid}/log limit=500`
- `/cluster/backup`: backup jobs; `/cluster/backup-info/not-backed-up`
- `/nodes/{node}/storage/{storage}/content content=backup`

**HA**
- `/cluster/ha/status/current`, `/cluster/ha/resources`
- `/cluster/ha/rules` (Proxmox VE 9) or `/cluster/ha/groups` (8)
- `/nodes/{node}/journal` around the event, for `pve-ha-crm` and `pve-ha-lrm`

**Replication**
- `/cluster/replication`: jobs
- `/nodes/{node}/replication`: state and last error per job
- `/nodes/{node}/replication/{id}/log`
