import csv
import os
from collections import namedtuple

from brain2_routes import load_map_and_route_options

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "options.csv")

Option = namedtuple("Option", ["value", "label", "owner", "language"])

DEFAULT_OPTIONS = {
    "vehicle_name": [Option("truck-807", "truck-807", "", "")],
    "launch_config": [Option("sds_road_readiness", "sds_road_readiness", "", "")],
}

CSV_FIELDS = ["vehicle_name", "launch_config"]
FIELDS = CSV_FIELDS + ["map_key", "route"]


def load_options(csv_path=CSV_PATH):
    options = {field: [] for field in CSV_FIELDS}
    if os.path.exists(csv_path):
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                field, value = row.get("field"), row.get("value")
                nickname = (row.get("nickname") or "").strip()
                if field in options and value:
                    options[field].append(Option(value, nickname or value, "", ""))
    for field in CSV_FIELDS:
        if not options[field]:
            options[field] = DEFAULT_OPTIONS[field]

    # map_key/route are not curated in options.csv - they're scanned live from
    # brain2's route definitions every time the tool launches.
    options.update(load_map_and_route_options())
    return options


def routes_for_map_key(options, map_key):
    """Restrict routes to only those whose owner map is the selected map_key.

    Routes with no owner, or a different owner, never show up once a
    map_key is selected.
    """
    if not map_key:
        return options["route"]
    return [opt for opt in options["route"] if opt.owner == map_key]


def map_keys_for_language(options, lang):
    """Return the available map_keys.

    map_key options are sourced live from brain2 and carry no per-language
    restriction, so every map is available regardless of UI language.
    """
    return options["map_key"]


def build_command(vehicle_name, launch_config, route="", enable_japan_driving=False):
    args = [f"--vehicle_name {vehicle_name}", f"--launch_config {launch_config}"]
    if route:
        args.append(f"--route {route}")
    if enable_japan_driving:
        args.append("--enable_japan_driving")
    # Line-break before each flag with a trailing backslash, so the command
    # stays valid to paste into a shell but reads one flag per line.
    return " \\\n  ".join(["start_stack"] + args)
