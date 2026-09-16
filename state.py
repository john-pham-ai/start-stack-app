import json
import os
import re
from datetime import datetime


def _default_state_path():
    """Where the presets/history state file lives.

    On an Apps Platform (Cloud Run) deployment the container filesystem is
    ephemeral — state would vanish on every redeploy — so when the
    platform's persistent Filestore mount (/mnt/data) is there, the state
    moves onto it (K_SERVICE is how Cloud Run identifies itself; it's
    unset on laptops and in tests). Everywhere else the file stays next
    to the tool, exactly as before, and the TUI and web UI keep sharing
    one file per machine.
    """
    # (enable_gcs_fuse in project.toml; the mount path is /mnt/data either way.)
    if os.environ.get("K_SERVICE") and os.path.isdir("/mnt/data"):
        return os.path.join("/mnt/data", "start-stack", ".launch_state.json")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".launch_state.json")


STATE_PATH = _default_state_path()

# How many recently built commands to remember (newest first).
MAX_HISTORY_ENTRIES = 20

# The fields that fully describe one built command / one preset.
COMMAND_FIELDS = ("vehicle_name", "launch_config", "route", "enable_japan_driving")

# Preset shapes: a values preset is a set of form answers the wizard/web UI
# rebuilds into a command; a custom preset is a raw command string saved as-is.
VALUES_PRESET = "values"
CUSTOM_PRESET = "command"

VEHICLE_FLAG_RE = re.compile(r"--vehicle_name[ =](\S+)")


def load_state(path=None):
    path = path or STATE_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state, path=None):
    path = path or STATE_PATH
    parent = os.path.dirname(path)
    if parent:  # /mnt/data/start-stack may not exist on a fresh mount
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def command_values(entry):
    """Pull the standard command fields out of a history entry or preset.

    enable_japan_driving defaults to False; the rest default to "".
    """
    values = {field: entry.get(field, "") for field in COMMAND_FIELDS}
    values["enable_japan_driving"] = bool(entry.get("enable_japan_driving"))
    return values


def remember_command(state, values, command, now=None, custom=False):
    """Insert a built command at the front of history, newest first.

    Building the same command again just refreshes the existing top entry's
    timestamp instead of stacking duplicates. History is capped at
    MAX_HISTORY_ENTRIES. A raw custom command can be recorded with custom=True
    so the UIs offer it back verbatim instead of re-deriving it from fields.
    """
    entry = {
        "built_at": (now or datetime.now()).isoformat(timespec="seconds"),
        "command": command,
        "custom": bool(custom),
    }
    entry.update(command_values(values))
    history = state.setdefault("history", [])
    if history and history[0].get("command") == command:
        history[0] = entry
    else:
        history.insert(0, entry)
    del history[MAX_HISTORY_ENTRIES:]
    return entry


def save_preset(state, name, values):
    """Save a full set of command choices under a name for one-step reuse."""
    name = (name or "").strip()
    if not name:
        return None
    state.setdefault("presets", {})[name] = command_values(values)
    return name


def load_preset(state, name):
    return state.get("presets", {}).get(name)


def delete_preset(state, name):
    """Remove a saved preset by name. Returns True if it existed."""
    presets = state.get("presets", {})
    if name in presets:
        del presets[name]
        return True
    return False


def preset_kind(entry):
    """Which shape a preset/history entry is: "values" or "command".

    Entries saved before custom presets existed carry no "kind", so they
    read as values presets — old state files keep working as-is.
    """
    if not isinstance(entry, dict):
        return VALUES_PRESET
    return CUSTOM_PRESET if entry.get("kind") == CUSTOM_PRESET else VALUES_PRESET


def normalize_custom_command(text):
    """Collapse a pasted command into a clean single line.

    Handles the common paste artifacts: a leading shell prompt ($/#), the
    multi-line backslash form the builder produces ("cmd \\n  --flag"), any
    other stray backslashes, and whitespace runs.
    """
    text = (text or "").strip()
    text = re.sub(r"^[#$]\s*", "", text)
    text = re.sub(r"\\\s*(\r?\n|\Z)", " ", text)  # line continuations / trailing \
    text = re.sub(r"\\\s+", " ", text)  # stray backslash before whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def vehicle_from_command(command):
    """Pull the --vehicle_name value out of a raw command ("" if absent)."""
    match = VEHICLE_FLAG_RE.search(command or "")
    return match.group(1) if match else ""


def command_entry_values(command):
    """History-row values for a raw custom command.

    Only the vehicle name is derivable; the rest stay blank, and the UIs
    display the command itself as the summary.
    """
    return {
        "vehicle_name": vehicle_from_command(command),
        "launch_config": "",
        "route": "",
        "enable_japan_driving": False,
    }


def save_custom_preset(state, name, command):
    """Save a raw command as a preset under a name for verbatim reuse."""
    name = (name or "").strip()
    command = (command or "").strip()
    if not name or not command:
        return None
    state.setdefault("presets", {})[name] = {"kind": CUSTOM_PRESET, "command": command}
    return name


def get_history(state, limit=None):
    history = state.get("history", [])
    return history[:limit] if limit is not None else history


# --- closed-loop mileage runs -------------------------------------------------
#
# A loop is one base command (vehicle, launch config, Japan driving on) driven
# over an ordered list of stops, each stop a route. Driving it means issuing
# the same command with the route swapped per stop, wrapping from the last
# stop back to the first for another lap — the "closed" part — until the
# tester declares the run done. Loops live in their own bucket so they never
# collide with values/custom presets in the menu or on disk.


# The closed-loop bucket is capped: the start menu gives loops the
# Q/W/E/R shortcut keys, and a bounded bucket keeps every saved loop one
# keystroke away (an over-full menu would push entries off the screen).
MAX_LOOPS = 4


class LoopBucketFull(Exception):
    """A 5th loop was saved (only MAX_LOOPS fit; re-saving an existing
    name is always allowed)."""


def loop_values(entry):
    """The base-command fields of a saved loop, with its stops.

    Japan driving is always on for a loop (the mode is a Japan route setup),
    regardless of what a hand-edited state file says; stops are the routes
    in driving order, with blanks dropped.
    """
    entry = entry if isinstance(entry, dict) else {}
    stops = [route for route in ((route or "").strip() for route in entry.get("stops", [])) if route]
    return {
        "vehicle_name": entry.get("vehicle_name", ""),
        "launch_config": entry.get("launch_config", ""),
        "enable_japan_driving": True,
        "stops": stops,
    }


def save_loop(state, name, values, stops):
    """Save a closed loop under a name. Returns the name, or None if the
    name is blank or there are no stops to drive. Raises LoopBucketFull
    when the bucket is already at MAX_LOOPS and the name isn't one of
    the existing loops."""
    name = (name or "").strip()
    stops = [route for route in ((route or "").strip() for route in (stops or [])) if route]
    if not name or not stops:
        return None
    loops = state.get("loops", {})
    if name not in loops and len(loops) >= MAX_LOOPS:
        raise LoopBucketFull(name)
    state.setdefault("loops", {})[name] = {
        "vehicle_name": values.get("vehicle_name", ""),
        "launch_config": values.get("launch_config", ""),
        "enable_japan_driving": True,
        "stops": stops,
    }
    return name


def load_loop(state, name):
    return state.get("loops", {}).get(name)


def delete_loop(state, name):
    """Remove a saved loop by name. Returns True if it existed."""
    loops = state.get("loops", {})
    if name in loops:
        del loops[name]
        return True
    return False
