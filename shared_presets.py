"""Presets that live in the repo, so a route one tester builds can be
one keystroke for everyone (see the flow in presets/README.md).

A shared preset is a values preset (vehicle, launch config, route,
japan toggle) committed to this repo as presets/<name>.json. The app
loads whatever the checkout has — and since the app self-updates from
origin on launch (self_update.py), a committed preset lands on every
machine by itself: no hand-editing, no re-typing.

Flow: a tester builds a preset and exports it (a JSON file named after
the preset), sends the file over, and it gets committed under presets/.
Sharing personal presets is opt-in — nothing leaves the machine until
the tester exports it.

The JSON schema is intentionally the state-file shape (the same dict
save_preset writes), plus optional metadata that defaults sensibly:

    {
      "vehicle_name": "truck-807",
      "launch_config": "sds_road_readiness",
      "route": "shoreline_straight",
      "enable_japan_driving": false,
      "kind": "values",                  # optional, only "values" is valid
      "exported_by": "jp",               # optional, who exported it
      "exported_at": "2026-09-16T10:00:00"  # optional, ISO timestamp
    }
"""

import json
import os
import re
import tempfile
from datetime import datetime

PRESETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets")
EXPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")

# Preset names become file names (and menu titles); keep them sane.
NAME_RE = re.compile(r"^[\w][\w \-]{0,63}$")
SHARED_TAG_KEY = "shared"


def _dir_path(configured, default):
    """Runtime lookup so tests can point the loader/exporter at a tmp dir."""
    return configured or default


class PresetImportError(Exception):
    """The user-visible reason an import was refused."""


def load_shared_presets(presets_dir=None):
    """Every valid shared preset in the repo's presets/ directory.

    Returns {name: entry} in file-name order, entry shaped like a personal
    values preset plus {"shared": true, "exported_by": ...} so the UIs can
    mark it. Malformed files are skipped — one bad file must never break
    the menu — and their names are returned alongside for diagnostics.
    """
    presets_dir = presets_dir or PRESETS_DIR
    shared, rejected = {}, []
    if not os.path.isdir(presets_dir):
        return shared, rejected
    for filename in sorted(os.listdir(presets_dir)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(presets_dir, filename)
        name = filename[: -len(".json")]
        try:
            with open(path, encoding="utf-8") as f:
                entry = json.load(f)
        except (json.JSONDecodeError, OSError):
            rejected.append(name)
            continue
        if not valid_shared_entry(entry, name):
            rejected.append(name)
            continue
        entry["shared"] = True
        shared[name] = entry
    return shared, rejected


def valid_shared_entry(entry, name):
    """True when entry parses as a values preset with a legal name.

    Only values presets can be shared: the whole point is a route setup
    that rebuilds on any machine, and a raw command is the machine's
    own to keep. Every command field must be present and a string/bool
    (a shared preset that silently forgets a field would build a
    half-configured command on other machines).
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("kind", "values") != "values":
        return False
    for field in ("vehicle_name", "launch_config", "route"):
        if not isinstance(entry.get(field), str):
            return False
    if not isinstance(entry.get("enable_japan_driving"), bool):
        return False
    return bool(NAME_RE.match(name or ""))


def merge_presets(personal, shared):
    """Personal and shared presets as one {name: entry} map.

    Personal entries come first (menu order) and win on a name clash —
    a tester who deliberately recreates a shared preset under the same
    name keeps their own version (the shared copy stays in the repo,
    untouched by local edits).
    """
    merged = dict(personal)
    for name, entry in shared.items():
        merged.setdefault(name, entry)
    return merged


def export_preset(name, entry, exports_dir=None):
    """Write a personal preset to an export file the tester can send in.

    Returns the path written, or None when the entry can't be shared (a
    custom command preset, a blank name, or a shared preset — those
    already live in the repo). The export lands in exports/<name>.json
    next to the tool by default; the file carries the exporter's
    $USER and a timestamp so the recipient knows where it came from.
    """
    name = (name or "").strip()
    if not name or entry.get("shared") or entry.get("kind"):
        return None
    if not NAME_RE.match(name):
        raise PresetImportError(
            "Preset names can use letters, digits, spaces and dashes "
            f"(up to 64 chars) — '{name}' can't be shared."
        )
    payload = dict(entry)
    payload.pop("shared", None)
    payload["kind"] = "values"
    payload["exported_by"] = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    payload["exported_at"] = datetime.now().isoformat(timespec="seconds")

    exports_dir = exports_dir or EXPORTS_DIR
    os.makedirs(exports_dir, exist_ok=True)
    path = os.path.join(exports_dir, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    return path


def parse_preset_export(data, name):
    """Validate preset-export bytes (or a str) into (name, entry).

    The core of both import paths — the TUI reads a file, the web UI
    reads an upload — raising PresetImportError with the reason when
    the data isn't a valid values-preset export.
    """
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError as err:
            raise PresetImportError(f"Could not read a preset: {err}")
    try:
        entry = json.loads(data)
    except json.JSONDecodeError as err:
        raise PresetImportError(f"Could not read a preset: {err}")
    name = (name or "").strip()
    if not valid_shared_entry(entry, name):
        raise PresetImportError(
            f"'{name}' is not a shared-able values preset — only presets "
            "built from the wizard's choices (vehicle, launch config, "
            "route, japan toggle) can be shared."
        )
    entry = dict(entry)
    for key in ("shared", "exported_by", "exported_at", "kind"):
        entry.pop(key, None)
    return name, entry


def import_preset_file(path, name=None):
    """Read an export file into a preset entry (validated, shared-stripped).

    Raises PresetImportError with the reason when the file isn't a valid
    values-preset export, so both UIs can show the same message. Returns
    (name, entry) with the entry ready for save_preset into local state.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as err:
        raise PresetImportError(f"Could not read {path}: {err}")
    name = (name or os.path.splitext(os.path.basename(path))[0])
    return parse_preset_export(data, name)


def write_temp_copy(name, entry):
    """An import-ready temp file path for the web UI's export download.

    The web UI hands the browser a one-off file (a real export file in
    exports/ would linger on a shared machine); the TUI's real file is
    still written by export_preset.
    """
    payload = dict(entry)
    payload.pop("shared", None)
    payload["kind"] = "values"
    fd, path = tempfile.mkstemp(prefix=f"{name}-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    return path
