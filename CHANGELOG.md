# Changelog

## [0.1.20](https://github.com/spelcc/gate/compare/v0.1.19...v0.1.20) (2026-08-01)

### Fixed

- Sort completed realtime calls by date regardless of terminal status.
- Sort calls without timestamps after dated calls within the same status group.
- Preserve Gate's historical `vX.Y.Z` tag format in Release Please.

### Continuous Integration

- Add Release Please automation for version pull requests, tags, draft releases, tested archives, and checksums.
- Publish draft releases only after release tests and asset uploads pass.

## 0.1.19

### Added

- Add deterministic `skills_create` support for creating validated local skill packages.
- Add the builtin `skill-creator` workflow.

### Fixed

- Add a Windows-compatible atomic publication fallback when `dir_fd` APIs are unavailable.
- Harden POSIX skill publication against symlink swaps and temporary-directory races.
- Fix secure skill publication on macOS with Python 3.14 by resolving directory descriptors through `F_GETPATH` while preserving fd-pinned writes on Linux.
- Preserve the original publication error during temporary-directory cleanup and log unexpected cleanup failures.

### Tests

- Add focused coverage for macOS descriptor resolution, fail-closed behavior, cleanup, and platform-specific write paths.

## 0.1.18

### Added

- Add a daemon log monitor for viewing Gate runtime output without opening raw log files.
- Add Tailscale as a tunnel provider alongside ngrok.
- Add MCP server auto-discovery and hot reload through the local registry.
- Add explicit version and prerelease update support to the Gate CLI.

### Changed

- Enforce a structured pull request template and validate pull request bodies in CI.
- Improve release asset and updater validation for explicit and prerelease versions.

### Tests

- Add focused coverage for daemon logs, tunnel providers, MCP registry reloads, release assets, updater behavior, and pull request validation.

## 0.1.17

### Fixed

- Probe gateway readiness through the same resolved LAN target used by ngrok on macOS.
- Avoid false startup timeouts when another process owns loopback port `8761`.

### Tests

- Add coverage ensuring gateway health checks follow the resolved ngrok target and retain the loopback fallback elsewhere.

## 0.1.16

### Fixed

- Route ngrok to the active macOS LAN address so a loopback-only listener on port `8761` cannot expose the wrong OAuth/JWKS instance.
- Add `GATE_NGROK_TARGET` as an explicit cross-platform upstream override.

### Tests

- Add focused coverage for macOS address discovery, fallback behavior, overrides, and launcher integration.

## 0.1.15

### Added

- Add an interactive **Realtime calls** monitor with bounded, redacted command previews and lifecycle status.
- Add a README security overview for the built-in safeguard and one-click verified `dcg` installation.

### Changed

- Keep realtime monitoring active in both blocking and queued command modes.
- Rename the asynchronous queue opt-in to `--queue` and `MCP_COMMAND_QUEUE_ENABLED`, while preserving the legacy realtime aliases.
- Guide agents to poll queued commands through `get_command_state` instead of reading internal log references.

### Security

- Keep realtime snapshots private, bounded, and sanitized before persistence.
- Update pinned authentication, multipart, and cryptography dependencies.

### Tests

- Add focused coverage for realtime rendering, state ordering, redaction, blocking-mode monitoring, and queue polling.

## 0.1.14

### Fixed

- Detect a compatible Python interpreter before creating the virtual environment, with clearer handling for unsupported Python versions.
- Use the virtual environment interpreter for startup dependency and SSL checks.
- Handle missing SSL support and ngrok `web_allow_hosts` startup edge cases more reliably.
- Reduce flaky command queue, onboarding, skill catalog, and startup tests.

### Tests

- Add focused coverage for Python bootstrap, startup compatibility, onboarding, and command queue behavior.

## 0.1.13

### Fixed

- Support Alpine Linux 3.22 in the installer by installing Node.js 22 with `apk` instead of requesting unavailable musl binaries through NVM.
- Run NVM outside `nounset` mode with a defined temporary directory on non-Alpine systems.

### Tests

- Add automated Alpine installer coverage using the `alpine:3.22` container image.

## 0.1.12

### Added

- Add pluggable destructive-command guards with dependency-free `builtin` and optional verified `dcg` providers.
- Return structured denial reasons and safe remediation commands before destructive shell execution.
- Guard local and proxied shell tools, including `run_command` and `filesystem_execute_tool`.
- Add temporary `gate --noguard` support for a single launch without changing saved configuration.
- Add first-run command guard provider selection.

### Changed

- Encrypt queued command payloads so commands can safely resume after restart while displayed state remains redacted.
- Add tool, host, platform, working directory, provider, rule, and remediation details to guard audit events.

### Security

- Redact secrets from command logs, queue state, proxy logs, and conversation logs.
- Verify pinned DCG release checksums and executable versions before use, with automatic fallback to the built-in provider.

## 0.1.11

### Fixed

- Keep the running Gate instance online when update discovery or download fails, including GitHub API rate limits.
- Stop and restart services only after a release has been downloaded, verified, and installed successfully.

## 0.1.10

### Changed

- Replace fixed 2-second startup waits with health-check polls for faster startup.
- Gateway waits for `/oauth/health` instead of sleeping blindly.
- ngrok waits for the local API tunnel response instead of sleeping blindly.
- Move GitHub update check to a background thread so it never blocks the UI.

### Fixed

- Skip redundant dependency installation on warm starts using an mtime sentinel.

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
