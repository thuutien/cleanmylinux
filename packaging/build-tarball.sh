#!/bin/sh
# Build a distro-independent install archive: dist/cleanmylinux-<version>.tar.gz
# Users extract it and run: sudo ./install.sh
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/cleanmylinux/__init__.py")
mkdir -p "$SRC/dist"
git -C "$SRC" archive --format=tar.gz --prefix="cleanmylinux-$VERSION/" \
    -o "$SRC/dist/cleanmylinux-$VERSION.tar.gz" HEAD
