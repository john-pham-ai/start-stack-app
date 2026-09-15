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
- ``TRUCK_KEYGEN_BIN``  (default ``ssh-keygen``; test hook)
- ``TRUCK_SSH_DIR``     (default ``~/.ssh``; test hook)

``truck.py setup <vehicle>`` does the one-time per-truck SSH setup: since
every truck answers on the same address, each gets its own identity and
``Host truck-<N>`` alias — the name is forced to the truck number — with a
separate known-hosts file so a second truck's host key can't collide with
the first's. The public key is then installed on the truck (existing
key/agent first, then an optional password via SSH_ASKPASS, prompted with
getpass when needed). Afterwards fetches for that vehicle SSH to the alias.
"""

import getpass
import json
import os
import re
import subprocess
import sys
import tempfile

SSH_TIMEOUT = 10  # whole round trip, so a hung connection can't pin the CLI
SETUP_TIMEOUT = 20  # key-install round trip


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
    When a per-truck alias exists for it (see setup_ssh), the fetch SSHes to
    the alias so that truck's own identity and known-hosts file apply.
    Raises TruckError with a message the user can act on.
    """
    vehicle = (vehicle or "").strip()
    if vehicle and not vehicle.isdigit():
        raise TruckError(f"invalid vehicle number {vehicle!r} (digits only)")

    ssh = ssh_bin or _env_or("TRUCK_SSH_BIN", "ssh")
    dest = resolve_target(vehicle) if target is None else target
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
            hint = ""
            if vehicle and not has_alias(vehicle):
                hint = " If this truck shares its IP with others, run `truck setup " + vehicle + "` first."
            raise TruckError(
                f"could not SSH to {dest} — host unreachable or the key was rejected. "
                f"Test it yourself with `ssh {dest}` ({detail}).{hint}"
            )
        raise TruckError(f"ssh failed with exit code {proc.returncode} ({detail})")
    return parse_output(proc.stdout, vehicle)


# ---- Per-truck SSH setup (the shared-IP fix) -------------------------------


def ssh_dir():
    """~/.ssh, or TRUCK_SSH_DIR when overridden (tests point it elsewhere)."""
    override = os.environ.get("TRUCK_SSH_DIR")
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".ssh")


def alias_for(vehicle):
    return "truck-" + vehicle


def _host_block_re(alias):
    return re.compile(r"(?m)^\s*Host\s+" + re.escape(alias) + r"\s*$")


def has_alias(vehicle):
    """True when ~/.ssh/config defines the Host alias for this vehicle."""
    if not (vehicle or "").isdigit():
        return False
    try:
        with open(os.path.join(ssh_dir(), "config")) as f:
            return bool(_host_block_re(alias_for(vehicle)).search(f.read()))
    except OSError:
        return False


def resolve_target(vehicle, target=None):
    """The per-truck alias when one is configured for this vehicle, else the
    raw TRUCK_SSH_TARGET (or the explicit target)."""
    dest = target or _env_or("TRUCK_SSH_TARGET", "applied@192.168.1.11")
    if vehicle and has_alias(vehicle):
        return alias_for(vehicle)
    return dest


def _split_target(target):
    """'applied@192.168.1.11' -> ('applied', '192.168.1.11')."""
    if "@" in target:
        user, _, host = target.rpartition("@")
        return user, host
    return "", target


def config_block(vehicle):
    """The managed ~/.ssh/config block for a vehicle, named after its number."""
    alias = alias_for(vehicle)
    user, host = _split_target(_env_or("TRUCK_SSH_TARGET", "applied@192.168.1.11"))
    d = ssh_dir()
    lines = [
        f"# {alias} — added by start-stack-app truck SSH setup",
        f"Host {alias}",
        f"    HostName {host}",
    ]
    if user:
        lines.append(f"    User {user}")
    lines += [
        f"    IdentityFile {os.path.join(d, alias)}",
        "    IdentitiesOnly yes",
        f"    UserKnownHostsFile {os.path.join(d, 'known_hosts.d', alias)}",
        "    StrictHostKeyChecking accept-new",
    ]
    return "\n".join(lines) + "\n"


