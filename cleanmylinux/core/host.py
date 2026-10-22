"""Reach the real system when running inside the Flatpak sandbox.

Outside Flatpak every helper here is a no-op wrapper. Inside it, commands run
on the host through flatpak-spawn and host system files are read from
/run/host (the sandbox's own /usr and /etc belong to the runtime).
"""

import configparser
import functools
import os
import shutil
import subprocess

FLATPAK = os.path.exists("/.flatpak-info")
HOST_ROOT = "/run/host"


def command(cmd):
    """Run cmd on the host when inside the Flatpak sandbox (apt, flatpak, pkexec...)."""
    return ["flatpak-spawn", "--host", *cmd] if FLATPAK else list(cmd)


def run(cmd, **kwargs):
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    return subprocess.run(command(cmd), **kwargs)


def output(cmd):
    """stdout of a host command, or "" if it cannot run."""
    try:
        return run(cmd, env={**os.environ, "LANG": "C"}).stdout
    except OSError:
        return ""


@functools.lru_cache(maxsize=None)
def which(name):
    if not FLATPAK:
        return shutil.which(name)
    try:
        proc = run(["sh", "-c", f'command -v "{name}"'])
    except OSError:
        return None
    return proc.stdout.strip() or None


def system_path(path):
    """Where a host system file (/usr/..., /etc/...) can be read from here."""
    if FLATPAK and path.startswith(("/usr/", "/etc/")):
        return HOST_ROOT + path
    return path


def real_path(path):
    """Inverse of system_path: the host's own name for a path we read."""
    if FLATPAK and path.startswith(HOST_ROOT + "/"):
        return path[len(HOST_ROOT):]
    return path


def app_path(path):
    """Host-visible path of a file shipped inside the Flatpak (/app/...)."""
    if not FLATPAK or not path.startswith("/app/"):
        return path
    info = configparser.ConfigParser()
    info.read("/.flatpak-info")
    return os.path.join(info.get("Instance", "app-path", fallback="/app"), path[len("/app/"):])


def sizes(paths):
    """{path: bytes} for host paths the sandbox cannot see (e.g. under /var)."""
    if not paths:
        return {}
    if not FLATPAK:
        from .utils import path_size
        return {p: path_size(p) for p in paths}
    result = {p: 0 for p in paths}
    for line in output(["du", "-sb", "--", *paths]).splitlines():
        size, _, path = line.partition("\t")
        if path in result and size.isdigit():
            result[path] = int(size)
    return result
