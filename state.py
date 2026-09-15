import json
import os
from datetime import datetime

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".launch_state.json")

# How many recently built commands to remember (newest first).
MAX_HISTORY_ENTRIES = 20

# The fields that fully describe one built command / one preset.
COMMAND_FIELDS = ("vehicle_name", "launch_config", "route", "enable_japan_driving")


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
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def command_values(entry):
    """Pull the standard command fields out of a history entry or preset.

    enable_japan_driving defaults to False; the rest default to "".
    """
    values = {field: entry.get(field, "") for field in COMMAND_FIELDS}
    values["enable_japan_driving"] = bool(entry.get("enable_japan_driving"))
    return values


def remember_command(state, values, command, now=None):
    """Insert a built command at the front of history, newest first.

    Building the same command again just refreshes the existing top entry's
    timestamp instead of stacking duplicates. History is capped at
    MAX_HISTORY_ENTRIES.
    """
    entry = {"built_at": (now or datetime.now()).isoformat(timespec="seconds"), "command": command}
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


def get_history(state, limit=None):
    history = state.get("history", [])
    return history[:limit] if limit is not None else history
