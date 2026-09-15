import os

import pytest
from questionary import Choice

import launch
from stack_options import Option
from launch import (
    NEW,
    QUIT,
    RECORD_ONLY,
    ask_start_menu,
    choices_for,
    pin_first,
    safe_default,
    summarize_entry,
    validated,
)


def make_options():
    return {
        "vehicle_name": [Option("truck-807", "truck-807", "", "")],
        "launch_config": [
            Option("sds_road_readiness", "sds_road_readiness", "", ""),
            Option("mrm_arbiter_integration_test", "mrm_arbiter_integration_test", "", ""),
        ],
        "route": [
            Option("shoreline_straight", "shoreline_straight", "usa_zone_10", ""),
            Option("jp_loop", "jp_loop", "jp_zone_53", ""),
        ],
    }


class TestPinFirst:
    def test_pins_in_order_at_front(self):
        opts = [Option("a", "a", "", ""), Option("b", "b", "", ""), Option("c", "c", "", "")]
        assert [o.value for o in pin_first(opts, ["c", "a"])] == ["c", "a", "b"]

    def test_missing_pins_ignored(self):
        opts = [Option("a", "a", "", "")]
        assert [o.value for o in pin_first(opts, ["zzz"])] == ["a"]


class TestSafeDefault:
    def test_valid_remembered_value(self):
        choices = [Choice("A", "a"), Choice("B", "b")]
        assert safe_default("b", choices) == "b"

    def test_stale_remembered_value_dropped(self):
        choices = [Choice("A", "a")]
        assert safe_default("zzz", choices) is None


class TestChoicesFor:
    def test_optional_prepends_none(self):
        result = choices_for({"x": [Option("a", "A", "", "")]}, "x", optional=True, none_label="none")
        assert result[0].title == "none"
        assert result[1].title == "A"

    def test_labels_win_over_values(self):
        result = choices_for({"x": [Option("a", "Pretty A", "", "")]}, "x")
        assert result[0].title == "Pretty A"
        assert result[0].value == "a"


class TestSummarizeEntry:
    def test_vehicle_config_and_route(self):
        assert (
            summarize_entry(
                {"vehicle_name": "truck-807", "launch_config": "cfg", "route": "r1"}
            )
            == "truck-807 · cfg · r1"
        )

    def test_no_route_omitted(self):
        assert summarize_entry({"vehicle_name": "t", "launch_config": "c"}) == "t · c"


class TestValidated:
    def test_valid_values_pass_through(self):
        options = make_options()
        values = {
            "vehicle_name": "truck-807",
            "launch_config": "sds_road_readiness",
            "route": "shoreline_straight",
            "enable_japan_driving": True,
        }
        out, dropped = validated(values, options)
        assert dropped == []
        assert out == values

    def test_stale_launch_config_falls_back_to_first(self):
        options = make_options()
        out, dropped = validated({"launch_config": "gone_forever", "route": ""}, options)
        assert out["launch_config"] == "sds_road_readiness"
        assert dropped == ["gone_forever"]

    def test_stale_route_dropped(self):
        options = make_options()
        out, dropped = validated({"route": "rift"}, options)
        assert out["route"] == ""
        assert dropped == ["rift"]

    def test_route_from_other_map_still_valid(self):
        # With no map picker, any live route is a valid route.
        options = make_options()
        out, dropped = validated({"route": "jp_loop"}, options)
        assert dropped == []
        assert out["route"] == "jp_loop"

    def test_vehicle_name_never_validated(self):
        options = make_options()
        out, _ = validated({"vehicle_name": "truck-999", "launch_config": ""}, options)
        assert out["vehicle_name"] == "truck-999"

    def test_japan_driving_coerced_to_bool(self):
        options = make_options()
        out, _ = validated({"enable_japan_driving": "yes"}, options)
        assert out["enable_japan_driving"] is True


