"""The app updates itself from its own GitHub repo on launch.

start-stack-app is its own checkout (origin on GitHub), so staying current
is just a fetch + fast-forward of that checkout: `self_update()` fetches
the running copy's branch, and when origin is ahead, pulls it --ff-only.
The running process keeps its already-loaded code — the update lands on
the next launch (whose launcher script re-installs requirements.txt too).

Self-updating must never break launching: every failure mode (no git, no
network, not a repo, dirty tree, timeout) degrades to a no-op with a
status for the caller. A dirty working tree blocks the pull — a local
edit should never be silently clobbered — and the status says so.

Env knobs:
  APP_UPDATE  "off"/"0"/"false"/"no" disables the check entirely.
"""

import os
import subprocess
import time

from routes_sync import COMMAND_TIMEOUT

DEFAULT_TTL = 3600  # don't re-check more often than hourly (web UI is per-request)


def short(commit):
    """A git-style short hash (7 chars, like rev-parse --short)."""
    return commit[:7]

UPDATED = "updated"    # origin was ahead; fast-forwarded to it
BLOCKED = "blocked"    # origin is ahead but the working tree is dirty
CURRENT = "current"    # already at origin's tip
SKIPPED = "skipped"    # disabled, not a repo, or any failure — nothing to say


def update_disabled(env=None):
    env = env if env is not None else os.environ
    return (env.get("APP_UPDATE", "") or "").strip().lower() in ("off", "0", "false", "no")


def _marker_path():
    cache = os.path.expanduser(os.path.join("~", ".cache", "start-stack-app"))
    return os.path.join(cache, "self-update.last")


def _fresh(ttl):
    try:
        with open(_marker_path(), encoding="utf-8") as f:
            return time.time() - float(f.read().strip()) < ttl
    except (OSError, ValueError):
        return False


def _write_marker():
    os.makedirs(os.path.dirname(_marker_path()), exist_ok=True)
    with open(_marker_path(), "w", encoding="utf-8") as f:
        f.write(str(time.time()))


def _git(args, cwd, capture=False):
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        timeout=COMMAND_TIMEOUT,
        check=True,
        capture_output=capture,
        text=capture,
    )


def _clean_lock(repo_dir):
    """The same lock trick routes_sync uses, next to the repo."""
    try:
        import fcntl
    except ImportError:
        return None
    try:
        lock = open(repo_dir.rstrip("/") + ".self-update.lock", "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return lock


def self_update(repo_dir=None, env=None, force=False, ttl=DEFAULT_TTL):
    """Fetch the app's own repo; fast-forward when origin is ahead.

    Returns a (status, detail) tuple — UPDATED carries the new short
    hash, BLOCKED/SKIPPED carry "". Callers print the interesting ones
    and stay quiet otherwise.
    """
    env = env if env is not None else os.environ
    if update_disabled(env):
        return (SKIPPED, "")
    repo_dir = os.path.abspath(repo_dir or os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isdir(os.path.join(repo_dir, ".git")):
        return (SKIPPED, "")
    if not force and _fresh(ttl):
        return (CURRENT, "")

    lock = _clean_lock(repo_dir)
    if lock is None:
        return (SKIPPED, "")  # another process is mid-update
    try:
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_dir, capture=True).stdout.strip()
        _git(["fetch", "--quiet", "origin", branch], repo_dir)
        local = _git(["rev-parse", "HEAD"], repo_dir, capture=True).stdout.strip()
        remote = _git(["rev-parse", "FETCH_HEAD"], repo_dir, capture=True).stdout.strip()
        if local == remote:
            _write_marker()
            return (CURRENT, "")
        if _is_dirty(repo_dir):
            return (BLOCKED, short(remote))
        _git(["merge", "--quiet", "--ff-only", "FETCH_HEAD"], repo_dir)
        _write_marker()
        return (UPDATED, short(remote))
    except (OSError, subprocess.SubprocessError, ValueError):
        return (SKIPPED, "")
    finally:
        lock.close()


def _is_dirty(repo_dir):
    """True when the tree has local changes or untracked files — anything
    that a pull could clobber (diff alone misses untracked files)."""
    try:
        out = _git(["status", "--porcelain"], repo_dir, capture=True).stdout
        return bool(out.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return True  # couldn't tell — don't risk clobbering
