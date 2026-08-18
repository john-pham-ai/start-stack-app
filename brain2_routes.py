import glob
import os
import re
from collections import namedtuple

Option = namedtuple("Option", ["value", "label", "owner", "language"])

BRAIN2_REPO_PATH = os.environ.get("BRAIN2_REPO_PATH", "/home/john.pham/brain2")
ROUTES_SUBDIR = "onroad/config/constants/behavior/routes"

IDENTIFIER_RE = re.compile(
    r'identifier:?\s*\{\s*map_name:\s*"([^"]+)"\s*,?\s*route_name:\s*"([^"]+)"', re.MULTILINE
)


def load_map_and_route_options(repo_path=None):
    """Scan brain2's route .txtpb files and derive map_key/route options live.

    Returns {"map_key": [Option, ...], "route": [Option, ...]}. Route values are
    disambiguated as "map_name:route_name" when the same route_name appears
    under more than one map, so --route stays unambiguous.
    """
    repo_path = repo_path or BRAIN2_REPO_PATH
    routes_dir = os.path.join(repo_path, ROUTES_SUBDIR)
    if not os.path.isdir(routes_dir):
        raise FileNotFoundError(
            f"brain2 routes directory not found at {routes_dir!r}. "
            f"Set BRAIN2_REPO_PATH to a valid local clone of brain2 (currently {repo_path!r})."
        )

    pairs = set()
    for path in glob.glob(os.path.join(routes_dir, "*.txtpb")):
        with open(path) as f:
            content = f.read()
        for map_name, route_name in IDENTIFIER_RE.findall(content):
            pairs.add((map_name, route_name))

    map_names = sorted({map_name for map_name, _ in pairs})
    route_names_seen = {}
    for map_name, route_name in pairs:
        route_names_seen.setdefault(route_name, set()).add(map_name)

    map_options = [Option(name, name, "", "") for name in map_names]

    route_options = []
    for map_name, route_name in sorted(pairs):
        ambiguous = len(route_names_seen[route_name]) > 1
        value = f"{map_name}:{route_name}" if ambiguous else route_name
        route_options.append(Option(value, route_name, map_name, ""))
    route_options.sort(key=lambda opt: (opt.owner, opt.label))

    return {"map_key": map_options, "route": route_options}
