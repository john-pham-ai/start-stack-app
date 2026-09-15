from datetime import datetime

import pytest

import state as state_module
from state import (
    MAX_HISTORY_ENTRIES,
    command_entry_values,
    command_values,
    delete_preset,
    get_history,
    load_preset,
    load_state,
    normalize_custom_command,
    preset_kind,
    remember_command,
    save_custom_preset,
    save_preset,
    save_state,
    vehicle_from_command,
)


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point every test at its own state file."""
    path = tmp_path / "state.json"
    monkeypatch.setattr(state_module, "STATE_PATH", str(path))
    return path


def values(vehicle="truck-807", config="sds_road_readiness", route="", japan=False):
    return {
        "vehicle_name": vehicle,
        "launch_config": config,
        "route": route,
        "enable_japan_driving": japan,
    }


class TestLoadSaveState:
    def test_missing_file_is_empty(self):
        assert load_state() == {}

    def test_roundtrip(self):
        save_state({"a": 1})
        assert load_state() == {"a": 1}

    def test_corrupt_json_is_empty(self, isolated_state):
        isolated_state.write_text("{not json")
        assert load_state() == {}

    def test_path_resolved_at_call_time(self, isolated_state):
        # Save via one path spelling, load via the (patched) default.
        save_state({"x": 1}, path=str(isolated_state))
        assert load_state() == {"x": 1}


class TestRememberCommand:
    def test_newest_first(self):
        state = {}
        remember_command(state, values(), "cmd-a", now=datetime(2026, 9, 14, 10))
        remember_command(state, values(vehicle="truck-808"), "cmd-b", now=datetime(2026, 9, 14, 11))
        assert [e["command"] for e in get_history(state)] == ["cmd-b", "cmd-a"]

    def test_rebuilding_same_command_dedupes(self):
        state = {}
        remember_command(state, values(), "cmd-a", now=datetime(2026, 9, 14, 10))
        remember_command(state, values(), "cmd-a", now=datetime(2026, 9, 14, 11))
        history = get_history(state)
        assert len(history) == 1
        assert history[0]["built_at"] == "2026-09-14T11:00:00"

    def test_history_capped(self):
        state = {}
        for n in range(MAX_HISTORY_ENTRIES + 5):
            remember_command(state, values(vehicle=f"truck-{n}"), f"cmd-{n}")
        assert len(get_history(state)) == MAX_HISTORY_ENTRIES
        assert get_history(state)[0]["command"] == f"cmd-{MAX_HISTORY_ENTRIES + 4}"

    def test_entry_carries_full_values(self):
        state = {}
        entry = remember_command(
            state, values(route="shoreline_straight", japan=True), "cmd"
        )
        assert entry["vehicle_name"] == "truck-807"
        assert entry["route"] == "shoreline_straight"
        assert entry["enable_japan_driving"] is True

    def test_get_history_limit(self):
        state = {}
        for n in range(5):
            remember_command(state, values(vehicle=f"truck-{n}"), f"cmd-{n}")
        assert [e["command"] for e in get_history(state, limit=2)] == ["cmd-4", "cmd-3"]


class TestPresets:
    def test_save_and_load(self):
        state = {}
        save_preset(state, "night loop", values(route="night_loop"))
        preset = load_preset(state, "night loop")
        assert preset["route"] == "night_loop"
        assert preset["enable_japan_driving"] is False

    def test_blank_name_rejected(self):
        state = {}
        assert save_preset(state, "   ", values()) is None
        assert state == {}

    def test_overwrite_same_name(self):
        state = {}
        save_preset(state, "p", values(route="a"))
        save_preset(state, "p", values(route="b"))
        assert load_preset(state, "p")["route"] == "b"

    def test_delete_existing(self):
        state = {}
        save_preset(state, "p", values(route="a"))
        assert delete_preset(state, "p") is True
        assert state["presets"] == {}

    def test_delete_last_one_removes_presets_dict(self):
        state = {"presets": {"p": values()}}
        delete_preset(state, "p")
        assert state["presets"] == {}

    def test_delete_missing_is_false(self):
        state = {"presets": {"p": values()}}
        assert delete_preset(state, "nope") is False
        assert "p" in state["presets"]

    def test_delete_blank_is_noop(self):
        # The web UI posts a blank name when nothing is selected.
        assert delete_preset({"presets": {"p": values()}}, "") is False
        assert delete_preset({}, "") is False


class TestCustomPresets:
    def test_save_custom_preset(self):
        state = {}
        assert save_custom_preset(state, "raw run", "start_stack --vehicle_name truck-807") == "raw run"
        assert state["presets"]["raw run"] == {
            "kind": "command",
            "command": "start_stack --vehicle_name truck-807",
        }

    def test_save_custom_preset_blank_rejected(self):
        state = {}
        assert save_custom_preset(state, "name", "") is None
        assert save_custom_preset(state, "", "some command") is None
        assert save_custom_preset(state, "   ", "some command") is None
        assert state == {}

    def test_preset_kind_defaults_to_values(self):
        # Presets saved before custom presets existed carry no "kind".
        assert preset_kind({"vehicle_name": "truck-807"}) == "values"
        assert preset_kind({}) == "values"
        assert preset_kind("not a dict") == "values"
        assert preset_kind({"kind": "command", "command": "x"}) == "command"


class TestNormalizeCustomCommand:
    def test_strips_leading_shell_prompt(self):
        assert normalize_custom_command("$ start_stack --flag") == "start_stack --flag"
        assert normalize_custom_command("# start_stack --flag") == "start_stack --flag"

    def test_collapses_line_continuations(self):
        pasted = "start_stack \\\n  --vehicle_name truck-807 \\\n  --launch_config cfg"
        assert normalize_custom_command(pasted) == (
            "start_stack --vehicle_name truck-807 --launch_config cfg"
        )

    def test_removes_stray_backslashes(self):
        assert normalize_custom_command("cmd \\ flag") == "cmd flag"
        assert normalize_custom_command("cmd \\") == "cmd"

    def test_collapses_whitespace_runs(self):
        assert normalize_custom_command("  cmd    --flag\t--x  ") == "cmd --flag --x"

    def test_blank_stays_blank(self):
        assert normalize_custom_command("") == ""
        assert normalize_custom_command("   ") == ""
        assert normalize_custom_command(None) == ""


class TestVehicleFromCommand:
    def test_space_form(self):
        assert vehicle_from_command("start_stack --vehicle_name truck-807 --flag") == "truck-807"

    def test_equals_form(self):
        assert vehicle_from_command("start_stack --vehicle_name=truck-42") == "truck-42"

    def test_missing_is_blank(self):
        assert vehicle_from_command("start_stack --flag") == ""
        assert vehicle_from_command("") == ""


class TestCommandEntryValues:
    def test_only_vehicle_is_derived(self):
        values = command_entry_values("start_stack --vehicle_name truck-807 --flag")
        assert values == {
            "vehicle_name": "truck-807",
            "launch_config": "",
            "route": "",
            "enable_japan_driving": False,
        }


class TestRememberCommandCustom:
    def test_custom_flag_recorded(self):
        state = {}
        entry = remember_command(state, command_entry_values("start_stack --vehicle_name t-1"), "cmd", custom=True)
        assert entry["custom"] is True

    def test_regular_build_not_marked_custom(self):
        state = {}
        entry = remember_command(state, values(), "cmd")
        assert entry["custom"] is False


class TestCommandValues:
    def test_defaults_for_missing_fields(self):
        assert command_values({}) == {
            "vehicle_name": "",
            "launch_config": "",
            "route": "",
            "enable_japan_driving": False,
        }

    def test_extra_keys_ignored(self):
        # Presets/history saved before map_key was removed still load fine.
        values = command_values({"vehicle_name": "truck-807", "map_key": "usa_zone_10"})
        assert values["vehicle_name"] == "truck-807"
        assert "map_key" not in values

    def test_coerces_japan_driving_to_bool(self):
        assert command_values({"enable_japan_driving": "yes"})["enable_japan_driving"] is True
        assert command_values({"enable_japan_driving": ""})["enable_japan_driving"] is False
