"""Run root-only actions through pkexec and the bundled helper."""

import json
import os
import subprocess
import sys

from . import host

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE_HELPER = os.path.join(HERE, "helper.py")
# Installed packages ship the helper where the polkit policy expects it.
INSTALLED_HELPER = "/usr/lib/cleanmylinux/cleanmylinux-helper"


class AuthCancelled(Exception):
    pass


def available():
    return host.which("pkexec") is not None


def helper_command():
    if host.FLATPAK:
        # The host's own Python runs the helper straight out of the Flatpak install.
        return host.command(["pkexec", "/usr/bin/python3", host.app_path(SOURCE_HELPER)])
    # Only the installed copy uses the installed helper, so a source checkout
    # always runs its own helper even when a package is installed too.
    if HERE == os.path.join(os.path.dirname(INSTALLED_HELPER), "cleanmylinux", "core") and \
            os.path.exists(INSTALLED_HELPER):
        return ["pkexec", INSTALLED_HELPER]
    return ["pkexec", sys.executable, SOURCE_HELPER]


def run_root(actions):
    """Run helper actions as root. Returns {action: (ok, output)}.

    Raises AuthCancelled when the password prompt is dismissed.
    """
    if not actions:
        return {}
    if not available():
        raise RuntimeError("pkexec is not installed; cannot run administrator tasks")
    proc = subprocess.run(helper_command() + list(actions), capture_output=True, text=True)
    if proc.returncode in (126, 127) and not proc.stdout.strip():
        raise AuthCancelled("Authentication was cancelled")
    results = {}
    for line in proc.stdout.splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        results[data["action"]] = (data["ok"], data["output"])
    for action in actions:
        results.setdefault(action, (False, proc.stderr.strip() or "No result"))
    return results
