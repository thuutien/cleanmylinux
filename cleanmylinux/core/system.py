"""Login items, running processes and maintenance tasks."""

import configparser
import glob
import os
import shutil
import signal
import subprocess
from dataclasses import dataclass

import psutil

from . import privileged
from .utils import HOME, clear_contents

USER_AUTOSTART = os.path.join(HOME, ".config/autostart")
SYSTEM_AUTOSTART = "/etc/xdg/autostart"
DESKTOP = os.environ.get("XDG_CURRENT_DESKTOP", "").replace("X-", "").split(":")


# ---------------------------------------------------------------- login items

@dataclass
class LoginItem:
    file_name: str
    name: str
    comment: str
    icon: str
    command: str
    enabled: bool
    user_only: bool  # exists only in ~/.config/autostart (can be deleted)

    @property
    def user_path(self):
        return os.path.join(USER_AUTOSTART, self.file_name)


def _read_desktop(path):
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
        return dict(parser["Desktop Entry"])
    except (configparser.Error, KeyError, UnicodeDecodeError):
        return None


def _shown_here(entry):
    only = [d for d in entry.get("OnlyShowIn", "").split(";") if d]
    hide = [d for d in entry.get("NotShowIn", "").split(";") if d]
    if only and not any(d in only for d in DESKTOP):
        return False
    return not any(d in hide for d in DESKTOP)


def login_items():
    files = {}
    for directory in (SYSTEM_AUTOSTART, USER_AUTOSTART):  # user overrides system
        for path in glob.glob(os.path.join(directory, "*.desktop")):
            files.setdefault(os.path.basename(path), []).append(path)
    items = []
    for name, paths in files.items():
        entry = _read_desktop(paths[-1])
        if entry is None:
            continue
        system_entry = _read_desktop(os.path.join(SYSTEM_AUTOSTART, name)) if len(paths) > 1 else entry
        if not _shown_here(system_entry or entry):
            continue
        enabled = (entry.get("Hidden", "false").lower() != "true"
                   and entry.get("X-GNOME-Autostart-enabled", "true").lower() != "false")
        items.append(LoginItem(name, entry.get("Name", name), entry.get("Comment", ""),
                               entry.get("Icon", ""), entry.get("Exec", ""), enabled,
                               not paths[0].startswith(SYSTEM_AUTOSTART)))
    return sorted(items, key=lambda i: i.name.lower())


