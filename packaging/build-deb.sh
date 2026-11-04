#!/usr/bin/env bash
# Build dist/gta5rp-launcher_<version>_all.deb (needs dpkg-deb).
#   packaging/build-deb.sh <version>
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VER="${1:?version required}"
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

"$SRC/packaging/stage.sh" "$ROOT"
# Debian keeps the license in /usr/share/doc/<pkg>/copyright
mv "$ROOT/usr/share/licenses/gta5rp-launcher/LICENSE" "$ROOT/usr/share/doc/gta5rp-launcher/copyright"
rm -rf "$ROOT/usr/share/licenses"

mkdir -p "$ROOT/DEBIAN"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: gta5rp-launcher
Version: $VER
Section: games
Priority: optional
Architecture: all
Depends: python3 (>= 3.9), python3-pyside6.qtcore, python3-pyside6.qtgui, python3-pyside6.qtwidgets
Recommends: python3-pyside6.qtwebenginewidgets, python3-pyside6.qtwebenginecore, python3-pyside6.qtwebchannel, python3-pyside6.qtwebsockets, python3-pyside6.qtnetwork, wine, steam-installer | steam
Suggests: 7zip
Maintainer: bagira818 <noreply@github.com>
Homepage: https://github.com/alinaz18/gta5rp-launcher-linux
Description: Unofficial GTA5RP (RAGE:MP) launcher for Linux
 Native launcher for the GTA5RP roleplay project. Shows the original GTA5RP
 interface (taken from the official installer you downloaded) with a Linux
 core: login, servers, news, live server-themed background, Linux settings,
 and one-click start of RAGE:MP through Steam's Proton. Not affiliated with
 GTA5RP.
EOF
cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
EOF
chmod 755 "$ROOT/DEBIAN/postinst"

mkdir -p "$SRC/dist"
dpkg-deb --root-owner-group --build "$ROOT" "$SRC/dist/gta5rp-launcher_${VER}_all.deb"
