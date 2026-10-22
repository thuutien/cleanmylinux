"""Shared filesystem helpers used by every scanner."""

import os
import shutil
import stat
import time
from pathlib import Path

HOME = str(Path.home())
# The host's root filesystem; inside Flatpak "/" is the sandbox.
ROOT_FS = "/run/host/usr" if os.path.exists("/.flatpak-info") else "/"

# Paths we never delete, no matter what a scanner returns.
PROTECTED = {
    "/", HOME, "/home", "/root", "/usr", "/etc", "/var", "/boot", "/bin", "/sbin",
    "/lib", "/lib64", "/opt", "/srv", "/tmp", "/media", "/mnt", "/proc", "/sys", "/dev",
    os.path.join(HOME, ".cache"), os.path.join(HOME, ".config"),
    os.path.join(HOME, ".local"), os.path.join(HOME, ".local/share"),
}


def human_size(num):
    num = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1000 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1000
    return f"{num:.1f} TB"


def human_age(timestamp):
    days = (time.time() - timestamp) / 86400
    if days < 1:
        return "Today"
    if days < 2:
        return "Yesterday"
    if days < 31:
        return f"{int(days)} days ago"
    if days < 365:
        return f"{int(days // 30)} months ago"
    years = days / 365
    return f"{years:.1f} years ago" if years < 10 else f"{int(years)} years ago"


def path_size(path, cancel=None):
    """Apparent size of a file or directory tree, without following symlinks."""
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if not stat.S_ISDIR(st.st_mode):
        return st.st_size
    total = 0
    stack = [path]
    while stack:
        if cancel is not None and cancel.is_set():
            break
        directory = stack.pop()
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def is_protected(path):
    real = os.path.realpath(path) if not os.path.islink(path) else os.path.abspath(path)
    return real.rstrip("/") in PROTECTED or real == "/"


def remove_path(path):
    """Permanently delete a file or directory tree. Returns bytes freed."""
    if not os.path.lexists(path) or is_protected(path):
        return 0
    before = path_size(path)
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        return 0
    after = path_size(path) if os.path.lexists(path) else 0
    return max(before - after, 0)


def clear_contents(path):
    """Delete everything inside a directory but keep the directory itself."""
    freed = 0
    try:
        with os.scandir(path) as it:
            entries = [e.path for e in it]
    except OSError:
        return 0
    for entry in entries:
        freed += remove_path(entry)
    return freed


def move_to_trash(path):
    """Move a path to the desktop Trash through GIO. Raises on failure."""
    from gi.repository import Gio
    Gio.File.new_for_path(path).trash(None)


def walk_files(root, cancel=None, skip_hidden=True, skip_dirs=(), one_fs=True, on_dir=None):
    """Yield (path, stat_result) for every regular file under root."""
    try:
        root_dev = os.lstat(root).st_dev
    except OSError:
        return
    skip = {os.path.abspath(d) for d in skip_dirs}
    stack = [root]
    while stack:
        if cancel is not None and cancel.is_set():
            return
        directory = stack.pop()
        if on_dir:
            on_dir(directory)
        try:
            with os.scandir(directory) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            if skip_hidden and entry.name.startswith("."):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.path in skip:
                        continue
                    if one_fs and entry.stat(follow_symlinks=False).st_dev != root_dev:
                        continue
                    stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    yield entry.path, entry.stat(follow_symlinks=False)
            except OSError:
                pass


class Throttle:
    """Rate-limit progress callbacks coming from worker threads."""

    def __init__(self, callback, interval=0.08):
        self.callback = callback
        self.interval = interval
        self.last = 0.0

    def __call__(self, *args, force=False):
        if self.callback is None:
            return
        now = time.monotonic()
        if force or now - self.last >= self.interval:
            self.last = now
            self.callback(*args)
