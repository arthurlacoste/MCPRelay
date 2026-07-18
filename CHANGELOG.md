# Changelog

## 0.1.9

### Fixed

- Treat an existing live daemon PID file as an already-running Gate instance instead of failing interactive startup.
- Remove stale daemon PID files automatically before interactive startup.
- Isolate onboarding and CLI tests from the developer's real Gate config, logs, and release state.

## 0.1.8

### Added

- Add an aligned interactive controls menu for connection details, changelog, updates, and shutdown.
- Allow connection details and changelog panels to be toggled with their shortcut or closed with Escape.
- Relaunch Gate automatically after a successful interactive update.

### Changed

- Replace the single-line startup prompt with a clearer multi-line terminal interface.

## 0.1.7

### Fixed

- Make `gate stop` reliably terminate orphaned gateway processes on WSL by killing matching gateway processes and the listener on port 8761, with TERM-to-KILL escalation.

## 0.1.6

### Added

- Check for a newer stable Gate release at interactive startup.
- Show `press u to install` when an update is available.
- Stop managed services before launching the update command.

### Fixed

- Stop gateway processes still listening on port 8761 even when the PID file is missing or stale.
- Make the CLI version test read `VERSION` dynamically instead of requiring edits for every release.

## 0.1.5

### Changed

- Remove all automatic browser-opening behavior from installation and normal Gate usage.
- Require Python tests and duplicate-code checks to pass before creating a GitHub Release.
- Stabilize the interactive Ctrl+C test on Linux CI.

## 0.1.4

### Fixed

- Handle Ctrl+C in the global Gate CLI without displaying a Python `KeyboardInterrupt` traceback.
- Return the standard shell interrupt exit code `130` after a clean shutdown.

## 0.1.3

### Fixed

- Install runtime dependencies through `uv pip` when Gate uses an uv-managed virtual environment without bundled `pip`.
- Replace the active release symlink atomically on macOS without following the previous directory symlink.

## 0.1.2

### Fixed

- Expose the installed `src` directory through `PYTHONPATH` so the global `gate` launcher can import `gate_cli`.

### Changed

- Rewrite the README around Gate as a local MCP reverse proxy for ChatGPT web and iOS.
- Add the Agent Skills catalogue to the README and link to the detailed MCP and Skills documentation.
- Remove the README logo and contributor-focused test section.

## 0.1.1

### Changed

- Renamed the project and all legacy user-facing references to Gate.
- Moved the canonical GitHub repository to `arthurlacoste/gate`.
- Renamed runtime identifiers, environment variables, package metadata and widget URIs to Gate.

## 0.1.0

### Added

- One-line user installation through `install.sh`.
- Global `gate` command in `~/.local/bin`.
- User-managed Python 3.12 through uv and Node 22 through nvm.
- Automatic ngrok installation and first-run authentication.
- Stable tag and edge update channels.
- Atomic release activation with rollback state.
- Persistent config, data, logs and skills outside release directories.
- `gate doctor`, `gate logs`, `gate secret` and uninstall commands.
- Reuse of the onboarding ngrok tunnel during the first launch.
