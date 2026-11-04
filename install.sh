#!/usr/bin/env bash
# GTA5RP Launcher for Linux — installer / установщик
#
#   ./install.sh            install dependencies + launcher (asks for sudo password)
#   ./install.sh --no-deps  install only the launcher
#   ./install.sh --dry-run  show what would be done, change nothing
#
# The game itself runs through Steam's Proton, so Wine is not required.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA/gta5rp-launcher-app"
BIN_DIR="$HOME/.local/bin"
DEPS=1
DRY=0
for arg in "$@"; do
  case "$arg" in
    --no-deps) DEPS=0 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[1;31m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
run()  { if [ "$DRY" = 1 ]; then printf '    [dry-run] %s\n' "$*"; else "$@"; fi; }
sudo_run() { if [ "$(id -u)" = 0 ]; then run "$@"; else run sudo "$@"; fi; }

install_deps() {
  if command -v pacman >/dev/null; then
    sudo_run pacman -S --needed --noconfirm python pyside6 7zip wine || warn "pacman failed"
  elif command -v apt-get >/dev/null; then
    sudo_run apt-get update
    sudo_run apt-get install -y python3 python3-venv python3-pip curl || true
    # PySide6 is packaged only in Debian 13+ / Ubuntu 26.04+; otherwise pip is used below
    sudo_run apt-get install -y python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets \
      || warn "PySide6 is not in your repositories — it will be installed via pip."
    sudo_run apt-get install -y python3-pyside6.qtwebenginewidgets 2>/dev/null || true
    sudo_run apt-get install -y libxcb-cursor0 libxkbcommon-x11-0 libegl1 || true
    sudo_run apt-get install -y 7zip 2>/dev/null || sudo_run apt-get install -y p7zip-full || true
    sudo_run apt-get install -y wine 2>/dev/null || true
  elif command -v dnf >/dev/null; then
    sudo_run dnf install -y python3 python3-pyside6 p7zip || sudo_run dnf install -y python3 || true
  elif command -v zypper >/dev/null; then
    sudo_run zypper --non-interactive install python3 python3-pyside6 7zip || true
  else
    warn "Unknown distribution: install Python 3 and PySide6 manually."
  fi
}

PY=python3
ensure_pyside() {
  if python3 -c 'import PySide6.QtWidgets' >/dev/null 2>&1; then
    say "PySide6: system package"
    return
  fi
  say "PySide6 not found — installing into $APP_DIR/venv via pip"
  run python3 -m venv "$APP_DIR/venv"
  run "$APP_DIR/venv/bin/pip" install --upgrade pip PySide6
  PY="$APP_DIR/venv/bin/python"
}

install_files() {
  say "Installing launcher → $APP_DIR"
  run mkdir -p "$APP_DIR" "$BIN_DIR" "$DATA/applications" "$DATA/icons/hicolor/scalable/apps"
  run install -m 644 "$SRC_DIR/gta5rp_core.py" "$SRC_DIR/gta5rp_launcher.py" "$SRC_DIR/gta5rp_official.py" \
    "$SRC_DIR/gta5rp_webui.py" "$APP_DIR/"
  run mkdir -p "$APP_DIR/webui"
  run install -m 644 "$SRC_DIR/webui/enhance.css" "$SRC_DIR/webui/enhance.js" "$APP_DIR/webui/"
  run mkdir -p "$APP_DIR/webui/themes"
  run install -m 644 "$SRC_DIR"/webui/themes/*.webp "$APP_DIR/webui/themes/"
  run install -m 644 "$SRC_DIR/data/gta5rp-launcher.svg" "$DATA/icons/hicolor/scalable/apps/"
  local py; py=$(command -v "$PY" || echo "$PY")
  [ -x "$APP_DIR/venv/bin/python" ] && py="$APP_DIR/venv/bin/python"
  if [ "$DRY" = 1 ]; then
    echo "    [dry-run] write $BIN_DIR/gta5rp-launcher (python: $py)"
    return
  fi
  printf '#!/bin/sh\nexec "%s" "%s" "$@"\n' "$py" "$APP_DIR/gta5rp_launcher.py" > "$BIN_DIR/gta5rp-launcher"
  chmod +x "$BIN_DIR/gta5rp-launcher"
  # if the icon from the official installer was already extracted, keep it
  local icon=gta5rp-launcher
  [ -f "$DATA/icons/hicolor/256x256/apps/gta5rp-launcher-original.png" ] && icon=gta5rp-launcher-original
  sed -e "s|@BIN@|$BIN_DIR/gta5rp-launcher|" -e "s|^Icon=.*|Icon=$icon|" \
    "$SRC_DIR/data/gta5rp-launcher.desktop" > "$DATA/applications/gta5rp-launcher.desktop"
  update-desktop-database "$DATA/applications" 2>/dev/null || true
}

[ "$DEPS" = 1 ] && install_deps
ensure_pyside
install_files

case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR is not in PATH — start the launcher from the app menu.";; esac
say "Done! Start \"GTA5RP Launcher\" from the application menu or run: gta5rp-launcher"
say "Готово! Запустите «GTA5RP Launcher» из меню приложений или командой: gta5rp-launcher"
