"""A tiny self-updating copy of brain2's routes, fetched from GitHub.

The app needs exactly one directory out of the (large) brain2 repo:
onroad/config/constants/behavior/routes. A blobless, sparse, shallow
clone of just that directory lives in ~/.cache/start-stack-app/routes
and is refreshed from origin/master on launch — so the route list is
always the repo's latest without anyone hand-editing this tool, and
without touching whatever branch or uncommitted state a developer's
real ~/brain2 checkout happens to be in.

Every failure mode (no git, no network, hung network, corrupt cache)
is swallowed and reported as "no synced routes": callers fall back to
scanning a local brain2 checkout (brain2_routes.find_brain2_repo),
then to options.csv. A previously-synced cache that can't be refreshed
right now still counts — stale remote data beats none, and it never
blocks the app behind the network.

Env knobs (see sync_disabled / sync_routes):
  ROUTES_SYNC        "off"/"0"/"false"/"no" disables the GitHub fetch
                     entirely (the local checkout scan is used).
  ROUTES_REMOTE_URL  override the remote (default: the brain2 GitHub URL).
  ROUTES_BRANCH      override the branch (default: master).
  ROUTES_CACHE_DIR   override where the cache clone lives.
"""

import os
import subprocess
import time

ROUTES_SUBDIR = "onroad/config/constants/behavior/routes"

DEFAULT_REMOTE = "https://github.com/Ext-Applied-Frontier/brain2"
DEFAULT_BRANCH = "master"
DEFAULT_CACHE = os.path.join("~", ".cache", "start-stack-app", "routes")

SYNC_TTL_SECONDS = 60  # don't refetch more often than this (web UI is per-request)
COMMAND_TIMEOUT = 20   # a hung clone/fetch must never hang the app


def sync_disabled(env=None):
    env = env if env is not None else os.environ
    return (env.get("ROUTES_SYNC", "") or "").strip().lower() in ("off", "0", "false", "no")


def routes_cache_dir(env=None):
    env = env if env is not None else os.environ
    return os.path.expanduser(env.get("ROUTES_CACHE_DIR", "") or DEFAULT_CACHE)


def _git(args, cwd=None, timeout=COMMAND_TIMEOUT):
    # check=True: a failed fetch/clone must raise, not silently leave a
    # half-synced cache that looks like success.
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        timeout=timeout,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _marker_path(cache_dir):
    return os.path.join(cache_dir, ".routes-sync-last")


def _fresh(cache_dir, ttl):
    """True when the last sync is more recent than ttl seconds ago."""
    try:
        with open(_marker_path(cache_dir), encoding="utf-8") as f:
            return time.time() - float(f.read().strip()) < ttl
    except (OSError, ValueError):
        return False


def _write_marker(cache_dir):
    with open(_marker_path(cache_dir), "w", encoding="utf-8") as f:
        f.write(str(time.time()))


def _lock(cache_dir):
    """A best-effort lock file *outside* the clone (git clean would eat one inside).

    Returns the open lock file (keep a reference!) or None when the lock
    is held elsewhere or the platform has no flock — in both cases the
    caller treats syncing as "not right now".
    """
    try:
        import fcntl
    except ImportError:
        return None
    try:
        lock = open(cache_dir + ".sync.lock", "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return lock


def sync_routes(remote=DEFAULT_REMOTE, branch=DEFAULT_BRANCH, cache_dir=None,
                env=None, force=False, ttl=SYNC_TTL_SECONDS):
    """Ensure the routes-only cache clone exists and is current.

    Returns the cache clone's path (its ROUTES_SUBDIR holds the fetched
    route files) on success — including the stale-cache case where a
    refresh failed but a previously-synced clone is usable — or None
    when there is nothing usable at all. Callers should treat None as
    "fall back to the local checkout".
    """
    env = env if env is not None else os.environ
    if sync_disabled(env):
        return None
    remote = (env.get("ROUTES_REMOTE_URL", "") or "").strip() or remote
    branch = (env.get("ROUTES_BRANCH", "") or "").strip() or branch
    cache_dir = cache_dir or routes_cache_dir(env)
    routes_dir = os.path.join(cache_dir, ROUTES_SUBDIR)

    have_clone = os.path.isdir(routes_dir)
    if have_clone and not force and _fresh(cache_dir, ttl):
        return cache_dir

    import shutil
    try:
        # The lock file lives next to the clone, so its parent must exist
        # before the very first sync.
        os.makedirs(os.path.dirname(cache_dir) or ".", exist_ok=True)
    except OSError:
        return None
    lock = _lock(cache_dir)
    if lock is None:
        # Someone else is mid-sync (or no locking available): a usable
        # clone stands as-is; otherwise leave the fallback to the caller.
        return cache_dir if have_clone else None
    try:
        if have_clone:
            _git(["fetch", "--quiet", "--depth", "1", remote, branch], cwd=cache_dir)
            _git(["reset", "--quiet", "--hard", "FETCH_HEAD"], cwd=cache_dir)
            _git(["clean", "-qfd"], cwd=cache_dir)
        else:
            if os.path.exists(cache_dir):  # corrupt leftovers from an aborted clone
                shutil.rmtree(cache_dir, ignore_errors=True)
            _git(["clone", "--quiet", "--depth", "1", "--filter=blob:none",
                  "--sparse", "--branch", branch, remote, cache_dir])
            _git(["sparse-checkout", "set", "--no-cone", ROUTES_SUBDIR], cwd=cache_dir)
        _write_marker(cache_dir)
        return cache_dir
    except (OSError, subprocess.SubprocessError, ValueError):
        # No git, offline, hung past the timeout, or a bad remote: a
        # previously-synced (possibly stale) cache still beats nothing.
        return cache_dir if os.path.isdir(routes_dir) else None
    finally:
        lock.close()


def synced_commit(cache_dir=None, env=None):
    """The short hash of the synced commit ("" when disabled or unknown)."""
    env = env if env is not None else os.environ
    if sync_disabled(env):
        return ""
    cache_dir = cache_dir or routes_cache_dir(env)
    try:
        out = subprocess.run(
            ["git", "-C", cache_dir, "rev-parse", "--short", "HEAD"],
            timeout=COMMAND_TIMEOUT,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
