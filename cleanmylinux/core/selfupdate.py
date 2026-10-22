"""Check GitHub for new CleanMyLinux releases and install them.

The check and download run as the user; only the final install step of a
.deb or tarball install is run through pkexec. Flatpak installs update the
bundle with `flatpak install --user`, which needs no password. Downloads are
verified against the SHA-256 digest GitHub publishes for each release asset.
"""

import configparser
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from dataclasses import dataclass, field

from .. import __version__
from . import host
from .utils import HOME

REPO = "thuutien/cleanmylinux"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
INSTALL_DIR = "/usr/lib/cleanmylinux"
APP_ID = "io.github.thuutien.CleanMyLinux"
TIMEOUT = 15
SETTINGS = os.path.join(HOME, ".config/cleanmylinux/settings.json")


@dataclass
class Release:
    version: str
    url: str
    notes: str = ""
    # asset name -> (download url, sha256 hex or "")
    assets: dict = field(default_factory=dict)


def version_tuple(v):
    parts = []
    for p in v.lstrip("vV").split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(latest, current=__version__):
    return version_tuple(latest) > version_tuple(current)


def _open(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"cleanmylinux/{__version__}",
        "Accept": "application/vnd.github+json",
    })
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def fetch_latest():
    """Return the latest published release. Raises OSError/ValueError on failure."""
    with _open(API_LATEST) as resp:
        data = json.load(resp)
    tag = data.get("tag_name") or ""
    if not tag:
        raise ValueError("No release found")
    rel = Release(version=tag.lstrip("vV"), url=data.get("html_url") or RELEASES_PAGE,
                  notes=data.get("body") or "")
    for asset in data.get("assets", []):
        digest = asset.get("digest") or ""
        sha = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
        rel.assets[asset["name"]] = (asset["browser_download_url"], sha)
    return rel


def _owned_by(cmd):
    if not shutil.which(cmd[0]):
        return False
    return subprocess.run(cmd, capture_output=True).returncode == 0


def install_method():
    """How this copy of CleanMyLinux was installed.

    "deb"     - Debian package, upgraded with apt
    "tarball" - install.sh into /usr/lib/cleanmylinux, upgraded the same way
    "flatpak" - Flatpak bundle, upgraded with flatpak install
    "package" - owned by another package manager (pacman); the user updates it
    "manual"  - running from source; the user updates it
    """
    if host.FLATPAK:
        return "flatpak"
    package_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if package_root != INSTALL_DIR:
        return "manual"
    if shutil.which("dpkg-query"):
        status = subprocess.run(["dpkg-query", "-W", "-f=${Status}", "cleanmylinux"],
                                capture_output=True, text=True).stdout
        if status.endswith(" installed"):
            return "deb"
    if _owned_by(["pacman", "-Qq", "cleanmylinux"]) or _owned_by(["rpm", "-q", "cleanmylinux"]):
        return "package"
    return "tarball"


def asset_for(rel, method):
    names = {
        "deb": f"cleanmylinux_{rel.version}_all.deb",
        "tarball": f"cleanmylinux-{rel.version}.tar.gz",
        "flatpak": f"cleanmylinux-{rel.version}-x86_64.flatpak",
    }
    name = names.get(method)
    return name if name in rel.assets else None


def download_dir():
    """A fresh folder for downloads. Inside Flatpak it must be visible to the host."""
    base = os.path.join(HOME, ".cache", "cleanmylinux-update") if host.FLATPAK else None
    if base:
        shutil.rmtree(base, ignore_errors=True)
        os.makedirs(base, mode=0o700)
        return base
    import tempfile
    return tempfile.mkdtemp(prefix="cleanmylinux-update-")


def download(rel, name, dest_dir, progress=None):
    """Download a release asset and verify its SHA-256. Returns the file path."""
    url, sha = rel.assets[name]
    if not url.startswith(DOWNLOAD_PREFIX):
        raise ValueError(f"Unexpected download location: {url}")
    if not sha:
        raise ValueError(f"GitHub did not publish a checksum for {name}")
    path = os.path.join(dest_dir, name)
    digest = hashlib.sha256()
    with _open(url) as resp, open(path, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    if digest.hexdigest() != sha.lower():
        os.unlink(path)
        raise ValueError(f"Checksum mismatch for {name}; the download was discarded")
    return path


def _flatpak_scope():
    info = configparser.ConfigParser()
    info.read("/.flatpak-info")
    app_path = info.get("Instance", "app-path", fallback="")
    return "--user" if app_path.startswith(HOME) else "--system"


def install_command(method, path, dest_dir):
    """Prepare the downloaded asset and return the install command."""
    if method == "deb":
        return ["pkexec", "apt-get", "install", "-y", path]
    if method == "tarball":
        with tarfile.open(path) as tar:
            members = tar.getmembers()
            for m in members:
                if m.name.startswith("/") or ".." in m.name.split("/") or \
                        not (m.isfile() or m.isdir()):
                    raise ValueError(f"Unsafe entry in archive: {m.name}")
            tar.extractall(dest_dir, members=members)
        top = os.path.basename(path)[:-len(".tar.gz")]
        script = os.path.join(dest_dir, top, "install.sh")
        if not os.path.isfile(script):
            raise ValueError("install.sh not found in the release archive")
        return ["pkexec", "/bin/sh", script]
    if method == "flatpak":
        return host.command(["flatpak", "install", _flatpak_scope(), "-y", "--noninteractive",
                             "--reinstall", path])
    raise ValueError(f"Cannot install automatically for method '{method}'")


def install(rel, progress=None):
    """Download and install rel. Returns (ok, output)."""
    method = install_method()
    name = asset_for(rel, method)
    if not name:
        raise ValueError("This release has no package for how CleanMyLinux is installed here")
    dest = download_dir()
    try:
        path = download(rel, name, dest, progress)
        proc = subprocess.run(install_command(method, path, dest), capture_output=True, text=True)
    finally:
        shutil.rmtree(dest, ignore_errors=True)
    if proc.returncode in (126, 127) and method != "flatpak":
        return False, "Authentication was cancelled"
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def restart_command():
    """Command that starts a fresh copy of the app after an update."""
    if host.FLATPAK:
        return host.command(["flatpak", "run", APP_ID])
    if os.path.basename(sys.argv[0]) == "__main__.py":  # started with python3 -m cleanmylinux
        return [sys.executable, "-m", "cleanmylinux"]
    return [sys.executable, *sys.argv]


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
