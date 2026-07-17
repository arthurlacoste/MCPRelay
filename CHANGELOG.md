# Changelog

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