class TestWizardEndToEnd:
    """Drive main() start to finish with mocked prompts and no recording."""

    @pytest.fixture(autouse=True)
    def isolated_state(self, tmp_path, monkeypatch):
        import state as state_module

        path = tmp_path / "state.json"
        monkeypatch.setattr(state_module, "STATE_PATH", str(path))
        monkeypatch.setenv("BRAIN2_REPO_PATH", "/nonexistent-brain2")
        return path

    def test_full_walkthrough_builds_and_remembers(self, monkeypatch, capsys):
        import json

        import recorder
        import state as state_module

        # No map_key step left in the wizard.
        assert "map_key" not in launch.STEPS

        answers = {
            "Language / 言語": "en",
            "What do you want to do?": NEW,
            "launch_config": "sds_road_readiness",
            "route (optional)": "shoreline_straight",
            "enable_japan_driving": False,
        }

        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.message = message

            def ask(self):
                return answers[self.message]

        class FakeAutocomplete:
            def __init__(self, message, choices=None, default="", validate=None):
                self.default = default

            def ask(self):
                return "812"

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        monkeypatch.setattr(launch.questionary, "autocomplete", FakeAutocomplete)
        monkeypatch.setattr(launch.questionary, "confirm", lambda *a, **k: type("A", (), {"ask": lambda s: False})())
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        monkeypatch.setattr(
            recorder, "run_recording_flow", lambda lang, state, **kw: None
        )

        launch.main()

        out = capsys.readouterr().out
        assert "--vehicle_name truck-812" in out
        assert "--route shoreline_straight" in out
        assert "--map_key" not in out

        with open(state_module.STATE_PATH) as f:
            state = json.load(f)
        assert state["vehicle_number"] == "812"
        assert state["launch_config"]["en"] == "sds_road_readiness"
        assert state["history"][0]["command"].startswith("start_stack")
        assert "map_key" not in state["history"][0]

    def test_record_only_menu_entry(self, monkeypatch, capsys):
        import recorder
        import state as state_module

        calls = {}

        answers = {
            "Language / 言語": "ja",
            "何をしますか？": launch.RECORD_ONLY,
        }

        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.message = message

            def ask(self):
                return answers[self.message]

        def fake_flow(lang, state, vehicle_name="", metadata=None):
            calls["lang"] = lang
            calls["vehicle_name"] = vehicle_name

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        monkeypatch.setattr(recorder, "run_recording_flow", fake_flow)

        launch.main()

        # Straight into recording, in the picked language, no command built.
        assert calls == {"lang": "ja", "vehicle_name": ""}
        out = capsys.readouterr().out
        assert "--vehicle_name" not in out
        # And no history was written for a record-only run.
        assert not os.path.exists(state_module.STATE_PATH)


class TestAskStartMenu:
    def test_menu_always_shown(self, monkeypatch):
        # Even with nothing saved, the menu appears — with record-only on it.
        captured = {}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                captured["titles"] = [c.title for c in choices]

            def ask(_):
                return None  # Ctrl-C

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        assert ask_start_menu({}, "en") is QUIT
        assert captured["titles"] == [
            "Build a new command",
            "Record the screen only",
            "Quit",
        ]

    def test_quit(self, monkeypatch):
        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                pass

            def ask(_):
                return None  # Ctrl-C

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        assert ask_start_menu({"presets": {"p": {}}}, "en") is QUIT

    def test_record_only(self, monkeypatch):
        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.choices = choices

            def ask(self):
                by_title = {c.title: c.value for c in self.choices}
                return by_title["Record the screen only"]

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        assert ask_start_menu({}, "en") is RECORD_ONLY

    def test_preset_choice_loads_values(self, monkeypatch):
        preset = {
            "vehicle_name": "truck-807",
            "launch_config": "sds_road_readiness",
            "route": "shoreline_straight",
            "enable_japan_driving": False,
        }
        state = {"presets": {"night loop": preset}}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.choices = choices

            def ask(self):
                by_title = {c.title: c.value for c in self.choices}
                return by_title["Preset: night loop"]

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        loaded = ask_start_menu(state, "en")
        assert loaded["vehicle_name"] == "truck-807"
        assert loaded["route"] == "shoreline_straight"

    def test_history_choice_loads_values(self, monkeypatch):
        state = {"history": [{"vehicle_name": "truck-801", "launch_config": "cfg", "route": ""}]}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.choices = choices

            def ask(self):
                by_title = {c.title: c.value for c in self.choices}
                return by_title["Recent: truck-801 · cfg"]

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        loaded = ask_start_menu(state, "en")
        assert loaded["vehicle_name"] == "truck-801"
        assert loaded["enable_japan_driving"] is False

    def test_start_new_returns_new(self, monkeypatch):
        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.choices = choices

            def ask(self):
                by_title = {c.title: c.value for c in self.choices}
                return by_title["Build a new command"]

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        assert ask_start_menu({"presets": {"p": {}}}, "en") is NEW
