#!/bin/sh
# Build a single-file Flatpak bundle.
# Usage: ./packaging/build-flatpak.sh   ->   dist/cleanmylinux-<version>-x86_64.flatpak
# Needs flatpak-builder and the GNOME runtime/SDK from Flathub:
#   flatpak install --user flathub org.gnome.Platform//50 org.gnome.Sdk//50
set -e
command -v flatpak-builder >/dev/null || {
    echo "flatpak-builder not found. Install it with your package manager" >&2
    echo "(e.g. sudo apt install flatpak-builder) or: flatpak install flathub org.flatpak.Builder" >&2
    exit 1
}
SRC="$(cd "$(dirname "$0")/.." && pwd)"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/cleanmylinux/__init__.py")
ARCH="${ARCH:-x86_64}"
BUILD="$SRC/dist/flatpak-build"
REPO="$SRC/dist/flatpak-repo"
mkdir -p "$SRC/dist"
flatpak-builder --user --install-deps-from=flathub --force-clean --arch="$ARCH" \
    --state-dir="$SRC/dist/.flatpak-builder" --repo="$REPO" \
    "$BUILD" "$SRC/packaging/flatpak/io.github.thuutien.CleanMyLinux.yml"
flatpak build-bundle --arch="$ARCH" "$REPO" "$SRC/dist/cleanmylinux-$VERSION-$ARCH.flatpak" \
    io.github.thuutien.CleanMyLinux
ls "$SRC/dist"/*.flatpak
