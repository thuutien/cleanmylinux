#!/bin/sh
# CleanMyLinux one-liner installer.
#
#   curl -fsSL https://raw.githubusercontent.com/thuutien/cleanmylinux/master/packaging/quick-install.sh | sudo bash
#
# Pick a version, skip dependency installation, or uninstall:
#
#   curl -fsSL .../quick-install.sh | sudo bash -s -- 1.0.0
#   curl -fsSL .../quick-install.sh | sudo bash -s -- --no-deps
#   curl -fsSL .../quick-install.sh | sudo bash -s -- --uninstall
#
# Environment overrides: CLEANMYLINUX_REPO (default thuutien/cleanmylinux),
# CLEANMYLINUX_VERSION (default latest).
set -eu

REPO="${CLEANMYLINUX_REPO:-thuutien/cleanmylinux}"
VERSION="${CLEANMYLINUX_VERSION:-latest}"
INSTALL_DEPS=1
UNINSTALL=0

for arg in "$@"; do
    case "$arg" in
        --no-deps) INSTALL_DEPS=0 ;;
        --deps) INSTALL_DEPS=1 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help)
            echo "Usage: quick-install.sh [version] [--no-deps] [--uninstall]"
            exit 0 ;;
        *) VERSION="$arg" ;;
    esac
done

if [ "$(id -u)" != 0 ]; then
    echo "Please run as root (pipe into 'sudo bash')." >&2
    exit 1
fi
command -v curl >/dev/null || { echo "curl is required." >&2; exit 1; }

if [ "$VERSION" = "latest" ]; then
    TAG=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
        | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)
    VERSION="${TAG#v}"
    [ -n "$VERSION" ] || { echo "Could not determine the latest release." >&2; exit 1; }
fi

install_deps() {
    if command -v apt-get >/dev/null; then
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-gi gir1.2-gtk-3.0 python3-psutil
        # Newer releases split pkexec out of policykit-1.
        DEBIAN_FRONTEND=noninteractive apt-get install -y pkexec || \
            DEBIAN_FRONTEND=noninteractive apt-get install -y policykit-1
    elif command -v dnf >/dev/null; then
        dnf install -y python3 python3-gobject gtk3 python3-psutil polkit
    elif command -v pacman >/dev/null; then
        pacman -Sy --needed --noconfirm python python-gobject gtk3 python-psutil polkit
    elif command -v zypper >/dev/null; then
        zypper install -y python3 python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-3_0 python3-psutil polkit
    else
        echo "No supported package manager found; install dependencies manually" >&2
        echo "(Python 3 GObject bindings, GTK 3, psutil and polkit)." >&2
    fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM
cd "$TMP"
echo "Downloading CleanMyLinux $VERSION..."
curl -fsSL -o cleanmylinux.tar.gz \
    "https://github.com/$REPO/releases/download/v$VERSION/cleanmylinux-$VERSION.tar.gz"
tar xzf cleanmylinux.tar.gz
cd "cleanmylinux-$VERSION"

if [ "$UNINSTALL" = 1 ]; then
    sh install.sh --uninstall
    exit 0
fi
[ "$INSTALL_DEPS" = 1 ] && install_deps
sh install.sh
echo "CleanMyLinux $VERSION installed. Run it with: cleanmylinux"
