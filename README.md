# agent-plugins

A marketplace of plugins for Claude Code and GitHub Copilot (CLI and VS Code).

| Plugin | What it does |
| --- | --- |
| [agent-loop](plugins/agent-loop/README.md) | Works one GitHub issue or prompt through planner, executor and reviewer agents. |
| [proxmox](plugins/proxmox/README.md) | Inspects Proxmox VE clusters read-only, through Proxmox Datacenter Manager where one exists. |

## Install

Add the marketplace once, then install the plugins you want:

```
claude plugin marketplace add https://github.com/wbpascal/agent-plugins.git
claude plugin install agent-loop@agent-plugins
```

```
copilot plugin marketplace add https://github.com/wbpascal/agent-plugins.git
copilot plugin install agent-loop@agent-plugins
```

To load a local checkout instead, pass the plugin's folder: `--plugin-dir /path/to/agent-plugins/plugins/<plugin>`.
