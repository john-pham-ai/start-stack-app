import csv
import os
from collections import namedtuple

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "options.csv")

Option = namedtuple("Option", ["value", "label"])

DEFAULT_OPTIONS = {
    "vehicle_name": [Option("truck-807", "truck-807")],
    "launch_config": [Option("sds_road_readiness", "sds_road_readiness")],
    "map_key": [Option("shirosato_zone_54", "shirosato_zone_54")],
    "route": [Option("shoreline_terminal_10kph", "shoreline_terminal_10kph")],
}

FIELDS = ["vehicle_name", "launch_config", "map_key", "route"]


def load_options(csv_path=CSV_PATH):
    options = {field: [] for field in FIELDS}
    if os.path.exists(csv_path):
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                field, value = row.get("field"), row.get("value")
                nickname = (row.get("nickname") or "").strip()
                if field in options and value:
                    options[field].append(Option(value, nickname or value))
    for field in FIELDS:
        if not options[field]:
            options[field] = DEFAULT_OPTIONS[field]
    return options


def routes_for_map_key(options, map_key):
    """Show routes for the selected map_key plus routes not owned by any map_key.

    A route is "owned" by a map_key if its value is prefixed with that
    map_key's value (e.g. crows_landing_cw_outer_loop is owned by
    crows_landing). Owned routes only show up for their own map_key;
    unprefixed routes are generic and show up for every map_key.
    """
    if not map_key:
        return options["route"]
    map_key_values = [opt.value for opt in options["map_key"]]

    def owner(route_value):
        return next((v for v in map_key_values if route_value.startswith(v)), None)

    visible = [opt for opt in options["route"] if owner(opt.value) in (None, map_key)]
    return visible if visible else options["route"]


def build_command(vehicle_name, launch_config, map_key="", route="", enable_japan_driving=False, local=False):
    parts = ["start_stack", "--vehicle_name", vehicle_name, "--launch_config", launch_config]
    if map_key:
        parts += ["--map_key", map_key]
    if route:
        parts += ["--route", route]
    if enable_japan_driving:
        parts.append("--enable_japan_driving")
    if local:
        parts.append("--local")
    return " ".join(parts)
