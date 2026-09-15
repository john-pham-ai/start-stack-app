"""Fetch the latest run_id from the test truck over SSH.

The truck this laptop is cabled to exposes its run logs as:

    $TRUCK_LOG_ROOT/truck-805/2026/09/15/2026-09-15_14-48-57_truck-805
                          | year/month/day | |---------- run_id ----------|

This module runs a fixed, server-built script over the system ``ssh``
(``BatchMode=yes`` so it never prompts), so the developer's own ``~/.ssh``
keys, agent and config do the authenticating. The vehicle number is derived
from the truck's own hostname — the only thing a caller may pass is an
optional vehicle number used purely as a cross-check (a mismatch is a
warning, not an error). Nothing from a caller ever reaches a shell.

Three interfaces share this module:

- ``truck.sh`` / ``python3 truck.py`` — standalone CLI,
- the TUI wizard ("Fetch the latest Run ID from the truck" on the start menu),
- the web UI (the "Fetch Run ID from truck" button).

Environment overrides (same names and defaults as the Master Checklist app):

- ``TRUCK_SSH_TARGET``   (default ``applied@192.168.1.11``)
- ``TRUCK_LOG_ROOT``    (default ``/media/hotswap1/frontier``)
- ``TRUCK_SSH_BIN``     (default ``ssh``; test hook for a fake ssh)
"""

import json
import os
import re
import subprocess
import sys

SSH_TIMEOUT = 10  # whole round trip, so a hung connection can't pin the CLI


class TruckError(Exception):
    """A readable failure: unreachable host, rejected key, no runs found."""


def _env_or(key, default):
    return os.environ.get(key) or default


HOST_RE = re.compile(r"^truck-([0-9]+)-")
DATE_RE = re.compile(r"(\d{4})/(\d{2})/(\d{2})/")


def remote_script(log_root):
    """The fixed script executed on the truck, with {ROOT} filled in.

    The vehicle number comes from the truck's own hostname (one truck per
    cable); if the hostname doesn't match, NOVEHICLE is printed and nothing
    else runs. `ls | sort | tail -1` is chronological because the zero-padded
    run names sort lexically; stderr is silenced so a missing today directory
    is just an empty result, not a failure.
    """
    return (
        "set -u\n"
        "host=$(hostname)\n"
        "printf 'HOSTNAME\\t%s\\n' \"$host\"\n"
        "n=''\n"
        'case "$host" in\n'
        "  truck-[0-9]*-*) n=${host#truck-}; n=${n%%-*} ;;\n"
        "  *) printf 'NOVEHICLE\\n'; exit 0 ;;\n"
        "esac\n"
        "root='{ROOT}/truck-'\"$n\"\n"
        "today=$(date +%Y/%m/%d)\n"
        'latest_today=$(ls -1d "$root/$today"/*_truck-"$n" 2>/dev/null | sort | tail -1)\n'
        'latest=$(ls -1d "$root"/*/*/*/*_truck-"$n" 2>/dev/null | sort | tail -1)\n'
        "printf 'TODAY\\t%s\\nLATEST\\t%s\\n' \"$latest_today\" \"$latest\"\n"
    ).replace("{ROOT}", log_root)


def _last_path_segment(path):
    path = path.rstrip("/")
    return path.rsplit("/", 1)[-1] if "/" in path else path


def parse_output(out, requested=""):
    """Interpret the script's tab-separated lines and pick the run to report.

    The newest run of the truck's own *today* is preferred; without one the
    newest overall is used, with a warning. Returns a dict with vehicle,
    run_id, path, date, hostname and (maybe) warning.
    """
    host = today = latest = ""
    for line in out.splitlines():
        key, sep, value = line.partition("\t")
        if not sep:
            continue
        if key == "HOSTNAME":
            host = value
        elif key == "TODAY":
            today = value
        elif key == "LATEST":
            latest = value

    if "NOVEHICLE" in out or not host or not HOST_RE.match(host):
        raise TruckError(
            f"the connected host {host or '(none)'!r} doesn't look like a truck "
            "(expected truck-<number>-…); check TRUCK_SSH_TARGET"
        )

    match = HOST_RE.match(host)
    info = {"vehicle": match.group(1), "hostname": host, "warning": ""}

    if today:
        info["path"] = today
    elif latest:
        info["path"] = latest
        info["warning"] = (
            "No runs found for today on the truck's clock — "
            "this is the latest run from an earlier day."
        )
    else:
        raise TruckError(
            "no run log directories found on the truck under TRUCK_LOG_ROOT"
        )

    info["run_id"] = _last_path_segment(info["path"])
    date_match = DATE_RE.search(info["path"])
    if date_match:
        info["date"] = "/".join(date_match.groups())

    requested = (requested or "").strip()
    if requested and requested != info["vehicle"]:
        info["warning"] += (
            f" The connected truck is {info['vehicle']}, not {requested}."
        ).strip()
    return info


def fetch_run_id(vehicle="", *, ssh_bin=None, target=None, log_root=None, timeout=SSH_TIMEOUT):
    """SSH to the truck, run the fixed script, return the parsed info dict.

    ``vehicle`` is optional and digits-only (a cross-check, never executed).
    Raises TruckError with a message the user can act on.
    """
    vehicle = (vehicle or "").strip()
    if vehicle and not vehicle.isdigit():
        raise TruckError(f"invalid vehicle number {vehicle!r} (digits only)")

    ssh = ssh_bin or _env_or("TRUCK_SSH_BIN", "ssh")
    dest = target or _env_or("TRUCK_SSH_TARGET", "applied@192.168.1.11")
    script = remote_script(log_root or _env_or("TRUCK_LOG_ROOT", "/media/hotswap1/frontier"))
    command = [
        ssh,
        "-o", "BatchMode=yes",  # never prompt for a password — fail fast instead
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=accept-new",  # first cable-up shouldn't hang on a prompt
        dest,
        "bash -s",
    ]
    try:
        proc = subprocess.run(
            command, input=script, capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError:
        raise TruckError(f"no {ssh!r} binary found — is SSH installed?") from None
    except subprocess.TimeoutExpired:
        raise TruckError(f"SSH to {dest} timed out after {timeout}s") from None

    if proc.returncode != 0:
        detail = proc.stderr.strip()
        detail = detail if len(detail) <= 200 else detail[:200] + "…"
        if proc.returncode == 255:  # ssh's own failures: unreachable, key rejected
            raise TruckError(
                f"could not SSH to {dest} — host unreachable or the key was rejected. "
                f"Test it yourself with `ssh {dest}` ({detail})"
            )
        raise TruckError(f"ssh failed with exit code {proc.returncode} ({detail})")
    return parse_output(proc.stdout, vehicle)


def main(argv):
    """CLI: truck.py [vehicle] [--json]. Exit 0 on success, 1 on failure."""
    args = [a for a in argv if a != "--json"]
    as_json = "--json" in argv
    if len(args) > 1:
        print(f"usage: {os.path.basename(sys.argv[0])} [vehicle] [--json]", file=sys.stderr)
        return 1

    try:
        info = fetch_run_id(args[0] if args else "")
    except TruckError as err:
        if as_json:
            print(json.dumps({"error": str(err)}))
        else:
            print(f"error: {err}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(info))
        return 0

    date = info.get("date", "")
    header = " · ".join(part for part in (info["vehicle"], info["hostname"], date) if part)
    print(header)
    print(f"run_id: {info['run_id']}")
    print(f"path:   {info['path']}")
    if info.get("warning"):
        print(f"⚠️  {info['warning']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
