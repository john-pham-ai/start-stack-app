"""Live route options scanned from a local brain2 checkout.

brain2's route definition files are the source of truth for which routes
exist. When a brain2 checkout is available, options are derived from those
files so they're never stale. When it isn't (no BRAIN2_REPO_PATH env var, no
checkout in the usual places), we raise Brain2RoutesError and the caller
falls back to options.csv's curated rows — the tool keeps working, just with
CSV data.

Each route carries its map (the `owner` field), which the UIs use to group
the route list. A route name used by more than one map is disambiguated as
"map_name:route_name" (the value) with "route_name (map_name)" as its label,
since the built command doesn't carry a separate map flag.
"""

import glob
import os
import re
from collections import namedtuple

Option = namedtuple("Option", ["value", "label", "owner", "language"])

ROUTES_SUBDIR = "onroad/config/constants/behavior/routes"

# Catches both `identifier { map_name: "x" route_name: "y" }` (text proto
# allows commas/newlines between fields) across the file.
IDENTIFIER_RE = re.compile(
    r'identifier:?\s*\{\s*map_name:\s*"([^"]+)"\s*,?\s*route_name:\s*"([^"]+)"',
    re.MULTILINE,
)

# Where to look for a checkout, in order, when BRAIN2_REPO_PATH isn't set.
DEFAULT_REPO_CANDIDATES = ("~/brain2", "~/Projects/brain2")


class Brain2RoutesError(Exception):
    """brain2's route definitions couldn't be read; fall back to options.csv."""


def find_brain2_repo(env=None):
    """Return the path to a brain2 checkout that has route files, or None.

    Checks $BRAIN2_REPO_PATH first, then the usual checkout locations. A
    candidate only counts if its routes subdirectory actually exists.
    """
    env = env if env is not None else os.environ
    candidates = []
    env_path = env.get("BRAIN2_REPO_PATH", "")
    if env_path:
        candidates.append(os.path.expanduser(env_path))
    candidates += [os.path.expanduser(p) for p in DEFAULT_REPO_CANDIDATES]
    for path in candidates:
        if os.path.isdir(os.path.join(path, ROUTES_SUBDIR)):
            return path
    return None


def scan_route_pairs(repo_path):
    """Parse (map_name, route_name) pairs from every routes/**/*.txtpb file.

    The glob is recursive, so route files for every map are picked up no
    matter how they're organized under the routes directory.
    """
    routes_dir = os.path.join(repo_path, ROUTES_SUBDIR)
    pairs = set()
    for path in sorted(glob.glob(os.path.join(routes_dir, "**", "*.txtpb"), recursive=True)):
        with open(path, encoding="utf-8") as f:
            content = f.read()
        pairs.update(IDENTIFIER_RE.findall(content))
    return sorted(pairs)


def build_route_options(pairs):
    """Turn (map_name, route_name) pairs into a route option list.

    Each route's owner is its map (used to group the list in the UI). A
    route name used by more than one map is disambiguated: its value becomes
    "map_name:route_name" and its label "route_name (map_name)" so the two
    entries stay tellable apart without a map picker.
    """
    maps_by_route = {}
    for map_name, route_name in pairs:
        maps_by_route.setdefault(route_name, set()).add(map_name)

    route_options = []
    for map_name, route_name in pairs:
        ambiguous = len(maps_by_route[route_name]) > 1
        if ambiguous:
            value = f"{map_name}:{route_name}"
            label = f"{route_name} ({map_name})"
        else:
            value = route_name
            label = route_name
        route_options.append(Option(value, label, map_name, ""))
    route_options.sort(key=lambda opt: (opt.owner, opt.label))
    return route_options


def load_route_options(repo_path=None):
    """Scan brain2's route files and build the live route options.

    Raises Brain2RoutesError when no checkout is findable or when the route
    files yield nothing — callers should treat that as "use options.csv".
    """
    repo_path = repo_path or find_brain2_repo()
    if repo_path is None:
        raise Brain2RoutesError(
            "No brain2 checkout found. Set BRAIN2_REPO_PATH or clone brain2 "
            f"to one of: {', '.join(DEFAULT_REPO_CANDIDATES)}"
        )

    routes_dir = os.path.join(repo_path, ROUTES_SUBDIR)
    if not os.path.isdir(routes_dir):
        raise Brain2RoutesError(f"brain2 routes directory not found at {routes_dir!r}")

    pairs = scan_route_pairs(repo_path)
    if not pairs:
        raise Brain2RoutesError(f"No route identifiers found in {routes_dir!r} (*.txtpb)")

    return build_route_options(pairs)
