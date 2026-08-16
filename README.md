# Gate — Bring local MCPs and Skills to ChatGPT

Gate is a local MCP reverse proxy that exposes your computer, MCP servers and Agent Skills through a single OAuth-protected endpoint. It lets ChatGPT reach tools running on your own machine from the web app and iOS apps, without moving the underlying services into the cloud.

Use Gate to connect local commands, files, browser automation, custom MCP servers and a trusted Skills catalogue back to your regular ChatGPT conversations.

## Installation and usage

Install Gate on macOS, Linux or WSL:

```bash
curl -fsSL https://spel.cc/gate.sh | bash
```

Then run:

```bash
gate
```

See the **[installation and usage guide](docs/installation.md)**, if you want to do it the hard way.

---

## 🛠️ Available MCP Tools

Gate starts in **discover mode**. Only seven tools are exposed by default:

| Tool | Description |
| --- | --- |
| `run_command` | Execute a local shell command |
| `skills_search` | Search the local Agent Skills catalogue |
| `skills_read` | Read a selected Agent Skill |
| `mcp_servers_list` | List downstream MCP servers, or refresh their registry |
| `mcp_tools_search` | Search tools across downstream MCP servers |
| `mcp_tool_read` | Load the schema for one discovered MCP tool |
| `mcp_tool_call` | Invoke one discovered MCP tool |

Additional first-party tools and runtime-specific helpers may be available outside this default surface. See the [installation and usage guide](docs/installation.md#configure-the-gateway) for exposure modes and configuration.

### 💻 Commands

`run_command` stays directly exposed because it is Gate's primary local execution tool.

### 🔐 Authentication (`full` mode)

| Tool          | Description                              |
| ------------- | ---------------------------------------- |
| `auth_status` | OAuth status: issuer, audience, base_url |

### 📁 File Sharing (`full` mode)

| Tool                 | Description                   |
| -------------------- | ----------------------------- |
| `public_file_share`  | Share a file via a public URL |
| `public_file_list`   | List active shares            |
| `public_file_revoke` | Revoke a share                |

### 🔌 Configurable MCP subservers

Gate uses **discovery mode by default** so large downstream MCP catalogues do not flood ChatGPT's initial tool context.

Downstream tools from `config/mcp.json` remain connected and searchable. Use `mcp_tools_search` to find one, including by its former `prefix_tool` public name, `mcp_tool_read` to load its schema, then `mcp_tool_call` to invoke it. Detailed exposure-mode and queue behavior lives in the [installation guide](docs/installation.md#configure-the-gateway).

[See more about the MCP implementation and subserver configuration.](docs/installation.md#configure-mcp-subservers)

### 🧠 Agent Skills

Gate can expose a trusted local catalogue of [Agent Skills](https://agentskills.io/) through `skills_search` and `skills_read`. Skills remain stored on your machine and can be discovered from ChatGPT without being bundled into the gateway or automatically injected into every conversation.

[See how to configure the Skills catalogue.](docs/installation.md#agent-skills-catalogue)

---

## ⚠️ Security

- `run_command` can execute local shell commands, so Gate applies a built-in destructive-command safeguard before process creation
- OAuth tokens are signed with a local RSA key (generated in `data/oauth_private_key.pem`)
- Files shared via `public_file_share` are accessible without authentication
- Command logs contain all input/output — do not expose logs

### 🛡️ Optional advanced safeguard

Gate blocks common destructive filesystem, Git, Docker, database, Kubernetes, Terraform, disk, PowerShell, cmd and WSL operations by default.

For broader protection, choose **2. Destructive Command Guard (dcg)** during Gate setup. This is a one-click install: Gate downloads the pinned [Destructive Command Guard](https://github.com/Dicklesworthstone/destructive_command_guard) release, verifies its SHA256 checksum and version, and falls back safely to the built-in guard if installation fails.

[Read the command safeguard documentation.](docs/installation.md#destructive-command-guard)

## 📝 License

This project is licensed under the MIT License.
