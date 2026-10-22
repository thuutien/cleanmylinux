#!/bin/sh
# Build a .deb package for Linux Mint / Ubuntu / Debian.
# Usage: ./packaging/build-deb.sh   ->   dist/cleanmylinux_<version>_all.deb
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/cleanmylinux/__init__.py")
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

chmod 755 "$STAGE"
sh "$SRC/install.sh" --prefix-root "$STAGE"
install -d "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/control" <<CTRL
Package: cleanmylinux
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.8), python3-gi, gir1.2-gtk-3.0, python3-psutil, pkexec | policykit-1
Recommends: flatpak
Maintainer: CleanMyLinux <cleanmylinux@localhost>
Homepage: https://github.com/thuutien/cleanmylinux
Description: Clean junk, uninstall apps and keep Linux fast
 A CleanMyMac-style GTK utility for Linux. Removes caches, logs, package
 leftovers and Trash, finds large, old and duplicate files, maps disk usage,
 manages login items, uninstalls and updates APT, Flatpak and Snap apps, and
 runs maintenance tasks.
CTRL
cat > "$STAGE/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
POST
chmod 755 "$STAGE/DEBIAN/postinst"
mkdir -p "$SRC/dist"
dpkg-deb --root-owner-group --build "$STAGE" "$SRC/dist/cleanmylinux_${VERSION}_all.deb"