def _authorized_keys_script():
    """Appends the stdin key to authorized_keys unless already present."""
    return (
        "umask 077; mkdir -p ~/.ssh; key=$(cat); "
        'grep -qxF -- "$key" ~/.ssh/authorized_keys 2>/dev/null '
        '|| printf \'%s\\n\' "$key" >> ~/.ssh/authorized_keys'
    )


def _install_key(vehicle, public_key, password="", timeout=SETUP_TIMEOUT):
    """Push the public key to the truck. Returns (installed, detail).

    Connects to the raw address (the alias's own key isn't authorized yet)
    but records the host key under the alias's known-hosts file. Attempt 1:
    existing key/agent (BatchMode). Attempt 2: the password via SSH_ASKPASS
    in a detached session — the password travels in the environment of the
    ssh process, never on a command line.
    """
    ssh = _env_or("TRUCK_SSH_BIN", "ssh")
    target = _env_or("TRUCK_SSH_TARGET", "applied@192.168.1.11")
    known_hosts = os.path.join(ssh_dir(), "known_hosts.d", alias_for(vehicle))
    common = [
        "-o", "ConnectTimeout=5",
        "-o", "IdentitiesOnly=no",
        "-o", f"UserKnownHostsFile={known_hosts}",
        "-o", "StrictHostKeyChecking=accept-new",
    ]

    def run(extra, env=None, detach=False):
        args = [ssh, *common, *extra, target, _authorized_keys_script()]
        kwargs = {}
        if detach:
            kwargs["start_new_session"] = True  # no tty for SSH_ASKPASS
        try:
            proc = subprocess.run(
                args, input=public_key + "\n", capture_output=True, text=True,
                timeout=timeout, env={**os.environ, **(env or {})}, **kwargs,
            )
        except subprocess.TimeoutExpired:
            return False, "timed out reaching the truck"
        except FileNotFoundError:
            return False, f"no {ssh!r} binary found — is SSH installed?"
        if proc.returncode == 0:
            return True, ""
        detail = proc.stderr.strip()
        detail = detail if len(detail) <= 200 else detail[:200] + "…"
        return False, detail

    installed, detail = run(["-o", "BatchMode=yes"])
    if installed:
        return True, "installed using your existing SSH key/agent"
    if not password:
        return False, "your existing key was not accepted and no password was given (" + detail + ")"

    # Attempt 2: the one-time password, through an askpass helper.
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write("#!/bin/sh\nprintf '%s' \"$TRUCK_SSH_PASSWORD\"\n")
        askpass = f.name
    try:
        os.chmod(askpass, 0o700)
        env = {
            "SSH_ASKPASS": askpass,
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": ":0",  # older OpenSSH only consults SSH_ASKPASS with DISPLAY set
            "TRUCK_SSH_PASSWORD": password,
        }
        installed, detail = run(
            ["-o", "NumberOfPasswordPrompts=1", "-o", "PreferredAuthentications=password,keyboard-interactive"],
            env=env, detach=True,
        )
    finally:
        os.remove(askpass)
    if installed:
        return True, "installed using the password you entered"
    return False, "the password was not accepted (" + detail + ")"


