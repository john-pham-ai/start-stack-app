import csv
import os
from collections import namedtuple

from brain2_routes import Brain2RoutesError, load_route_options

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "options.csv")

Option = namedtuple("Option", ["value", "label", "owner", "language"])

DEFAULT_OPTIONS = {
    "vehicle_name": [Option("truck-807", "truck-807", "", "")],
    "launch_config": [Option("sds_road_readiness", "sds_road_readiness", "", "")],
    "route": [Option("shoreline_terminal_10kph", "shoreline_terminal_10kph", "", "")],
}

FIELDS = ["vehicle_name", "launch_config", "route"]


def load_options(csv_path=CSV_PATH):
    """Load vehicle/config options from options.csv, and route options live
    from a brain2 checkout when one is available (falling back to the CSV's
    route rows when it isn't).

    The CSV's route rows do double duty: they're the fallback source when
    brain2 is missing, and they carry nicknames ("Shoreline Terminal -
    Slow") that get overlaid onto any matching live-scanned routes so
    curated labels survive the merge.
    """
    options = {field: [] for field in FIELDS}
    if os.path.exists(csv_path):
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                field, value = row.get("field"), row.get("value")
                nickname = (row.get("nickname") or "").strip()
                owner = (row.get("owner_map_key") or "").strip()
                if field in options and value:
                    options[field].append(Option(value, nickname or value, owner, ""))
    for field in FIELDS:
        if not options[field]:
            options[field] = DEFAULT_OPTIONS[field]

    try:
        live_routes = load_route_options()
    except Brain2RoutesError:
        pass  # no usable brain2 checkout — keep the CSV-derived options
    else:
        options["route"] = _overlay(options["route"], live_routes)
    return options


def _overlay(csv_options, live_options):
    """Overlay CSV nicknames onto matching live-scanned routes.

    Live options own the value set and the route→map ownership (the CSV's
    may be stale); for any value the CSV also knows about, its nickname
    wins so curated labels survive the merge.
    """
    csv_by_value = {opt.value: opt for opt in csv_options}
    merged = []
    for live_opt in live_options:
        csv_opt = csv_by_value.get(live_opt.value)
        if csv_opt is None:
            merged.append(live_opt)
        else:
            merged.append(Option(live_opt.value, csv_opt.label, live_opt.owner, ""))
    return merged


def map_key_for_route(options, route):
    """The map a route belongs to ("" when the route or owner is unknown).

    Commands don't carry a map flag — routes carry their map — but this is
    still useful context for recording sidecars.
    """
    for opt in options["route"]:
        if opt.value == route:
            return opt.owner
    return ""


def build_command(vehicle_name, launch_config, route="", enable_japan_driving=False):
    """Assemble the start_stack command, one flag per line.

    No --map_key: routes carry their map, so --route alone is enough (a route
    name used by more than one map is emitted as "map_name:route_name").
    """
    args = [f"--vehicle_name {vehicle_name}", f"--launch_config {launch_config}"]
    if route:
        args.append(f"--route {route}")
    if enable_japan_driving:
        args.append("--enable_japan_driving")
    # Line-break before each flag with a trailing backslash, so the command
    # stays valid to paste into a shell but reads one flag per line.
    return " \\\n  ".join(["start_stack"] + args)
