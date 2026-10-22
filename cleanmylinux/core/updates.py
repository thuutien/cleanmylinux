"""Software updates from APT, Flatpak and Snap."""

import os
import re
import time
from dataclasses import dataclass, field

from . import host, privileged

APT_LISTS = "/var/lib/apt/lists"
APT_LINE = re.compile(r"^(?P<name>[^/\s]+)/\S+\s+(?P<new>\S+)\s+\S+\s+\[upgradable from: (?P<old>[^\]]+)\]")
SECURITY = re.compile(r"-security|security\.", re.I)
SOURCE_INFO = {
    "apt": ("System Packages (APT)", "package-x-generic-symbolic"),
    "flatpak": ("Flatpak Apps & Runtimes", "system-software-install-symbolic"),
    "snap": ("Snap Packages", "package-x-generic-symbolic"),
}


@dataclass
class Update:
    source: str  # apt | flatpak | snap
    id: str
    name: str
    old: str
    new: str
    size: int = 0
    security: bool = False
    installation: str = ""
    selected: bool = True


@dataclass
class UpdateGroup:
    source: str
    name: str
    icon: str
    updates: list = field(default_factory=list)

    @property
    def size(self):
        return sum(u.size for u in self.updates)


_run = host.output


def lists_age():
    """Seconds since the APT package lists were last refreshed (None if unknown)."""
    if host.FLATPAK:
        stamps = _run(["find", APT_LISTS, "-maxdepth", "1", "-type", "f", "-printf", "%T@\\n"]).split()
        newest = max((float(s) for s in stamps), default=None)
    else:
        try:
            newest = max((e.stat().st_mtime for e in os.scandir(APT_LISTS) if e.is_file()), default=None)
        except OSError:
            return None
    return None if newest is None else time.time() - newest


def parse_apt(output):
    updates = []
    for line in output.splitlines():
        m = APT_LINE.match(line.strip())
        if m:
            suite = line.split("/", 1)[1].split()[0]
            updates.append(Update("apt", m["name"], m["name"], m["old"], m["new"],
                                  security=bool(SECURITY.search(suite))))
    return updates


def _apt_sizes(updates):
    if not updates:
        return
    sizes, current = {}, None
    for line in _run(["apt-cache", "show", "--no-all-versions", *[u.id for u in updates]]).splitlines():
        if line.startswith("Package: "):
            current = line.split(": ", 1)[1].strip()
        elif line.startswith("Size: ") and current:
            sizes.setdefault(current, int(line.split(": ", 1)[1]))
    for update in updates:
        update.size = sizes.get(update.id, 0)


def apt_updates():
    if not host.which("apt"):
        return []
    updates = parse_apt(_run(["apt", "list", "--upgradable"]))
    _apt_sizes(updates)
    return updates


def parse_flatpak(output, installation):
    updates = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and "." in parts[0]:
            app_id, name, version = parts[0].strip(), parts[1].strip(), parts[2].strip()
            updates.append(Update("flatpak", app_id, name or app_id, "", version or "latest",
                                  installation=installation))
    return updates


def flatpak_updates():
    if not host.which("flatpak"):
        return []
    updates = []
    for scope in ("system", "user"):
        out = _run(["flatpak", "remote-ls", f"--{scope}", "--updates", "--columns=application,name,version"])
        updates += parse_flatpak(out, scope)
    return updates


def snap_updates():
    if not host.which("snap"):
        return []
    updates = []
    for line in _run(["snap", "refresh", "--list"]).splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            updates.append(Update("snap", parts[0], parts[0], "", parts[1]))
    return updates


def check(refresh=False, progress=None):
    """Return non-empty UpdateGroups. refresh=True runs `apt-get update` as root first."""
    errors = []
    if refresh and host.which("apt-get"):
        if progress:
            progress("Refreshing package lists (administrator password needed)…", 0.1)
        try:
            ok, out = privileged.run_root(["apt-update"])["apt-update"]
            if not ok:
                errors.append(out.splitlines()[-1] if out else "apt-get update failed")
        except (privileged.AuthCancelled, RuntimeError) as exc:
            errors.append(f"Package lists not refreshed: {exc}")
    groups = []
    for index, (source, finder) in enumerate((("apt", apt_updates), ("flatpak", flatpak_updates),
                                              ("snap", snap_updates))):
        if progress:
            progress(f"Checking {SOURCE_INFO[source][0]}…", 0.3 + index * 0.23)
        found = sorted(finder(), key=lambda u: (not u.security, u.name.lower()))
        if found:
            groups.append(UpdateGroup(source, *SOURCE_INFO[source], found))
    return groups, errors


def count_cached():
    """Fast, password-free count of pending updates for the sidebar badge."""
    return len(apt_updates()) + len(flatpak_updates()) + len(snap_updates())


def install(updates, progress=None):
    """Install selected updates. Returns (count_installed, errors)."""
    errors, done = [], 0
    apt = [u for u in updates if u.source == "apt"]
    if apt:
        if progress:
            progress("Installing system updates (administrator password needed)…", 0.2)
        action = "upgrade-packages=" + ",".join(u.id for u in apt)
        try:
            ok, out = privileged.run_root([action])[action]
            if ok:
                done += len(apt)
            else:
                errors.append(out[-600:])
        except (privileged.AuthCancelled, RuntimeError) as exc:
            errors.append(f"System updates skipped: {exc}")
    for scope in ("system", "user"):
        ids = [u.id for u in updates if u.source == "flatpak" and u.installation == scope]
        if ids:
            if progress:
                progress(f"Updating {len(ids)} Flatpak item(s)…", 0.6)
            proc = host.run(["flatpak", "update", "-y", "--noninteractive", f"--{scope}", *ids])
            if proc.returncode == 0:
                done += len(ids)
            else:
                errors.append(proc.stderr.strip()[-600:])
    snaps = [u.id for u in updates if u.source == "snap"]
    if snaps:
        if progress:
            progress("Refreshing snaps…", 0.85)
        proc = host.run(["snap", "refresh", *snaps])
        if proc.returncode == 0:
            done += len(snaps)
        else:
            errors.append(proc.stderr.strip()[-600:])
    return done, errors
