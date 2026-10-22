#!/usr/bin/env python3
"""Privileged helper for CleanMyLinux.

Run through pkexec with a list of whitelisted actions, e.g.
    pkexec python3 helper.py apt-clean journal-vacuum
Each action prints one JSON line: {"action", "ok", "output"}.
"""

import json
import os
import re
import subprocess
import sys

ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "DEBIAN_FRONTEND": "noninteractive"}
ROTATED = re.compile(r"\.(gz|xz|bz2|zst|old)$|\.\d+$")
PKG_NAME = re.compile(r"^[a-z0-9][a-z0-9+.\-]*(:[a-z0-9]+)?$")


def run(cmd):
    proc = subprocess.run(cmd, env=ENV, capture_output=True, text=True)
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out


def remove_files(paths):
    freed, count = 0, 0
    for path in paths:
        try:
            st = os.lstat(path)
            os.unlink(path)
            freed += st.st_size
            count += 1
        except OSError:
            pass
    return True, f"Removed {count} files ({freed} bytes)"


def rotated_logs():
    victims = []
    for root, dirs, files in os.walk("/var/log"):
        if root.startswith("/var/log/journal"):
            dirs[:] = []
            continue
        for name in files:
            path = os.path.join(root, name)
            if ROTATED.search(name) and os.path.isfile(path) and not os.path.islink(path):
                victims.append(path)
    return remove_files(victims)


def crash_reports():
    base = "/var/crash"
    if not os.path.isdir(base):
        return True, "Nothing to remove"
    return remove_files(os.path.join(base, n) for n in os.listdir(base))


def drop_caches():
    os.sync()
    with open("/proc/sys/vm/drop_caches", "w") as fh:
        fh.write("3\n")
    return True, "Page cache, dentries and inodes dropped"


KEEP_CONFIG = ["-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold"]


def packages(args, mode="remove"):
    names = [a for a in args if PKG_NAME.match(a)]
    if not names or len(names) != len(args):
        return False, "Invalid package names"
    if mode == "upgrade":
        return run(["apt-get", "install", "--only-upgrade", "-y", *KEEP_CONFIG, *names])
    return run(["apt-get", mode, "-y", *names])


ACTIONS = {
    "apt-clean": lambda: run(["apt-get", "clean"]),
    "apt-update": lambda: run(["apt-get", "update"]),
    "apt-autoremove": lambda: run(["apt-get", "autoremove", "-y"]),
    "fix-packages": lambda: _chain(["dpkg", "--configure", "-a"], ["apt-get", "-f", "install", "-y"]),
    "journal-vacuum": lambda: _chain(["journalctl", "--rotate"], ["journalctl", "--vacuum-size=64M"]),
    "rotated-logs": rotated_logs,
    "crash-reports": crash_reports,
    "drop-caches": drop_caches,
    "fstrim": lambda: run(["fstrim", "-av"]),
}


PACKAGE_MODES = {"remove-packages": "remove", "purge-packages": "purge", "upgrade-packages": "upgrade"}


def _chain(*cmds):
    outputs = []
    for cmd in cmds:
        ok, out = run(cmd)
        outputs.append(out)
        if not ok:
            return False, "\n".join(outputs)
    return True, "\n".join(outputs)


def main(argv):
    if os.geteuid() != 0:
        print(json.dumps({"action": "*", "ok": False, "output": "Helper must run as root"}))
        return 1
    status = 0
    for action in argv:
        name, _, arg = action.partition("=")
        try:
            if name in PACKAGE_MODES:
                ok, out = packages(arg.split(","), PACKAGE_MODES[name])
            elif name in ACTIONS:
                ok, out = ACTIONS[name]()
            else:
                ok, out = False, "Unknown action"
        except Exception as exc:  # report and keep going with the remaining actions
            ok, out = False, str(exc)
        if not ok:
            status = 1
        print(json.dumps({"action": action, "ok": ok, "output": out[-4000:]}), flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
