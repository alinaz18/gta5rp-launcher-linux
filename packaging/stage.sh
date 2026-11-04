#!/usr/bin/env bash
# Lay out the launcher files for a system-wide package (deb / rpm / PKGBUILD).
#   packaging/stage.sh <destdir> [prefix=/usr]
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:?destdir required}"
PREFIX="${2:-/usr}"

install -Dm644 "$SRC/gta5rp_launcher.py"        "$DEST$PREFIX/share/gta5rp-launcher/gta5rp_launcher.py"
install -Dm644 "$SRC/gta5rp_core.py"            "$DEST$PREFIX/share/gta5rp-launcher/gta5rp_core.py"
for f in gta5rp_official.py gta5rp_webui.py webui/enhance.css webui/enhance.js; do
  install -Dm644 "$SRC/$f" "$DEST$PREFIX/share/gta5rp-launcher/$f"
done
install -Dm644 "$SRC/data/gta5rp-launcher.svg"     "$DEST$PREFIX/share/icons/hicolor/scalable/apps/gta5rp-launcher.svg"
install -Dm644 "$SRC/LICENSE"                    "$DEST$PREFIX/share/licenses/gta5rp-launcher/LICENSE"
install -Dm644 "$SRC/README.md"                  "$DEST$PREFIX/share/doc/gta5rp-launcher/README.md"
install -Dm644 "$SRC/README.en.md"               "$DEST$PREFIX/share/doc/gta5rp-launcher/README.en.md"

install -dm755 "$DEST$PREFIX/bin" "$DEST$PREFIX/share/applications"
cat > "$DEST$PREFIX/bin/gta5rp-launcher" <<EOF
#!/bin/sh
exec python3 $PREFIX/share/gta5rp-launcher/gta5rp_launcher.py "\$@"
EOF
chmod 755 "$DEST$PREFIX/bin/gta5rp-launcher"
sed "s|@BIN@|gta5rp-launcher|" "$SRC/data/gta5rp-launcher.desktop" > "$DEST$PREFIX/share/applications/gta5rp-launcher.desktop"
chmod 644 "$DEST$PREFIX/share/applications/gta5rp-launcher.desktop"
