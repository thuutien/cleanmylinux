#!/usr/bin/env bash
# Install CleanMyLinux for the current user (no root needed).
#   ./install.sh            install to ~/.local
#   ./install.sh --uninstall
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/cleanmylinux"

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -rf "$APP_DIR" "$PREFIX/bin/cleanmylinux" \
    "$PREFIX/share/applications/cleanmylinux.desktop" \
    "$PREFIX/share/icons/hicolor/scalable/apps/cleanmylinux.svg"
  echo "CleanMyLinux removed."
  exit 0
fi

missing=()
python3 -c 'import gi; gi.require_version("Gtk", "3.0")' 2>/dev/null || missing+=(python3-gi gir1.2-gtk-3.0)
python3 -c 'import psutil' 2>/dev/null || missing+=(python3-psutil)
if (( ${#missing[@]} )); then
  echo "Missing dependencies. Install them with:"
  echo "  sudo apt install ${missing[*]}"
  exit 1
fi

mkdir -p "$APP_DIR" "$PREFIX/bin" "$PREFIX/share/applications" "$PREFIX/share/icons/hicolor/scalable/apps"
rm -rf "$APP_DIR/cleanmylinux"
cp -r "$SRC/cleanmylinux" "$APP_DIR/"
find "$APP_DIR" -name __pycache__ -prune -exec rm -rf {} +
install -m 755 "$SRC/bin/cleanmylinux" "$APP_DIR/cleanmylinux-launcher"
mkdir -p "$APP_DIR/bin" && mv "$APP_DIR/cleanmylinux-launcher" "$APP_DIR/bin/cleanmylinux"
ln -sf "$APP_DIR/bin/cleanmylinux" "$PREFIX/bin/cleanmylinux"
install -m 644 "$SRC/cleanmylinux/data/cleanmylinux.svg" "$PREFIX/share/icons/hicolor/scalable/apps/cleanmylinux.svg"
sed "s|^Exec=.*|Exec=$PREFIX/bin/cleanmylinux|" "$SRC/cleanmylinux.desktop" > "$PREFIX/share/applications/cleanmylinux.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$PREFIX/share/applications" || true
gtk-update-icon-cache -q "$PREFIX/share/icons/hicolor" 2>/dev/null || true
echo "CleanMyLinux installed. Launch it from your app menu or run: cleanmylinux"
