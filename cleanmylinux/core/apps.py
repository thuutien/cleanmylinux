"""Installed application discovery and removal (APT, Flatpak, Snap)."""

import glob
import os
import re
from dataclasses import dataclass

from . import host, privileged
from .utils import HOME, path_size, remove_path

APP_DIRS = [host.system_path(d) for d in ("/usr/share/applications", "/usr/local/share/applications")]
UNITS = {"B": 1, "kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}


@dataclass
class App:
    source: str  # apt | flatpak | snap | leftover
    id: str
    name: str
    summary: str
    version: str
    size: int
    icon: str = ""
    desktop_file: str = ""
    installation: str = ""
    protected: bool = False
    selected: bool = False


_run = host.output


def _parse_size(text):
    m = re.match(r"([\d.,]+)\s*([kKMGT]?B)", text.strip().replace("\xa0", " "))
    if not m:
        return 0
    return int(float(m.group(1).replace(",", ".")) * UNITS.get(m.group(2), 1))


def _desktop_info(path):
    """Read Name, Comment, Icon and NoDisplay from a .desktop file."""
    info = {}
    in_entry = False
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("["):
                    in_entry = line == "[Desktop Entry]"
                    continue
                if in_entry and "=" in line:
                    key, _, value = line.partition("=")
                    info.setdefault(key.strip(), value.strip())
    except OSError:
        pass
    return info


def apt_apps():
    if not host.which("dpkg-query"):
        return []
    desktops = [p for d in APP_DIRS for p in glob.glob(os.path.join(d, "*.desktop"))]
    if not desktops:
        return []
    owners = {}
    for line in _run(["dpkg", "-S", *map(host.real_path, desktops)]).splitlines():
        pkgs, _, path = line.partition(": ")
        if path:
            owners[host.system_path(path.strip())] = pkgs.split(",")[0].strip().split(":")[0]
    meta = {}
    fmt = "${Package}\t${Installed-Size}\t${Version}\t${Priority}\t${Essential}\t${binary:Summary}\n"
    for line in _run(["dpkg-query", "-W", "-f", fmt]).splitlines():
        parts = line.split("\t")
        if len(parts) == 6:
            meta[parts[0]] = parts
    apps = {}
    for path in sorted(desktops):
        pkg = owners.get(path)
        if not pkg or pkg in apps or pkg not in meta:
            continue
        info = _desktop_info(path)
        if info.get("NoDisplay", "").lower() == "true" or info.get("Type", "Application") != "Application":
            continue
        _, size, version, priority, essential, summary = meta[pkg]
        apps[pkg] = App(
            "apt", pkg, info.get("Name", pkg), info.get("Comment") or summary, version,
            int(size or 0) * 1024, info.get("Icon", ""), path,
            protected=essential == "yes" or priority in ("required", "important"),
        )
    return list(apps.values())


def flatpak_apps():
    if not host.which("flatpak"):
        return []
    out = _run(["flatpak", "list", "--app", "--columns=application,name,version,size,installation"])
    apps = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        app_id, name, version, size, installation = parts[:5]
        apps.append(App("flatpak", app_id, name or app_id, app_id, version, _parse_size(size),
                        app_id, f"{app_id}.desktop", installation.strip()))
    return apps


def snap_apps():
    if not host.which("snap"):
        return []
    apps = []
    rows = []
    for line in _run(["snap", "list"]).splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        name, version = parts[0], parts[1]
        notes = parts[-1]
        if name in ("snapd", "core") or "base" in notes or "core" in notes or name.startswith(("core", "gnome-", "gtk-common")):
            continue
        rows.append((name, version, f"/var/lib/snapd/snaps/{name}_{parts[2]}.snap"))
    sizes = host.sizes([path for *_, path in rows])
    for name, version, path in rows:
        apps.append(App("snap", name, name, "Snap package", version, sizes.get(path, 0), f"snap.{name}"))
    return apps


def flatpak_leftovers(installed_ids):
    """Data in ~/.var/app for Flatpak apps that are no longer installed."""
    apps = []
    for path in sorted(glob.glob(os.path.join(HOME, ".var/app/*"))):
        app_id = os.path.basename(path)
        if app_id in installed_ids:
            continue
        size = path_size(path)
        apps.append(App("leftover", path, app_id, "Data left behind by a removed Flatpak app",
                        "", size, "user-trash-symbolic"))
    return apps


def list_apps():
    apps = apt_apps()
    flatpaks = flatpak_apps()
    apps += flatpaks + snap_apps()
    apps += flatpak_leftovers({a.id for a in flatpaks})
    return sorted(apps, key=lambda a: a.name.lower())


def simulate_apt_removal(packages):
    """Return the full list of packages apt would remove alongside `packages`."""
    out = _run(["apt-get", "-s", "remove", *packages])
    return [line.split()[1] for line in out.splitlines() if line.startswith("Remv ")]


def uninstall(apps, delete_data=False):
    """Remove apps. Returns list of error strings."""
    errors = []
    apt = [a.id for a in apps if a.source == "apt" and not a.protected]
    if apt:
        action = ("purge-packages=" if delete_data else "remove-packages=") + ",".join(apt)
        try:
            ok, out = privileged.run_root([action])[action]
            if not ok:
                errors.append(out)
        except privileged.AuthCancelled:
            errors.append("APT removal skipped: authorization cancelled")
        except RuntimeError as exc:
            errors.append(str(exc))
    for app in apps:
        if app.source == "flatpak":
            scope = "--system" if app.installation == "system" else "--user"
            cmd = ["flatpak", "uninstall", "-y", "--noninteractive", scope, app.id]
            if delete_data:
                cmd.insert(2, "--delete-data")
            proc = host.run(cmd)
            if proc.returncode != 0:
                errors.append(f"{app.name}: {proc.stderr.strip()}")
        elif app.source == "snap":
            cmd = ["snap", "remove", app.id] + (["--purge"] if delete_data else [])
            proc = host.run(cmd)
            if proc.returncode != 0:
                errors.append(f"{app.name}: {proc.stderr.strip()}")
        elif app.source == "leftover":
            remove_path(app.id)
    return errors
