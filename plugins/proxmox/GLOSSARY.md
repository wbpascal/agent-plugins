# proxmox

Read-only inspection of Proxmox VE clusters, starting at Proxmox Datacenter Manager when the environment has one.

## Language

**Cluster**:
One Proxmox VE cluster, or a single standalone Proxmox VE node. Every node serves the whole cluster's API.
_Avoid_: datacenter, site, environment

**Remote**:
A cluster as Proxmox Datacenter Manager knows it, named by its remote id. A cluster in the settings carries the same name as its remote.
_Avoid_: connection, member

**Source**:
An API the plugin reads from: Proxmox Datacenter Manager or a cluster.
_Avoid_: target, backend, endpoint
