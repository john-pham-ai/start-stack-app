import os

import pytest
from questionary import Choice

import launch
from stack_options import Option
from launch import (
    NEW,
    QUIT,
    RECORD_ONLY,
    LoadedCommand,
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

    def test_custom_entry_falls_back_to_command(self):
        summary = summarize_entry({"vehicle_name": "", "launch_config": "", "command": "start_stack --flag"})
        assert summary == "start_stack --flag"

    def test_custom_entry_command_truncated(self):
        command = "start_stack " + "--flag " * 20
        summary = summarize_entry({"command": command})
        assert len(summary) == 58  # 57 chars + the ellipsis
        assert summary.endswith("…")

    def test_vehicle_still_wins_for_custom_rows(self):
        # A custom command carrying --vehicle_name summarizes like any other.
        summary = summarize_entry(
            {"vehicle_name": "truck-807", "launch_config": "", "command": "cmd"}
        )
        assert summary == "truck-807"


class TestCustomPresets:
    CUSTOM = {"kind": "command", "command": "start_stack --vehicle_name truck-807"}

    def test_menu_labels_custom_presets(self, monkeypatch):
        captured = {}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                captured["titles"] = [c.title for c in choices]

            def ask(_):
                return None

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        state = {"presets": {"raw run": self.CUSTOM}}
        ask_start_menu(state, "en")
        assert "Preset: raw run (custom)" in captured["titles"]
        assert "Save a custom command as a preset" in captured["titles"]

    def test_loading_custom_preset_returns_command(self, monkeypatch):
        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.choices = choices

            def ask(self):
                by_title = {c.title: c.value for c in self.choices}
                return by_title["Preset: raw run (custom)"]

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        loaded = ask_start_menu({"presets": {"raw run": self.CUSTOM}}, "en")
        assert isinstance(loaded, LoadedCommand)
        assert loaded.name == "raw run"
        assert loaded.command == "start_stack --vehicle_name truck-807"

    def test_loading_custom_history_row_returns_command(self, monkeypatch):
        entry = {
            "built_at": "2026-09-14T21:00:00",
            "command": "start_stack --vehicle_name truck-807",
            "custom": True,
            "vehicle_name": "truck-807",
            "launch_config": "",
            "route": "",
            "enable_japan_driving": False,
        }

        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.choices = choices

            def ask(self):
                by_title = {c.title: c.value for c in self.choices}
                return by_title["Recent: truck-807"]

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        loaded = ask_start_menu({"history": [entry]}, "en")
        assert isinstance(loaded, LoadedCommand)
        assert loaded.command == "start_stack --vehicle_name truck-807"

    def test_old_shaped_presets_still_load_as_values(self, monkeypatch):
        old_preset = {"vehicle_name": "truck-807", "launch_config": "cfg", "route": "", "enable_japan_driving": False}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.choices = choices

            def ask(self):
                by_title = {c.title: c.value for c in self.choices}
                return by_title["Preset: legacy"]

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        loaded = ask_start_menu({"presets": {"legacy": old_preset}}, "en")
        assert not isinstance(loaded, LoadedCommand)
        assert loaded["vehicle_name"] == "truck-807"


class TestSaveCustomCommandPreset:
    @pytest.fixture(autouse=True)
    def no_disk_writes(self, monkeypatch):
        monkeypatch.setattr(launch, "save_state", lambda state: None)

    def test_saves_normalized_command(self, monkeypatch, capsys):
        typed = [
            "$ start_stack \\\n  --vehicle_name truck-999 --launch_config cfg",  # the command
            "raw run",  # the name
        ]
        monkeypatch.setattr(
            launch.questionary,
            "text",
            lambda message: type("P", (), {"ask": lambda s: typed.pop(0)})(),
        )
        state = {}
        launch.save_custom_command_preset(state, "en")
        assert state["presets"]["raw run"]["command"] == (
            "start_stack --vehicle_name truck-999 --launch_config cfg"
        )
        assert state["presets"]["raw run"]["kind"] == "command"
        assert "Preset saved: raw run" in capsys.readouterr().out

    def test_blank_command_aborts_without_name_prompt(self, monkeypatch):
        prompts = []
        monkeypatch.setattr(
            launch.questionary,
            "text",
            lambda message: type("P", (), {"ask": lambda s: prompts.append(message) or ""})(),
        )
        state = {}
        launch.save_custom_command_preset(state, "en")
        # Only the command prompt happened; the name was never asked.
        assert len(prompts) == 1
        assert state == {}


class TestRunCustomCommand:
    def test_prints_copies_records_done(self, monkeypatch, capsys):
        import recorder

        flow_calls = []

        def no_flow(*args, **kwargs):
            flow_calls.append((args, kwargs))

        monkeypatch.setattr(recorder, "run_recording_flow", no_flow)
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        monkeypatch.setattr(launch, "save_state", lambda state: None)

        state = {}
        launch.run_custom_command(
            state, "ja", LoadedCommand("raw run", "start_stack --vehicle_name truck-807 --launch_config cfg")
        )
        out = capsys.readouterr().out
        assert "start_stack --vehicle_name truck-807 --launch_config cfg" in out
        assert "（クリップボードにコピーしました）" in out
        # Pure re-grab: no recording offer follows the copy.
        assert flow_calls == []
        # History: custom flag on, vehicle derived from the command.
        entry = state["history"][0]
        assert entry["custom"] is True
        assert entry["vehicle_name"] == "truck-807"

    def test_command_without_vehicle_still_works(self, monkeypatch, capsys):
        import recorder

        monkeypatch.setattr(recorder, "run_recording_flow", lambda *a, **kw: None)
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        monkeypatch.setattr(launch, "save_state", lambda state: None)

        launch.run_custom_command({}, "en", LoadedCommand("n", "my_tool --flag"))
        assert "my_tool --flag" in capsys.readouterr().out


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

    def test_remove_preset_loops_back_to_menu(self, monkeypatch, capsys):
        """Removing a preset from the menu returns to the menu afterwards."""
        import recorder

        menu_answers = [launch.REMOVE_PRESET, launch.NEW]
        wizard_answers = {
            "Language / 言語": "en",
            "launch_config": "sds_road_readiness",
            "route (optional)": "",
            "enable_japan_driving": False,
        }
        removed = []

        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.message = message

            def ask(self):
                if self.message == "What do you want to do?":
                    return menu_answers.pop(0)
                return wizard_answers[self.message]

        class FakeAutocomplete:
            def __init__(self, message, choices=None, default="", validate=None):
                pass

            def ask(self):
                return "812"

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        monkeypatch.setattr(launch.questionary, "autocomplete", FakeAutocomplete)
        monkeypatch.setattr(launch.questionary, "confirm", lambda *a, **k: type("A", (), {"ask": lambda s: False})())
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        monkeypatch.setattr(recorder, "run_recording_flow", lambda lang, state, **kw: None)
        monkeypatch.setattr(launch, "remove_preset", lambda state, lang: removed.append(lang))

        launch.main()

        # Remove was invoked, then the menu was shown again and the wizard
        # ran to a completed command.
        assert removed == ["en"]
        assert menu_answers == []
        assert "--vehicle_name truck-812" in capsys.readouterr().out

    def test_custom_preset_load_end_to_end(self, monkeypatch, capsys):
        """A custom preset from the menu: printed, copied, done — that's it."""
        import json

        import recorder
        import state as state_module

        with open(state_module.STATE_PATH, "w") as f:
            json.dump(
                {
                    "presets": {
                        "raw run": {
                            "kind": "command",
                            "command": "start_stack --vehicle_name truck-815",
                        }
                    }
                },
                f,
            )

        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.message = message
                self.choices = choices

            def ask(self):
                if self.message == "Language / 言語":
                    return "en"
                by_title = {c.title: c.value for c in self.choices}
                return by_title["Preset: raw run (custom)"]

        flow_calls = []
        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        monkeypatch.setattr(
            recorder, "run_recording_flow", lambda *a, **kw: flow_calls.append(kw)
        )

        launch.main()

        out = capsys.readouterr().out
        assert "start_stack --vehicle_name truck-815" in out
        assert "(copied to clipboard)" in out
        # Pure re-grab: no recording offer after a preset pick.
        assert flow_calls == []
        with open(state_module.STATE_PATH) as f:
            state = json.load(f)
        assert state["history"][0]["custom"] is True
        assert state["history"][0]["vehicle_name"] == "truck-815"

    def test_values_preset_load_end_to_end(self, monkeypatch, capsys):
        """A values preset from the menu: built, copied, done — no wizard
        steps, no recording offer."""
        import json

        import recorder
        import state as state_module

        with open(state_module.STATE_PATH, "w") as f:
            json.dump(
                {
                    "presets": {
                        "night loop": {
                            "vehicle_name": "truck-815",
                            "launch_config": "sds_road_readiness",
                            "route": "",
                            "enable_japan_driving": False,
                        }
                    }
                },
                f,
            )

        wizard_prompts = []

        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.message = message
                self.choices = choices

            def ask(self):
                if self.message == "Language / 言語":
                    return "en"
                if self.message == "What do you want to do?":
                    by_title = {c.title: c.value for c in self.choices}
                    return by_title["Preset: night loop"]
                wizard_prompts.append(self.message)  # no step should be asked
                raise AssertionError(f"unexpected wizard prompt: {self.message}")

        flow_calls = []
        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        monkeypatch.setattr(
            recorder, "run_recording_flow", lambda *a, **kw: flow_calls.append(kw)
        )

        launch.main()

        out = capsys.readouterr().out
        assert "--vehicle_name truck-815" in out
        assert "--launch_config sds_road_readiness" in out
        assert "(copied to clipboard)" in out
        assert "Record the screen" not in out
        assert flow_calls == []
        with open(state_module.STATE_PATH) as f:
            state = json.load(f)
        assert state["history"][0]["command"].startswith("start_stack")
        assert state["history"][0]["custom"] is False

    def test_save_custom_loops_back_to_menu(self, monkeypatch, capsys):
        """Saving a custom preset from the menu returns to the menu."""
        import recorder

        menu_answers = [launch.SAVE_CUSTOM, launch.NEW]
        wizard_answers = {
            "Language / 言語": "en",
            "launch_config": "sds_road_readiness",
            "route (optional)": "",
            "enable_japan_driving": False,
        }
        saved = []

        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.message = message

            def ask(self):
                if self.message == "What do you want to do?":
                    return menu_answers.pop(0)
                return wizard_answers[self.message]

        class FakeAutocomplete:
            def __init__(self, message, choices=None, default="", validate=None):
                pass

            def ask(self):
                return "812"

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        monkeypatch.setattr(launch.questionary, "autocomplete", FakeAutocomplete)
        monkeypatch.setattr(launch.questionary, "confirm", lambda *a, **k: type("A", (), {"ask": lambda s: False})())
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        monkeypatch.setattr(recorder, "run_recording_flow", lambda lang, state, **kw: None)
        monkeypatch.setattr(launch, "save_custom_command_preset", lambda state, lang: saved.append(lang))

        launch.main()

        assert saved == ["en"]
        assert menu_answers == []
        assert "--vehicle_name truck-812" in capsys.readouterr().out

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
        # Even with nothing saved, the menu appears — with record-only and
        # save-custom on it (but no remove-preset entry without presets).
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
            "Save a custom command as a preset",
            "Quit",
        ]

    def test_remove_entry_with_presets(self, monkeypatch):
        captured = {}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                captured["titles"] = [c.title for c in choices]

            def ask(_):
                return None

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        state = {"presets": {"night loop": {}}, "history": [{"vehicle_name": "t", "launch_config": "c"}]}
        ask_start_menu(state, "en")
        assert captured["titles"] == [
            "Build a new command",
            "Record the screen only",
            "Save a custom command as a preset",
            "Preset: night loop",
            "Recent: t · c",
            "Remove a preset",
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

    def test_remove_preset_entry(self, monkeypatch):
        class FakeSelect:
            def __init__(self, message, choices=None, default=None):
                self.choices = choices

            def ask(self):
                by_title = {c.title: c.value for c in self.choices}
                return by_title["Remove a preset"]

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        assert ask_start_menu({"presets": {"p": {}}}, "en") is launch.REMOVE_PRESET


class TestRemovePreset:
    @pytest.fixture(autouse=True)
    def no_disk_writes(self, monkeypatch):
        # remove_preset saves right away; keep it off the real state file.
        monkeypatch.setattr(launch, "save_state", lambda state: None)

    def _select(self, monkeypatch, picked, confirmed):
        monkeypatch.setattr(
            launch.questionary,
            "select",
            lambda message, choices=None: type(
                "P", (), {"ask": lambda s: picked}
            )(),
        )
        monkeypatch.setattr(
            launch.questionary,
            "confirm",
            lambda message, default=False: type(
                "P", (), {"ask": lambda s: confirmed}
            )(),
        )

    def test_removes_when_confirmed(self, monkeypatch, capsys):
        self._select(monkeypatch, picked="night loop", confirmed=True)
        state = {"presets": {"night loop": {"route": "a"}, "keep": {"route": "b"}}}
        launch.remove_preset(state, "en")
        assert list(state["presets"]) == ["keep"]
        out = capsys.readouterr().out
        assert "Preset removed: night loop" in out

    def test_confirm_declined_keeps_preset(self, monkeypatch, capsys):
        self._select(monkeypatch, picked="night loop", confirmed=False)
        state = {"presets": {"night loop": {"route": "a"}}}
        launch.remove_preset(state, "en")
        assert "night loop" in state["presets"]
        assert "removed" not in capsys.readouterr().out

    def test_back_keeps_preset(self, monkeypatch, capsys):
        self._select(monkeypatch, picked=launch.BACK, confirmed=False)
        state = {"presets": {"night loop": {"route": "a"}}}
        launch.remove_preset(state, "en")
        assert "night loop" in state["presets"]
        # The confirm prompt is never reached after Back.
        assert "Remove preset" not in capsys.readouterr().out

    def test_no_presets_is_a_noop(self, monkeypatch, capsys):
        calls = []
        monkeypatch.setattr(
            launch.questionary, "select", lambda *a, **k: calls.append(a) or None
        )
        launch.remove_preset({}, "en")
        assert calls == []
        assert capsys.readouterr().out == ""
