#!/usr/bin/env bash
set -Eeuo pipefail

REPO="arthurlacoste/MCPRelay"
API="https://api.github.com/repos/$REPO"
RELEASE_API="https://api.github.com/repos/arthurlacoste/MCPRelay/releases/latest"
GATE_ROOT="${GATE_INSTALL_DIR:-$HOME/.gate}"
BIN_DIR="$HOME/.local/bin"
NODE_VERSION="22"
PYTHON_VERSION="3.12"
YES=false
START="${GATE_START:-ask}"

for arg in "$@"; do
  case "$arg" in
    --yes|-y) YES=true ;;
    *) printf 'Unknown installer option: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

info() { printf '\n\033[1;34m%s\033[0m\n' "$*"; }
ok() { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

ask_yes() {
  local prompt="$1" answer
  if [ "$YES" = true ]; then return 0; fi
  printf '%s' "$prompt" >/dev/tty
  IFS= read -r answer </dev/tty || true
  case "$answer" in ""|y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

need() { command -v "$1" >/dev/null 2>&1; }

install_uv() {
  need uv && return 0
  info "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  need uv || die "uv installation failed."
}

install_python() {
  info "Preparing Python $PYTHON_VERSION"
  uv python install "$PYTHON_VERSION"
}

install_nvm_node() {
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  if [ ! -s "$NVM_DIR/nvm.sh" ]; then
    info "Installing nvm"
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
  fi
  # shellcheck disable=SC1090
  . "$NVM_DIR/nvm.sh"
  info "Preparing Node $NODE_VERSION"
  nvm install "$NODE_VERSION"
  nvm alias default "$NODE_VERSION" >/dev/null
}

install_ngrok() {
  need ngrok && return 0
  local os arch url archive tmp
  os="$(uname -s)"; arch="$(uname -m)"
  case "$os:$arch" in
    Darwin:arm64) url="https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-darwin-arm64.zip" ;;
    Darwin:x86_64) url="https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-darwin-amd64.zip" ;;
    Linux:x86_64) url="https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz" ;;
    Linux:aarch64|Linux:arm64) url="https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz" ;;
    *) die "Unsupported platform for automatic ngrok installation: $os $arch" ;;
  esac
  info "Installing ngrok"
  mkdir -p "$GATE_ROOT/runtime/bin"
  tmp="$(mktemp -d)"; archive="$tmp/ngrok"
  curl -fsSL "$url" -o "$archive"
  case "$url" in *.zip) unzip -q "$archive" -d "$tmp" ;; *) tar -xzf "$archive" -C "$tmp" ;; esac
  install -m 755 "$tmp/ngrok" "$GATE_ROOT/runtime/bin/ngrok"
  rm -rf "$tmp"
  export PATH="$GATE_ROOT/runtime/bin:$PATH"
}

ensure_ngrok_auth() {
  ngrok config check >/dev/null 2>&1 && return 0
  if [ -z "${GATE_NGROK_AUTHTOKEN:-}" ]; then
    need open && open "https://dashboard.ngrok.com/get-started/your-authtoken" >/dev/null 2>&1 || true
    need xdg-open && xdg-open "https://dashboard.ngrok.com/get-started/your-authtoken" >/dev/null 2>&1 || true
    printf 'Paste your ngrok authtoken: ' >/dev/tty
    IFS= read -r -s GATE_NGROK_AUTHTOKEN </dev/tty
    printf '\n' >/dev/tty
  fi
  [ -n "${GATE_NGROK_AUTHTOKEN:-}" ] || die "ngrok authtoken is required."
  ngrok config add-authtoken "$GATE_NGROK_AUTHTOKEN" >/dev/null
  unset GATE_NGROK_AUTHTOKEN
  ngrok config check >/dev/null 2>&1 || die "ngrok authentication failed."
}

latest_release_assets() {
  curl -fsSL "$RELEASE_API" | uv run --python "$PYTHON_VERSION" python -c '
import json,sys
release=json.load(sys.stdin)
tag=release.get("tag_name", "")
assets={a.get("name"): a.get("browser_download_url") for a in release.get("assets", [])}
archive=assets.get(f"gate-{tag}.tar.gz", "")
checksums=assets.get("SHA256SUMS", "")
if not tag or not archive or not checksums:
    raise SystemExit("Latest GitHub Release is missing gate-<tag>.tar.gz or SHA256SUMS")
print(tag)
print(archive)
print(checksums)'
}

