import json
import os

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".launch_state.json")


def load_state(path=STATE_PATH):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state, path=STATE_PATH):
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
