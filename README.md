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

### 💻 Commands

| Tool          | Description                            |
| ------------- | -------------------------------------- |
| `run_command` | Execute a shell command with streaming |

### 🔐 Authentication

| Tool          | Description                              |
| ------------- | ---------------------------------------- |
| `auth_status` | OAuth status: issuer, audience, base_url |

### 📁 File Sharing

| Tool                 | Description                   |
| -------------------- | ----------------------------- |
| `public_file_share`  | Share a file via a public URL |
| `public_file_list`   | List active shares            |
| `public_file_revoke` | Revoke a share                |

### 🔌 Configurable MCP subservers

Servers from `config/mcp.json` are exposed through Gate with namespaced tools. The included example configures Computer Use as `computer_use_*`.

[See more about the MCP implementation and subserver configuration.](docs/installation.md#configure-mcp-subservers)

### 🧠 Agent Skills

Gate can expose a trusted local catalogue of [Agent Skills](https://agentskills.io/) through `skills_search` and `skills_read`. Skills remain stored on your machine and can be discovered from ChatGPT without being bundled into the gateway or automatically injected into every conversation.

[See how to configure the Skills catalogue.](docs/installation.md#agent-skills-catalogue)

---

## ⚠️ Security

- `run_command` executes shell commands **without restrictions** — use with caution
- OAuth tokens are signed with a local RSA key (generated in `data/oauth_private_key.pem`)
- Files shared via `public_file_share` are accessible without authentication
- Command logs contain all input/output — do not expose logs

## 📝 License

This project is licensed under the MIT License.
