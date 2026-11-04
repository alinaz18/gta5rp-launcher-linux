#!/usr/bin/env bash
# Удаляет лаунчер. Игра, RAGE:MP и префикс Steam не трогаются.
set -eu
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
rm -rf "$DATA/gta5rp-launcher-app" "$HOME/.local/bin/gta5rp-launcher" \
  "$DATA/applications/gta5rp-launcher.desktop" \
  "$DATA/icons/hicolor/scalable/apps/gta5rp-launcher.svg" \
  "$DATA/icons/hicolor/256x256/apps/gta5rp-launcher-original.png"
echo "Лаунчер удалён. Настройки и вход: ~/.config/gta5rp-launcher, интерфейс и кэш:"
echo "~/.local/share/gta5rp-launcher и ~/.cache/gta5rp-launcher (удалите вручную при желании)."