verify_archive_checksum() {
  local archive="$1" tag="$2" checksums_url="$3" manifest expected actual
  manifest="$(curl -fsSL "$checksums_url")" || die "Could not download SHA256SUMS."
  expected="$(printf '%s\n' "$manifest" | awk -v name="gate-$tag.tar.gz" '$2 == name {print $1; exit}')"
  [ -n "$expected" ] || die "No SHA256 checksum published for $tag."
  if command -v shasum >/dev/null 2>&1; then
    actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
  elif command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "$archive" | awk '{print $1}')"
  elif command -v openssl >/dev/null 2>&1; then
    actual="$(openssl dgst -sha256 "$archive" | awk '{print $NF}')"
  else
    die "No SHA256 tool available."
  fi
  [ "$actual" = "$expected" ] || die "Gate archive checksum mismatch."
}

install_release() {
  local tag archive_url checksums_url archive tmp extracted release python assets
  assets="$(latest_release_assets)"
  tag="$(printf '%s\n' "$assets" | sed -n '1p')"
  archive_url="$(printf '%s\n' "$assets" | sed -n '2p')"
  checksums_url="$(printf '%s\n' "$assets" | sed -n '3p')"
  archive="$(mktemp)"; tmp="$(mktemp -d)"
  info "Installing Gate $tag"
  curl -fsSL "$archive_url" -o "$archive"
  verify_archive_checksum "$archive" "$tag" "$checksums_url"
  tar -xzf "$archive" -C "$tmp"
  extracted="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
  release="$GATE_ROOT/releases/$tag"
  rm -rf "$release.next"; mv "$extracted" "$release.next"
  python="$(uv python find "$PYTHON_VERSION")"
  uv venv --python "$python" "$release.next/.venv"
  uv pip install --python "$release.next/.venv/bin/python" -r "$release.next/requirements.txt"
  mv "$release.next" "$release"
  ln -sfn "$release" "$GATE_ROOT/current.next"
  mv -f "$GATE_ROOT/current.next" "$GATE_ROOT/current"
  rm -rf "$tmp" "$archive"
  printf '{"schema_version":1,"channel":"stable","active_version":"%s","active_release":"%s","previous_version":"","previous_release":"","commit":null}\n' "${tag#v}" "$release" > "$GATE_ROOT/state.json"
}

install_launcher() {
  mkdir -p "$BIN_DIR"
  cat > "$HOME/.local/bin/gate" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${GATE_INSTALL_DIR:-$HOME/.gate}"
export GATE_ROOT="$ROOT"
export GATE_PROJECT_DIR="$ROOT/current"
export MCP_CONFIG_ROOT="$ROOT/config"
export MCP_DATA_ROOT="$ROOT/data"
export MCP_LOG_ROOT="$ROOT/logs"
export MCP_SKILLS_ROOT="$ROOT/skills"
export PATH="$ROOT/runtime/bin:${NVM_DIR:-$HOME/.nvm}/versions/node/$(ls -1 "${NVM_DIR:-$HOME/.nvm}/versions/node" 2>/dev/null | sort -V | tail -1)/bin:$PATH"
exec "$ROOT/current/.venv/bin/python" -m gate_cli "$@"
EOF
  chmod 755 "$HOME/.local/bin/gate"
  local rc
  case "${SHELL:-}" in
    */zsh) rc="$HOME/.zshrc" ;;
    */bash) rc="$HOME/.bashrc" ;;
    */fish) rc="$HOME/.config/fish/config.fish"; mkdir -p "$(dirname "$rc")" ;;
    *) rc="$HOME/.profile" ;;
  esac
  if ! grep -Fq '# Gate CLI' "$rc" 2>/dev/null; then
    if [[ "$rc" == *fish* ]]; then printf '\n# Gate CLI\nfish_add_path "$HOME/.local/bin"\n' >> "$rc"
    else printf '\n# Gate CLI\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc"; fi
  fi
}

mkdir -p "$GATE_ROOT"/{releases,config,data,logs,skills,runtime,cache,backups}
install_uv
install_python
install_nvm_node
install_ngrok
ensure_ngrok_auth
install_release
install_launcher
ok "Gate installed"
if [ "$START" = "true" ] || { [ "$START" = "ask" ] && ask_yes "Start Gate now? [Y/n] "; }; then
  "$HOME/.local/bin/gate"
else
  printf 'Run Gate with: %s\n' "$HOME/.local/bin/gate"
fi
