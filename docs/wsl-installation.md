# Install Gate on WSL

Use Ubuntu in WSL. Do not run these commands from PowerShell.

## One-script installation

```bash
curl -fsSL https://raw.githubusercontent.com/arthurlacoste/gate/main/scripts/install-wsl.sh -o /tmp/install-gate.sh
bash /tmp/install-gate.sh
```

The installer:

- verifies that it is running inside WSL;
- installs Git, Python, build tools, `scrot`, Tk and other system packages;
- installs Node.js 22 through nvm;
- installs and configures ngrok;
- clones or updates Gate;
- creates the Python virtual environment;
- asks which directories Gate may access;
- asks for an OAuth access secret or securely generates one;
- opens a temporary ngrok tunnel;
- writes `config/.env` with the detected public URL and only the Argon2id secret hash;
- prints the exact custom MCP app settings for ChatGPT.

The ngrok token is entered silently and saved only by ngrok in its local configuration. It is not written to the project `.env` file. If the installer generates the OAuth access secret, it displays it once; save it immediately in a password manager.

## Start Gate

The installer prints the final project path. With the default path:

```bash
cd ~/Gate
./run.sh
```

Keep the terminal open. On the free ngrok plan, the public URL may change after restarting. When that happens, run:

```bash
cd ~/Gate
bash scripts/change-ngrok-token.sh
```

Then update the MCP server URL in ChatGPT.

## ChatGPT settings

Enable developer mode in ChatGPT web, then add a custom MCP app with:

```text
Name: mcp dl
Description: Local computer tools through Gate
Connection: Server URL
Server URL: https://YOUR-NGROK-DOMAIN/mcp
Authentication: OAuth
```

OAuth registration and token exchange are automatic. When ChatGPT opens the Gate authorization page, enter the access secret and click **Authorize**. Do not paste an OAuth token into ChatGPT.

To rotate the secret, create a new Argon2id hash, update `OAUTH_ACCESS_SECRET_HASH` in `config/.env`, and restart. Existing tokens remain valid for their configured TTL. For emergency revocation, stop Gate, delete `data/oauth_private_key.pem`, and restart to invalidate all existing tokens.

## WSL limitations

Gateway, OAuth, filesystem and shell tools work inside WSL. Paths exposed to Gate are Linux paths such as `/home/art` or Windows-mounted paths such as `/mnt/c/Users/artha`.

Screenshot, keyboard and mouse automation can be limited by WSL, WSLg, Wayland and Windows session boundaries. Keep Windows awake, signed in and unlocked while Gate is running.
