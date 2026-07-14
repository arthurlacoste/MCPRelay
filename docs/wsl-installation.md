# Install MCPRelay on WSL

Use Ubuntu in WSL. Do not run these commands from PowerShell.

## One-script installation

```bash
curl -fsSL https://raw.githubusercontent.com/arthurlacoste/MCPRelay/main/install-wsl.sh -o /tmp/install-mcprelay.sh
bash /tmp/install-mcprelay.sh
```

The installer:

- verifies that it is running inside WSL;
- installs Git, Python, build tools, `scrot`, Tk and other system packages;
- installs Node.js 22 through nvm;
- installs and configures ngrok;
- clones or updates MCPRelay;
- creates the Python virtual environment;
- asks which directories MCPRelay may access;
- opens a temporary ngrok tunnel;
- writes `config/.env` with the detected public URL;
- prints the exact custom MCP app settings for ChatGPT.

The ngrok token is entered silently and saved only by ngrok in its local configuration. It is not written to the project `.env` file.

## Start MCPRelay

The installer prints the final project path. With the default path:

```bash
cd ~/MCPRelay
./run.sh
```

Keep the terminal open. On the free ngrok plan, the public URL may change after restarting. When that happens, update the public URL values in `config/.env` and update the MCP server URL in ChatGPT.

## ChatGPT settings

Enable developer mode in ChatGPT web, then add a custom MCP app with:

```text
Name: mcp dl
Description: Local computer tools through MCPRelay
Connection: Server URL
Server URL: https://YOUR-NGROK-DOMAIN/mcp
Authentication: OAuth
```

OAuth registration and token exchange are automatic. Do not paste an OAuth token into ChatGPT.

## WSL limitations

Gateway, OAuth, filesystem and shell tools work inside WSL. Paths exposed to MCPRelay are Linux paths such as `/home/art` or Windows-mounted paths such as `/mnt/c/Users/artha`.

Screenshot, keyboard and mouse automation can be limited by WSL, WSLg, Wayland and Windows session boundaries. Keep Windows awake, signed in and unlocked while MCPRelay is running.
