import csv
import os
from collections import namedtuple

from brain2_routes import Brain2RoutesError, find_brain2_repo, load_route_options
from routes_sync import sync_routes

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
    from brain2 when it's reachable (falling back to the CSV's route rows
    when it isn't).

    Routes come from the brain2 repo on GitHub via a self-updating
    routes-only cache clone (see routes_sync.py); when that isn't
    possible (offline, ROUTES_SYNC=off, no git), a local brain2
    checkout is scanned instead. The CSV's route rows do double duty:
    they're the last-resort source, and they carry nicknames ("Shoreline
    Terminal - Slow") that get overlaid onto any matching live-scanned
    routes so curated labels survive the merge.
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

    live_routes = _live_route_options()
    if live_routes is not None:
        options["route"] = _overlay(options["route"], live_routes)
    return options


def _live_route_options():
    """Route options straight from brain2, or None to keep the CSV's.

    Precedence: the routes-only cache synced from brain2's GitHub repo
    (always current with origin/master) → a local brain2 checkout
    (however fresh its last git pull was). Neither being usable means
    no brain2 at all — the CSV's route rows then stand in.
    """
    for repo_path in (sync_routes(), find_brain2_repo()):
        if not repo_path:
            continue
        try:
            return load_route_options(repo_path)
        except Brain2RoutesError:
            continue
    return None


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