def set_login_item(item, enabled):
    """Enable/disable via a user override so system files are never edited."""
    os.makedirs(USER_AUTOSTART, exist_ok=True)
    source = item.user_path if os.path.exists(item.user_path) else os.path.join(SYSTEM_AUTOSTART, item.file_name)
    with open(source, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    out, in_entry, done = [], False, set()
    keys = {"Hidden": "false" if enabled else "true",
            "X-GNOME-Autostart-enabled": "true" if enabled else "false"}
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            if in_entry:
                out += [f"{k}={v}" for k, v in keys.items() if k not in done]
                done.update(keys)
            in_entry = stripped == "[Desktop Entry]"
        elif in_entry and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in keys:
                out.append(f"{key}={keys[key]}")
                done.add(key)
                continue
        out.append(line)
    if in_entry:
        out += [f"{k}={v}" for k, v in keys.items() if k not in done]
    with open(item.user_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    item.enabled = enabled


def remove_login_item(item):
    if item.user_only and os.path.exists(item.user_path):
        os.unlink(item.user_path)


# ------------------------------------------------------------------ processes

_proc_cache = {}


def heavy_processes(limit=40):
    """Processes sorted by CPU then memory. First call primes CPU counters."""
    rows = []
    alive = set()
    me = os.getuid()
    for proc in psutil.process_iter(["pid", "name", "username", "memory_info", "uids", "cmdline"]):
        pid = proc.info["pid"]
        alive.add(pid)
        cached = _proc_cache.setdefault(pid, proc)
        try:
            cpu = cached.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        mem = proc.info["memory_info"].rss if proc.info["memory_info"] else 0
        cmd = proc.info["cmdline"] or []
        name = proc.info["name"] or "?"
        if cmd and os.path.basename(cmd[0]) not in (name, "python3", "python", "sh", "bash"):
            name = os.path.basename(cmd[0]) or name
        owned = bool(proc.info["uids"]) and proc.info["uids"].real == me
        rows.append((pid, name, proc.info["username"] or "", cpu, mem, owned))
    for pid in list(_proc_cache):
        if pid not in alive:
            del _proc_cache[pid]
    rows.sort(key=lambda r: (-r[3], -r[4]))
    return rows[:limit]


def stop_process(pid, force=False):
    os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)


# --------------------------------------------------------------- maintenance

@dataclass
class Task:
    id: str
    name: str
    description: str
    root_action: str = ""
    command: tuple = ()
    func: object = None
    recommended: bool = False

    @property
    def needs_root(self):
        return bool(self.root_action)

    @property
    def available(self):
        if self.command:
            return shutil.which(self.command[0]) is not None
        return True


def _rebuild_thumbnails():
    clear_contents(os.path.join(HOME, ".cache/thumbnails"))
    return "Thumbnail cache cleared; previews will be regenerated on demand"


def _desktop_db():
    out = []
    apps = os.path.join(HOME, ".local/share/applications")
    mime = os.path.join(HOME, ".local/share/mime")
    if shutil.which("update-desktop-database") and os.path.isdir(apps):
        out.append(subprocess.run(["update-desktop-database", apps], capture_output=True, text=True).stderr)
    if shutil.which("update-mime-database") and os.path.isdir(mime):
        out.append(subprocess.run(["update-mime-database", mime], capture_output=True, text=True).stderr)
    return "\n".join(o for o in out if o) or "Application and file-type databases refreshed"


TASKS = [
    Task("ram", "Free Up RAM", "Flush filesystem buffers and drop reclaimable page cache.",
         root_action="drop-caches", recommended=True),
    Task("autoremove", "Remove Unused Packages",
         "Uninstall dependencies that are no longer needed by any app (apt autoremove).",
         root_action="apt-autoremove", recommended=True),
    Task("flatpak", "Remove Unused Flatpak Runtimes",
         "Delete Flatpak runtimes and extensions no app depends on.",
         command=("flatpak", "uninstall", "--unused", "-y", "--noninteractive"), recommended=True),
    Task("journal", "Shrink System Logs", "Rotate and vacuum the systemd journal down to 64 MB.",
         root_action="journal-vacuum"),
    Task("fonts", "Rebuild Font Cache", "Fixes missing or garbled fonts in applications.",
         command=("fc-cache", "-f")),
    Task("desktopdb", "Refresh App Database",
         "Rebuild the menu and file-association databases for your account.", func=_desktop_db),
    Task("thumbs", "Reset Thumbnails", "Clear thumbnail previews so broken ones are regenerated.",
         func=_rebuild_thumbnails),
    Task("fix", "Repair Broken Packages",
         "Finish interrupted installs and fix broken dependencies (dpkg --configure -a).",
         root_action="fix-packages"),
    Task("trim", "Run TRIM on SSDs", "Tell your SSDs which blocks are free to keep them fast.",
         root_action="fstrim"),
]


def run_tasks(tasks, on_status):
    """Run tasks; on_status(task, state, output) with state running|ok|error."""
    root_tasks = [t for t in tasks if t.needs_root]
    for task in tasks:
        if task.needs_root:
            continue
        on_status(task, "running", "")
        try:
            if task.func:
                ok, out = True, task.func()
            else:
                proc = subprocess.run(task.command, capture_output=True, text=True)
                ok, out = proc.returncode == 0, (proc.stdout + proc.stderr).strip() or "Done"
        except Exception as exc:
            ok, out = False, str(exc)
        on_status(task, "ok" if ok else "error", out)
    if not root_tasks:
        return
    for task in root_tasks:
        on_status(task, "running", "Waiting for administrator authorization…")
    try:
        results = privileged.run_root([t.root_action for t in root_tasks])
    except (privileged.AuthCancelled, RuntimeError) as exc:
        for task in root_tasks:
            on_status(task, "error", str(exc))
        return
    for task in root_tasks:
        ok, out = results[task.root_action]
        on_status(task, "ok" if ok else "error", out or "Done")
