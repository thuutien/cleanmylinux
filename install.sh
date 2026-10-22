#!/bin/sh
# Install (or uninstall with --uninstall) CleanMyLinux system-wide.
# Usage: sudo ./install.sh [--uninstall] [--prefix-root DIR]
set -e

ROOT=""
UNINSTALL=0
while [ $# -gt 0 ]; do
    case "$1" in
        --uninstall) UNINSTALL=1 ;;
        --prefix-root) ROOT="$2"; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
    shift
done

LIB="$ROOT/usr/lib/cleanmylinux"
BIN="$ROOT/usr/bin/cleanmylinux"
DESKTOP="$ROOT/usr/share/applications/cleanmylinux.desktop"
ICON="$ROOT/usr/share/icons/hicolor/scalable/apps/cleanmylinux.svg"
POLICY="$ROOT/usr/share/polkit-1/actions/io.github.thuutien.cleanmylinux.policy"

if [ "$UNINSTALL" = 1 ]; then
    rm -rf "$LIB" "$BIN" "$DESKTOP" "$ICON" "$POLICY"
    echo "CleanMyLinux uninstalled."
    exit 0
fi

if [ -z "$ROOT" ] && [ "$(id -u)" != 0 ]; then
    echo "Please run as root: sudo $0"
    exit 1
fi

SRC="$(cd "$(dirname "$0")" && pwd)"

rm -rf "$LIB/cleanmylinux"
for dir in cleanmylinux cleanmylinux/core cleanmylinux/ui cleanmylinux/ui/pages cleanmylinux/data; do
    install -d "$LIB/$dir"
done
install -m 644 "$SRC"/cleanmylinux/*.py "$LIB/cleanmylinux/"
install -m 644 "$SRC"/cleanmylinux/core/*.py "$LIB/cleanmylinux/core/"
install -m 644 "$SRC"/cleanmylinux/ui/*.py "$SRC/cleanmylinux/ui/style.css" "$LIB/cleanmylinux/ui/"
install -m 644 "$SRC"/cleanmylinux/ui/pages/*.py "$LIB/cleanmylinux/ui/pages/"
install -m 644 "$SRC/cleanmylinux/data/cleanmylinux.svg" "$LIB/cleanmylinux/data/"
# The helper is what pkexec runs; its path must match the polkit policy.
sed '1s|.*|#!/usr/bin/python3|' "$SRC/cleanmylinux/core/helper.py" > "$LIB/cleanmylinux-helper"
chmod 755 "$LIB/cleanmylinux-helper"
install -D -m 755 "$SRC/data/cleanmylinux-launcher" "$BIN"
install -D -m 644 "$SRC/data/cleanmylinux.desktop" "$DESKTOP"
install -D -m 644 "$SRC/cleanmylinux/data/cleanmylinux.svg" "$ICON"
install -D -m 644 "$SRC/data/io.github.thuutien.cleanmylinux.policy" "$POLICY"

if [ -z "$ROOT" ]; then
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
    command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
    echo "CleanMyLinux installed. Launch it from the menu (System Tools > CleanMyLinux) or run: cleanmylinux"
fi