def setup_ssh(vehicle, password=""):
    """One-time per-truck SSH setup; the name is forced to the truck number.

    Returns a dict: vehicle, alias, key_path, public_key, key_created,
    config_added, key_installed, install_detail, next_step. Only the key
    install can fail without stopping the rest: the identity and config are
    still written, and next_step carries the ssh-copy-id line to run by hand.
    """
    vehicle = (vehicle or "").strip()
    if not vehicle.isdigit():
        raise TruckError(
            f"the truck number is required and digits-only (got {vehicle!r}) — "
            "the SSH identity and alias are named after it"
        )
    alias = alias_for(vehicle)
    d = ssh_dir()
    res = {
        "vehicle": vehicle, "alias": alias,
        "key_path": os.path.join(d, alias),
        "next_step": "",
    }

    os.makedirs(os.path.join(d, "known_hosts.d"), mode=0o700, exist_ok=True)

    # 1. Identity: one ed25519 key per truck, no passphrase.
    if not os.path.exists(res["key_path"]):
        keygen = _env_or("TRUCK_KEYGEN_BIN", "ssh-keygen")
        try:
            subprocess.run(
                [keygen, "-q", "-t", "ed25519", "-N", "", "-C", alias, "-f", res["key_path"]],
                capture_output=True, text=True, timeout=15, check=True,
            )
        except FileNotFoundError:
            raise TruckError(f"no {keygen!r} binary found — is OpenSSH installed?") from None
        except subprocess.TimeoutExpired:
            raise TruckError("ssh-keygen timed out") from None
        except subprocess.CalledProcessError as err:
            raise TruckError(f"ssh-keygen failed: {(err.stderr or '').strip()}") from None
        res["key_created"] = True
    else:
        res["key_created"] = False

    with open(res["key_path"] + ".pub") as f:
        res["public_key"] = f.read().strip()

    # 2. Config block, appended once.
    res["config_added"] = not has_alias(vehicle)
    if res["config_added"]:
        config_path = os.path.join(d, "config")
        existing = ""
        if os.path.exists(config_path):
            with open(config_path) as f:
                existing = f.read()
        with open(config_path, "a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write("\n" + config_block(vehicle))

    # 3. Install the public key on the truck.
    res["key_installed"], res["install_detail"] = _install_key(vehicle, res["public_key"], password)
    if not res["key_installed"]:
        user, host = _split_target(_env_or("TRUCK_SSH_TARGET", "applied@192.168.1.11"))
        dest = f"{user}@{host}" if user else host
        res["next_step"] = (
            f"ssh-copy-id -i {res['key_path']}.pub "
            f"-o UserKnownHostsFile={os.path.join(d, 'known_hosts.d', alias)} {dest}"
        )
    return res


def retry_install(vehicle, public_key, password):
    """Retry just the key install with a password (the wizard/CLI ask for it
    only after the existing key was rejected). Returns (installed, detail)."""
    return _install_key(vehicle, public_key, password)


def main(argv):
    """CLI: truck.py [vehicle] [--json], or truck.py setup <vehicle> [--json].

    Exit 0 on success, 1 on failure."""
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]

    if args and args[0] == "setup":
        if len(args) != 2:
            print(f"usage: {os.path.basename(sys.argv[0])} setup <vehicle> [--json]", file=sys.stderr)
            return 1
        try:
            res = setup_ssh(args[1])
        except TruckError as err:
            if as_json:
                print(json.dumps({"error": str(err)}))
            else:
                print(f"error: {err}", file=sys.stderr)
            return 1
        # The install is the only step that can need a password; ask once,
        # off any command line (getpass), and retry just that step.
        if not res["key_installed"] and not as_json:
            password = getpass.getpass(
                "Your existing SSH key was not accepted. Truck login password "
                "(Enter to skip and do it by hand): "
            )
            if password:
                res["key_installed"], res["install_detail"] = _install_key(
                    args[1], res["public_key"], password
                )
        if as_json:
            if not res["key_installed"]:
                res["next_step"] = res.get("next_step") or ""
            print(json.dumps(res))
            return 0 if res["key_installed"] else 1
        print_setup_result(res)
        return 0 if res["key_installed"] else 1

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


def print_setup_result(res):
    """Human-readable summary of a setup result (shared with the wizard)."""
    key_state = "created" if res["key_created"] else "already existed"
    cfg_state = "added" if res["config_added"] else "already existed"
    print(f"{res['alias']}: identity {key_state} ({res['key_path']}), config block {cfg_state}.")
    if res["key_installed"]:
        print(f"✅ public key installed — {res['install_detail']}.")
        print(f"Next: `ssh {res['alias']}` and the run-id fetch for {res['vehicle']} now work with no password.")
    else:
        print(f"⚠️  public key not installed — {res['install_detail']}")
        if res.get("next_step"):
            print("Run it by hand, then fetch again:")
            print("  " + res["next_step"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
