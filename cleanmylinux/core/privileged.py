"""Run root-only actions through pkexec and the bundled helper."""

import json
import os
import shutil
import subprocess
import sys

HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "helper.py")


class AuthCancelled(Exception):
    pass


def available():
    return shutil.which("pkexec") is not None


def run_root(actions):
    """Run helper actions as root. Returns {action: (ok, output)}.

    Raises AuthCancelled when the password prompt is dismissed.
    """
    if not actions:
        return {}
    if not available():
        raise RuntimeError("pkexec is not installed; cannot run administrator tasks")
    proc = subprocess.run(
        ["pkexec", sys.executable, HELPER, *actions], capture_output=True, text=True
    )
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
