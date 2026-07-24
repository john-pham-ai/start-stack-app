import csv
import os
from collections import namedtuple

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "options.csv")

Option = namedtuple("Option", ["value", "label", "owner", "language"])

DEFAULT_OPTIONS = {
    "vehicle_name": [Option("truck-807", "truck-807", "", "")],
    "launch_config": [Option("sds_road_readiness", "sds_road_readiness", "", "")],
    "map_key": [Option("shirosato_zone_54", "shirosato_zone_54", "", "")],
    "route": [Option("shoreline_terminal_10kph", "shoreline_terminal_10kph", "", "")],
}

FIELDS = ["vehicle_name", "launch_config", "map_key", "route"]


def load_options(csv_path=CSV_PATH):
    options = {field: [] for field in FIELDS}
    if os.path.exists(csv_path):
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                field, value = row.get("field"), row.get("value")
                nickname = (row.get("nickname") or "").strip()
                owner = (row.get("owner_map_key") or "").strip()
                language = (row.get("language") or "").strip()
                if field in options and value:
                    options[field].append(Option(value, nickname or value, owner, language))
    for field in FIELDS:
        if not options[field]:
            options[field] = DEFAULT_OPTIONS[field]
    return options


def routes_for_map_key(options, map_key):
    """Restrict routes to only those whose owner_map_key is the selected map_key.

    Routes with no owner, or a different owner, never show up once a
    map_key is selected (see the owner_map_key column in options.csv).
    """
    if not map_key:
        return options["route"]
    return [opt for opt in options["route"] if opt.owner == map_key]


def map_keys_for_language(options, lang):
    """Restrict map_keys to those available for the given UI language.

    A blank language means the map_key is available for every UI language
    (see the language column in options.csv).
    """
    return [opt for opt in options["map_key"] if not opt.language or opt.language == lang]


def build_command(vehicle_name, launch_config, map_key="", route="", enable_japan_driving=False):
    parts = ["start_stack", "--vehicle_name", vehicle_name, "--launch_config", launch_config]
    if map_key:
        parts += ["--map_key", map_key]
    if route:
        parts += ["--route", route]
    if enable_japan_driving:
        parts.append("--enable_japan_driving")
    return " ".join(parts)
