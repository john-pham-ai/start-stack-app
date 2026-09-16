import json
import os

import pytest
from questionary import Choice

import launch
import shared_presets
from state import command_values
from stack_options import Option
from launch import (
    BACK,
    NEW,
    QUIT,
    RECORD_ONLY,
    BUILD_LOOP,
    LoadedCommand,
    ask_route,
    ask_start_menu,
    choices_for,
    pin_first,
    route_choices_for,
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


class TestRouteChoicesFor:
    def test_map_named_in_title(self):
        # Both UIs search on the title as you type, so the map in the
        # title lets typing a map name narrow the list.
        options = make_options()
        choices = route_choices_for(options, none_label="none")
        assert choices[0].title == "none"
        assert choices[0].value == ""
        assert choices[1].title == "usa_zone_10 — shoreline_straight"
        assert choices[1].value == "shoreline_straight"
        assert choices[2].title == "jp_zone_53 — jp_loop"
        assert choices[2].value == "jp_loop"

    def test_ownerless_route_stays_bare(self):
        options = {"route": [Option("x", "X", "", "")]}
        assert route_choices_for(options)[1].title == "X"


class TestAskRoute:
    """ask_route: the route step as a type-to-autofill prompt."""

    def ask_with(self, monkeypatch, answer):
        """Mock autocomplete; returns the prompt instance ask_route built."""
        created = []

        class FakeAutocomplete:
            def __init__(self, message, choices=None, default="", validate=None, **kwargs):
                self.message = message
                self.choices = choices
                self.validate = validate
                self.kwargs = kwargs
                created.append(self)

            def ask(self):
                return answer

        monkeypatch.setattr(launch.questionary, "autocomplete", FakeAutocomplete)
        return created

    def test_suggestions_carry_map_titled_entries(self, monkeypatch):
        created = self.ask_with(monkeypatch, "")
        ask_route("en", make_options(), none_label="-- none --")
        prompt = created[0]
        assert prompt.choices[0] == "-- none --"
        assert "usa_zone_10 — shoreline_straight" in prompt.choices
        assert "jp_zone_53 — jp_loop" in prompt.choices
        # The prompt says how to navigate, like the vehicle prompt does.
        assert "back" in prompt.message and "quit" in prompt.message

    def test_suggestion_title_resolves_to_value(self, monkeypatch):
        self.ask_with(monkeypatch, "usa_zone_10 — shoreline_straight")
        assert ask_route("en", make_options()) == "shoreline_straight"

    def test_typed_value_resolves(self, monkeypatch):
        self.ask_with(monkeypatch, "jp_loop")
        assert ask_route("en", make_options()) == "jp_loop"

    def test_typed_label_resolves_to_value(self, monkeypatch):
        options = {"route": [Option("v1", "Pretty Route", "m1", "")]}
        self.ask_with(monkeypatch, "Pretty Route")
        assert ask_route("en", options) == "v1"

    def test_blank_means_no_route(self, monkeypatch):
        self.ask_with(monkeypatch, "")
        assert ask_route("en", make_options()) == ""

    def test_none_suggestion_means_no_route(self, monkeypatch):
        self.ask_with(monkeypatch, "-- none --")
        assert ask_route("en", make_options(), none_label="-- none --") == ""

    def test_back_and_quit_keywords(self, monkeypatch):
        self.ask_with(monkeypatch, "back")
        assert ask_route("en", make_options()) is BACK
        self.ask_with(monkeypatch, "quit")
        assert ask_route("en", make_options()) is QUIT

    def test_ctrl_c_or_eof_returns_quit(self, monkeypatch):
        self.ask_with(monkeypatch, None)
        assert ask_route("en", make_options()) is QUIT

    def test_easy_on_the_eyes_styling(self, monkeypatch):
        # The prompt gets the toned-down style and doesn't nag while typing
        # (partial text is never a full route, so a red bar per keystroke
        # was just noise).
        created = self.ask_with(monkeypatch, "")
        ask_route("en", make_options())
        kwargs = created[0].kwargs
        assert kwargs["style"] is launch.AUTOCOMPLETE_STYLE
        assert kwargs["validate_while_typing"] is False
        rules = dict(launch.AUTOCOMPLETE_STYLE.style_rules)
        assert "completion-menu" in rules  # the menu itself is restyled
        assert "noreverse" in rules["completion-menu.completion.current selected"]

    def test_extra_valid_keyword_accepted(self, monkeypatch):
        # The loop stop picker accepts a typed 'done'; resolution runs
        # first, so a real route named "done" would still win.
        self.ask_with(monkeypatch, "done")
        assert ask_route("en", make_options(), extra_valid=("done",)) == "done"

    def test_extra_valid_keyword_case_insensitive(self, monkeypatch):
        self.ask_with(monkeypatch, "DONE")
        assert ask_route("en", make_options(), extra_valid=("done",)) == "done"

    def test_extra_keyword_rejected_without_the_parameter(self, monkeypatch):
        # Validation refuses 'done' when the caller didn't opt in — a
        # mistyped wizard answer must not silently become a keyword.
        created = self.ask_with(monkeypatch, "done")
        ask_route("en", make_options(), extra_valid=("done",))
        assert created[0].validate("done") is True
        created = self.ask_with(monkeypatch, "done")
        ask_route("en", make_options())
        assert created[0].validate("done") is not True

    def test_extra_keyword_does_not_shadow_a_real_route(self, monkeypatch):
        # A route whose label is literally "done" resolves first, so the
        # keyword can never steal it.
        options = {"route": [Option("done_circuit", "done", "", "")]}
        self.ask_with(monkeypatch, "done")
        assert ask_route("en", options, extra_valid=("done",)) == "done_circuit"

    def test_message_override_used_verbatim(self, monkeypatch):
        created = self.ask_with(monkeypatch, "")
        ask_route("en", make_options(), message="Stop 1 — pick a route")
        assert "Stop 1 — pick a route" in created[0].message
        created = self.ask_with(monkeypatch, "")
        ask_route("en", make_options())
        assert "route" in created[0].message.lower()

    def test_validate_accepts_known_and_rejects_unknown(self, monkeypatch):
        created = self.ask_with(monkeypatch, "")
        ask_route("en", make_options(), none_label="-- none --")
        validate = created[0].validate
        # Everything the prompt should let through...
        assert validate("") is True
        assert validate("  ") is True
        assert validate("usa_zone_10 — shoreline_straight") is True
        assert validate("shoreline_straight") is True
        assert validate("back") is True
        assert validate("QUIT") is True
        # ...and what it must not.
        assert validate("rift") is not True


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
            def __init__(self, message, choices=None, default=None, **kwargs):
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
            def __init__(self, message, choices=None, default=None, **kwargs):
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
            def __init__(self, message, choices=None, default=None, **kwargs):
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
            def __init__(self, message, choices=None, default=None, **kwargs):
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
    def test_prints_copies_then_offers_recording(self, monkeypatch, capsys):
        import recorder

        flow_calls = []

        def fake_flow(*args, **kwargs):
            flow_calls.append((args, kwargs))

        monkeypatch.setattr(recorder, "run_recording_flow", fake_flow)
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        monkeypatch.setattr(launch, "save_state", lambda state: None)

        state = {}
        launch.run_custom_command(
            state, "ja", LoadedCommand("raw run", "start_stack --vehicle_name truck-807 --launch_config cfg")
        )
        out = capsys.readouterr().out
        assert "start_stack --vehicle_name truck-807 --launch_config cfg" in out
        assert "（クリップボードにコピーしました）" in out
        # The reuse now offers the same recording flow as a hand-built
        # command; the vehicle comes from the command itself.
        assert len(flow_calls) == 1
        args, kwargs = flow_calls[0]
        assert args[0] == "ja"
        assert kwargs["vehicle_name"] == "truck-807"
        assert kwargs["metadata"] == {"command": "start_stack --vehicle_name truck-807 --launch_config cfg"}
        # History: custom flag on, vehicle derived from the command.
        entry = state["history"][0]
        assert entry["custom"] is True
        assert entry["vehicle_name"] == "truck-807"

    def test_command_without_vehicle_passes_empty_vehicle(self, monkeypatch, capsys):
        import recorder

        flow_calls = []
        monkeypatch.setattr(
            recorder, "run_recording_flow", lambda *a, **kw: flow_calls.append(kw)
        )
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        monkeypatch.setattr(launch, "save_state", lambda state: None)

        launch.run_custom_command({}, "en", LoadedCommand("n", "my_tool --flag"))
        out = capsys.readouterr().out
        assert "my_tool --flag" in out
        assert flow_calls == [{"vehicle_name": "", "metadata": {"command": "my_tool --flag"}}]

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
            "launch_config": "sds_road_readiness",
            "enable_japan_driving": False,
        }
        # The menu is asked again once the command flow finishes — the app
        # returns there instead of exiting now — and only Quit ends it.
        menu_answers = [NEW, QUIT]

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                self.message = message

            def ask(self):
                if self.message == "What do you want to do?":
                    return menu_answers.pop(0)
                return answers[self.message]

        class FakeAutocomplete:
            def __init__(self, message, choices=None, default="", validate=None, **kwargs):
                self.message = message

            def ask(self):
                # The vehicle prompt answers a number; the route prompt
                # answers a suggestion title, which resolves to its value.
                # (The CSV's shoreline_straight lives on shoreline_zone_10.)
                if "route" in self.message:
                    return "shoreline_zone_10 — shoreline_straight"
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

        menu_answers = [launch.REMOVE_PRESET, launch.NEW, launch.QUIT]
        wizard_answers = {
            "Language / 言語": "en",
            "launch_config": "sds_road_readiness",
            "enable_japan_driving": False,
        }
        removed = []

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                self.message = message

            def ask(self):
                if self.message == "What do you want to do?":
                    return menu_answers.pop(0)
                return wizard_answers[self.message]

        class FakeAutocomplete:
            def __init__(self, message, choices=None, default="", validate=None, **kwargs):
                self.message = message

            def ask(self):
                return "" if "route" in self.message else "812"

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

        menu_asks = {"count": 0}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                self.message = message
                self.choices = choices

            def ask(self):
                if self.message == "Language / 言語":
                    return "en"
                by_title = {c.title: c.value for c in self.choices}
                if self.message == "What do you want to do?":
                    # A new instance is built per prompt, so the counter
                    # lives outside; the flow finishes back at the menu,
                    # and only Quit ends the app now.
                    menu_asks["count"] += 1
                    if menu_asks["count"] > 1:
                        return launch.QUIT
                    return by_title["Preset: raw run (custom)"]
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
        # The reuse now offers recording; the vehicle comes from the command.
        assert len(flow_calls) == 1
        assert flow_calls[0]["vehicle_name"] == "truck-815"
        assert flow_calls[0]["metadata"] == {"command": "start_stack --vehicle_name truck-815"}
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
        menu_asks = {"count": 0}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                self.message = message
                self.choices = choices

            def ask(self):
                if self.message == "Language / 言語":
                    return "en"
                if self.message == "What do you want to do?":
                    by_title = {c.title: c.value for c in self.choices}
                    # First ask loads the preset; after the flow the app is
                    # back at the menu, and Quit is the only exit. The
                    # counter lives outside — one instance per prompt.
                    menu_asks["count"] += 1
                    if menu_asks["count"] > 1:
                        return launch.QUIT
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
        assert "Record the screen" not in out  # the mocked flow prints nothing
        # A loaded values preset gets the same recording offer, with the
        # same metadata a hand-built command would carry.
        assert len(flow_calls) == 1
        assert flow_calls[0]["vehicle_name"] == "truck-815"
        assert flow_calls[0]["metadata"]["launch_config"] == "sds_road_readiness"
        assert flow_calls[0]["metadata"]["command"].startswith("start_stack")
        with open(state_module.STATE_PATH) as f:
            state = json.load(f)
        assert state["history"][0]["command"].startswith("start_stack")
        assert state["history"][0]["custom"] is False

    def test_save_custom_loops_back_to_menu(self, monkeypatch, capsys):
        """Saving a custom preset from the menu returns to the menu."""
        import recorder

        menu_answers = [launch.SAVE_CUSTOM, launch.NEW, launch.QUIT]
        wizard_answers = {
            "Language / 言語": "en",
            "launch_config": "sds_road_readiness",
            "enable_japan_driving": False,
        }
        saved = []

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                self.message = message

            def ask(self):
                if self.message == "What do you want to do?":
                    return menu_answers.pop(0)
                return wizard_answers[self.message]

        class FakeAutocomplete:
            def __init__(self, message, choices=None, default="", validate=None, **kwargs):
                self.message = message

            def ask(self):
                return "" if "route" in self.message else "812"

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


SHARED_VALUES = {
    "vehicle_name": "truck-807",
    "launch_config": "sds_road_readiness",
    "route": "shoreline_straight",
    "enable_japan_driving": False,
}


def seeded_shared_dir(tmp_path, name="repo route", **overrides):
    """A presets/ dir holding one shared preset, for monkeypatching in."""
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    (presets_dir / f"{name}.json").write_text(json.dumps(dict(SHARED_VALUES, **overrides)))
    return str(presets_dir)


class TestSharedPresetsMenu:
    def test_shared_listed_after_personal_with_tag_and_shortcut(self, monkeypatch, tmp_path):
        monkeypatch.setattr(shared_presets, "PRESETS_DIR", seeded_shared_dir(tmp_path))
        captured = {}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                captured["choices"] = choices

            def ask(_):
                return None

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        state = {"presets": {"mine": dict(SHARED_VALUES, route="jp_loop")}}
        ask_start_menu(state, "en")
        titles = [c.title for c in captured["choices"]]
        # Personal first, shared after, marked — and the ! @ shortcut run
        # continues across the merged list.
        assert "Preset: mine" in titles
        assert "Preset: repo route (shared)" in titles
        assert titles.index("Preset: mine") < titles.index("Preset: repo route (shared)")
        preset_keys = [c.shortcut_key for c in captured["choices"] if c.title.startswith("Preset:")]
        assert preset_keys == ["!", "@"]
        assert "Export a preset to share" in titles  # personal values preset exists

    def test_selecting_a_shared_preset_loads_its_values(self, monkeypatch, tmp_path):
        monkeypatch.setattr(shared_presets, "PRESETS_DIR", seeded_shared_dir(tmp_path))

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                self.choices = choices

            def ask(self):
                by_title = {c.title: c.value for c in self.choices}
                return by_title["Preset: repo route (shared)"]

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        values = ask_start_menu({}, "en")
        assert values == command_values(SHARED_VALUES)

    def test_broken_shared_files_noted_not_fatal(self, monkeypatch, tmp_path, capsys):
        presets_dir = tmp_path / "presets"
        presets_dir.mkdir()
        (presets_dir / "repo route.json").write_text(json.dumps(SHARED_VALUES))
        (presets_dir / "broken.json").write_text("{oops")
        monkeypatch.setattr(shared_presets, "PRESETS_DIR", str(presets_dir))

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                pass

            def ask(_):
                return None

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        assert ask_start_menu({}, "en") is QUIT
        out = capsys.readouterr().out
        assert "skipped 1 unreadable file" in out


class TestExportPresetFlow:
    def test_export_writes_the_share_file(self, monkeypatch, tmp_path, capsys):
        exports = str(tmp_path / "exports")
        monkeypatch.setattr(shared_presets, "EXPORTS_DIR", exports)

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                self.choices = choices

            def ask(self):
                by_title = {c.title: c.value for c in self.choices}
                return by_title["night loop"]

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        state = {"presets": {"night loop": dict(SHARED_VALUES)}}
        launch.export_preset_flow(state, "en")

        entry = json.loads((tmp_path / "exports" / "night loop.json").read_text())
        assert entry["route"] == "shoreline_straight"
        assert entry["kind"] == "values"
        out = capsys.readouterr().out
        assert "Exported 'night loop'" in out
        assert "Send that file to the repo owner" in out

    def test_only_values_presets_offered(self, monkeypatch, tmp_path):
        offered = []

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                offered.extend(c.title for c in choices if c.title not in ("<< Back",))

            def ask(_):
                return None  # back

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        state = {"presets": {
            "values one": dict(SHARED_VALUES),
            "raw run": {"kind": "command", "command": "start_stack --flag"},
        }}
        launch.export_preset_flow(state, "en")
        assert offered == ["values one"]

    def test_nothing_shareable_says_so(self, monkeypatch, capsys):
        state = {"presets": {"raw run": {"kind": "command", "command": "x"}}}
        launch.export_preset_flow(state, "en")
        assert "No shareable presets" in capsys.readouterr().out


class TestImportPresetFlow:
    @pytest.fixture(autouse=True)
    def isolated_state(self, tmp_path, monkeypatch):
        import state as state_module

        monkeypatch.setattr(state_module, "STATE_PATH", str(tmp_path / "state.json"))

    def test_import_saves_and_says(self, monkeypatch, tmp_path, capsys, isolated_state):
        path = tmp_path / "night loop.json"
        path.write_text(json.dumps(dict(SHARED_VALUES, kind="values", exported_by="jp")))

        class FakePath:
            def __init__(self, message, **kwargs):
                pass

            def ask(_):
                return str(path)

        monkeypatch.setattr(launch.questionary, "path", FakePath)
        state = {}
        launch.import_preset_flow(state, "en")
        assert state["presets"]["night loop"] == command_values(SHARED_VALUES)
        assert "Imported preset: night loop" in capsys.readouterr().out

    def test_bad_file_says_why(self, monkeypatch, tmp_path, capsys):
        path = tmp_path / "bad.json"
        path.write_text("{oops")

        class FakePath:
            def __init__(self, message, **kwargs):
                pass

            def ask(_):
                return str(path)

        monkeypatch.setattr(launch.questionary, "path", FakePath)
        state = {}
        launch.import_preset_flow(state, "en")
        assert not state.get("presets")
        assert "Could not read a preset" in capsys.readouterr().out

    def test_existing_name_needs_confirm(self, monkeypatch, tmp_path, capsys):
        path = tmp_path / "night loop.json"
        path.write_text(json.dumps(SHARED_VALUES))
        monkeypatch.setattr(
            launch.questionary, "path",
            lambda message, **kw: type("P", (), {"ask": lambda s: str(path)})(),
        )
        confirm = []
        monkeypatch.setattr(
            launch.questionary, "confirm",
            lambda message, **kw: type(
                "C", (), {"ask": lambda s: confirm.append(message) or False}
            )(),
        )
        state = {"presets": {"night loop": dict(SHARED_VALUES, route="jp_loop")}}
        launch.import_preset_flow(state, "en")
        assert any("already exists" in m for m in confirm)
        # Declined: the existing preset is untouched.
        assert state["presets"]["night loop"]["route"] == "jp_loop"

        import recorder
        import state as state_module

        calls = {}

        answers = {
            "Language / 言語": "ja",
        }
        menu_answers = [launch.RECORD_ONLY, launch.QUIT]

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                self.message = message

            def ask(self):
                if self.message == "何をしますか？":
                    return menu_answers.pop(0)
                return answers[self.message]

        def fake_flow(lang, state, vehicle_name="", metadata=None):
            calls["lang"] = lang
            calls["vehicle_name"] = vehicle_name

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        monkeypatch.setattr(recorder, "run_recording_flow", fake_flow)

        launch.main()

        # Straight into recording, in the picked language, no command built —
        # then the menu again, because a finished flow no longer exits.
        assert calls == {"lang": "ja", "vehicle_name": ""}
        assert menu_answers == []
        out = capsys.readouterr().out
        assert "--vehicle_name" not in out
        assert "キャンセルしました。" in out  # the Quit that ended it
        # And no history was written for a record-only run.
        assert not os.path.exists(state_module.STATE_PATH)

    def test_kept_recording_returns_to_start_menu(self, monkeypatch, capsys):
        """The default after ANY finished flow is the menu, not an exit:
        a kept (not discarded) record-only run comes back here too."""
        import recorder

        menu_returns = [launch.RECORD_ONLY, launch.QUIT]
        monkeypatch.setattr(launch, "ask_start_menu", lambda state, lang: menu_returns.pop(0))
        monkeypatch.setattr(
            launch.questionary,
            "select",
            lambda message, choices=None, default=None: type("P", (), {"ask": lambda s: "en"})(),
        )
        monkeypatch.setattr(
            recorder, "run_recording_flow", lambda *a, **kw: ("/tmp/v.mp4", "/tmp/v.json")
        )

        launch.main()

        assert menu_returns == []  # the menu was shown again after the kept run
        assert "Cancelled." in capsys.readouterr().out

    def test_discarded_record_only_returns_to_start_menu(self, monkeypatch, capsys):
        """Discarding a record-only recording loops back to the start
        menu instead of exiting the app."""
        import recorder

        menu_returns = [launch.RECORD_ONLY, launch.QUIT]
        monkeypatch.setattr(launch, "ask_start_menu", lambda state, lang: menu_returns.pop(0))
        monkeypatch.setattr(
            launch.questionary,
            "select",
            lambda message, choices=None, default=None: type("P", (), {"ask": lambda s: "en"})(),
        )
        monkeypatch.setattr(recorder, "run_recording_flow", lambda *a, **kw: recorder.DISCARDED)

        launch.main()

        assert menu_returns == []  # the menu was shown again after the discard
        assert "Cancelled." in capsys.readouterr().out

    def test_discarded_command_recording_returns_to_start_menu(self, monkeypatch, capsys):
        """A discard at the end of a hand-built command also goes back to
        the start menu rather than exiting."""
        import recorder

        menu_answers = [launch.NEW, launch.QUIT]
        wizard_answers = {
            "Language / 言語": "en",
            "launch_config": "sds_road_readiness",
            "enable_japan_driving": False,
        }

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                self.message = message

            def ask(self):
                if self.message == "What do you want to do?":
                    return menu_answers.pop(0)
                return wizard_answers[self.message]

        class FakeAutocomplete:
            def __init__(self, message, choices=None, default="", validate=None, **kwargs):
                self.message = message

            def ask(self):
                return "" if "route" in self.message else "812"

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        monkeypatch.setattr(launch.questionary, "autocomplete", FakeAutocomplete)
        monkeypatch.setattr(launch.questionary, "confirm", lambda *a, **k: type("A", (), {"ask": lambda s: False})())
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        monkeypatch.setattr(recorder, "run_recording_flow", lambda lang, state, **kw: recorder.DISCARDED)

        launch.main()

        assert menu_answers == []  # NEW ran, then the menu showed again
        out = capsys.readouterr().out
        assert "--vehicle_name truck-812" in out
        assert "Cancelled." in out

    def test_discarded_custom_command_recording_returns_to_start_menu(self, monkeypatch, capsys):
        """A discard after a reused custom preset goes back to the menu too."""
        import recorder

        loaded = LoadedCommand("raw run", "start_stack --vehicle_name truck-807")
        menu_returns = [loaded, launch.QUIT]
        monkeypatch.setattr(launch, "ask_start_menu", lambda state, lang: menu_returns.pop(0))
        monkeypatch.setattr(
            launch.questionary,
            "select",
            lambda message, choices=None, default=None: type("P", (), {"ask": lambda s: "en"})(),
        )
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        monkeypatch.setattr(recorder, "run_recording_flow", lambda *a, **kw: recorder.DISCARDED)

        launch.main()

        assert menu_returns == []
        out = capsys.readouterr().out
        assert "start_stack --vehicle_name truck-807" in out
        assert "Cancelled." in out


class TestAskStartMenu:
    def test_menu_always_shown(self, monkeypatch):
        # Even with nothing saved, the menu appears — with record-only and
        # save-custom on it (but no remove-preset entry without presets).
        captured = {}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                captured["titles"] = [c.title for c in choices]

            def ask(_):
                return None  # Ctrl-C

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        assert ask_start_menu({}, "en") is QUIT
        assert captured["titles"] == [
            "Build a new command",
            "Record the screen only",
            "Fetch the latest Run ID from the truck",
            "Set up SSH for a truck (one-time per truck)",
            "Save a custom command as a preset",
            "Build a closed-loop mileage route (Japan)",
            "Import a preset file",
            "Quit",
        ]

    def test_remove_entry_with_presets(self, monkeypatch):
        captured = {}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                captured["titles"] = [c.title for c in choices]

            def ask(_):
                return None

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        state = {"presets": {"night loop": {}}, "history": [{"vehicle_name": "t", "launch_config": "c"}]}
        ask_start_menu(state, "en")
        assert captured["titles"] == [
            "Build a new command",
            "Record the screen only",
            "Fetch the latest Run ID from the truck",
            "Set up SSH for a truck (one-time per truck)",
            "Save a custom command as a preset",
            "Build a closed-loop mileage route (Japan)",
            "Preset: night loop",
            "Remove a preset",
            "Export a preset to share",
            "Import a preset file",
            "Recent: t · c",
            "Quit",
        ]

    def test_quit(self, monkeypatch):
        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                pass

            def ask(_):
                return None  # Ctrl-C

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        assert ask_start_menu({"presets": {"p": {}}}, "en") is QUIT

    def _menu_choices(self, monkeypatch, state):
        captured = {}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                captured["choices"] = choices
                captured["kwargs"] = kwargs

            def ask(_):
                return None

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        ask_start_menu(state, "en")
        return captured

    def test_shortcuts_assigned_by_group(self, monkeypatch):
        state = {
            "presets": {name: {} for name in ("one", "two", "three")},
            "loops": {"L1": {}, "L2": {}},
            "history": [{"vehicle_name": "t", "launch_config": "c"} for _ in range(3)],
        }
        captured = self._menu_choices(monkeypatch, state)
        by_key = {c.shortcut_key: c for c in captured["choices"] if c.shortcut_key}
        # Presets: the number-row symbols, in save order.
        assert by_key["!"].title == "Preset: one"
        assert by_key["@"].title == "Preset: two"
        assert by_key["#"].title == "Preset: three"
        # Japan loops: Q/W/E/R.
        assert by_key["q"].title.endswith("— L1")
        assert by_key["w"].title.endswith("— L2")
        # Recents (at the bottom): A/S/D/F.
        assert by_key["a"].title.startswith("Recent:")
        assert by_key["s"].title.startswith("Recent:")
        assert by_key["d"].title.startswith("Recent:")
        # The fixed entries carry no explicit key — questionary's own
        # auto-assign hands them 1, 2, 3... when the real prompt runs.
        assert launch.NEW in [c.value for c in captured["choices"] if c.shortcut_key is None]
        # And the prompt runs in shortcut mode with a hint.
        assert captured["kwargs"]["use_shortcuts"] is True
        assert "press a shortcut key" in captured["kwargs"]["instruction"]

    def test_recents_capped_at_four_and_on_the_bottom(self, monkeypatch):
        # History is stored newest-first; six runs in, the menu shows the
        # last four (t5 back to t2), nothing else, above Quit.
        state = {"history": [{"vehicle_name": f"t{5-i}", "launch_config": "c"} for i in range(6)]}
        captured = self._menu_choices(monkeypatch, state)
        titles = [c.title for c in captured["choices"]]
        recents = [c for c in captured["choices"] if c.title.startswith("Recent:")]
        # The last 4 runs only — newest first is get_history's order.
        assert [c.shortcut_key for c in recents] == ["a", "s", "d", "f"]
        assert len(recents) == 4
        # Recents sit below everything else, newest first, Quit last.
        assert titles[-5:] == [
            "Recent: t5 · c",
            "Recent: t4 · c",
            "Recent: t3 · c",
            "Recent: t2 · c",
            "Quit",
        ]

    def test_past_the_shortcut_pool_no_explicit_key(self, monkeypatch):
        # An 11th preset has no number-row symbol left; it gets no
        # explicit key (questionary's own auto-assign handles it).
        state = {"presets": {f"p{i}": {} for i in range(11)}}
        captured = self._menu_choices(monkeypatch, state)
        presets = [c for c in captured["choices"] if c.title.startswith("Preset:")]
        assert len(presets) == 11
        assert [c.shortcut_key for c in presets[:10]] == list(launch.PRESET_SHORTCUTS)
        assert presets[10].shortcut_key is None
        # All explicit shortcut keys are unique across the whole menu.
        all_keys = [c.shortcut_key for c in captured["choices"] if c.shortcut_key]
        assert len(all_keys) == len(set(all_keys))

    def test_record_only(self, monkeypatch):
        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
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
            def __init__(self, message, choices=None, default=None, **kwargs):
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
            def __init__(self, message, choices=None, default=None, **kwargs):
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
            def __init__(self, message, choices=None, default=None, **kwargs):
                self.choices = choices

            def ask(self):
                by_title = {c.title: c.value for c in self.choices}
                return by_title["Build a new command"]

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        assert ask_start_menu({"presets": {"p": {}}}, "en") is NEW

    def test_remove_preset_entry(self, monkeypatch):
        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
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


class TestTruckFetch:
    """The truck entry on the start menu, and its flow."""

    INFO = {
        "vehicle": "805",
        "run_id": "2026-09-15_14-48-57_truck-805",
        "path": "/media/hotswap1/frontier/truck-805/2026/09/15/2026-09-15_14-48-57_truck-805",
        "date": "2026/09/15",
        "hostname": "truck-805-primarypc",
        "warning": "",
    }

    @pytest.fixture(autouse=True)
    def isolated_state(self, tmp_path, monkeypatch):
        import state as state_module

        path = tmp_path / "state.json"
        monkeypatch.setattr(state_module, "STATE_PATH", str(path))
        monkeypatch.setenv("BRAIN2_REPO_PATH", "/nonexistent-brain2")
        return path

    def test_menu_lists_truck_entry(self, monkeypatch):
        captured = {}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                captured["titles"] = [c.title for c in choices]

            def ask(_):
                return None

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        ask_start_menu({}, "en")
        assert "Fetch the latest Run ID from the truck" in captured["titles"]

    def test_menu_returns_truck_sentinel(self, monkeypatch):
        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                self.choices = choices

            def ask(self):
                by_title = {c.title: c.value for c in self.choices}
                return by_title["Fetch the latest Run ID from the truck"]

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        assert ask_start_menu({}, "en") is launch.TRUCK_RUN

    def test_run_truck_fetch_prints_and_copies(self, monkeypatch, capsys):
        copied = []
        monkeypatch.setattr(launch.truck, "fetch_run_id", lambda vehicle="": dict(self.INFO))
        monkeypatch.setattr(launch.pyperclip, "copy", copied.append)
        launch.run_truck_fetch("en", {})
        out = capsys.readouterr().out
        assert "run_id: 2026-09-15_14-48-57_truck-805" in out
        assert "/media/hotswap1/frontier/truck-805/" in out
        assert copied == ["2026-09-15_14-48-57_truck-805"]
        assert "(copied to clipboard)" in out

    def test_run_truck_fetch_passes_remembered_vehicle(self, monkeypatch, capsys):
        # The remembered vehicle number rides along so a configured
        # per-truck alias is used when one exists.
        seen = []
        monkeypatch.setattr(launch.truck, "fetch_run_id", lambda vehicle="": seen.append(vehicle) or dict(self.INFO))
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        launch.run_truck_fetch("en", {"vehicle_number": "807"})
        assert seen == ["807"]

    def test_run_truck_fetch_prints_warning(self, monkeypatch, capsys):
        info = dict(self.INFO, warning="No runs found for today on the truck's clock.")
        monkeypatch.setattr(launch.truck, "fetch_run_id", lambda vehicle="": info)
        monkeypatch.setattr(
            launch.pyperclip, "copy", lambda text: None
        )
        launch.run_truck_fetch("en", {})
        assert "⚠️" in capsys.readouterr().out

    def test_run_truck_fetch_error_is_printed_not_raised(self, monkeypatch, capsys):
        def boom(vehicle=""):
            raise launch.truck.TruckError("could not SSH to applied@192.168.1.11")

        monkeypatch.setattr(launch.truck, "fetch_run_id", boom)
        launch.run_truck_fetch("en", {})  # must not raise
        out = capsys.readouterr().out
        assert "Could not fetch the run id:" in out
        assert "could not SSH" in out

    def test_truck_menu_entry_loops_back_to_menu(self, monkeypatch, capsys):
        # Pick the truck entry, then quit — the fetch runs and the menu is
        # shown again (not straight back into the wizard steps).
        menu_returns = [launch.TRUCK_RUN, launch.QUIT]
        monkeypatch.setattr(launch, "ask_start_menu", lambda state, lang: menu_returns.pop(0))
        # The language step still prompts through questionary.
        monkeypatch.setattr(
            launch.questionary,
            "select",
            lambda message, choices=None, default=None: type("P", (), {"ask": lambda s: "en"})(),
        )
        monkeypatch.setattr(launch.truck, "fetch_run_id", lambda vehicle="": dict(self.INFO))
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)

        launch.main()

        assert menu_returns == []  # the menu was asked twice: fetch, then quit
        out = capsys.readouterr().out
        assert "run_id: 2026-09-15_14-48-57_truck-805" in out
        assert "Cancelled." in out

    def test_setup_menu_entry_loops_back_to_menu(self, monkeypatch, capsys):
        menu_returns = [launch.TRUCK_SETUP, launch.QUIT]
        monkeypatch.setattr(launch, "ask_start_menu", lambda state, lang: menu_returns.pop(0))
        monkeypatch.setattr(
            launch.questionary,
            "select",
            lambda message, choices=None, default=None: type("P", (), {"ask": lambda s: "en"})(),
        )
        monkeypatch.setattr(launch.questionary, "text", lambda message: type("P", (), {"ask": lambda s: "805"})())

        def fake_setup(vehicle, password=""):
            return {"vehicle": vehicle, "alias": "truck-" + vehicle, "key_created": True,
                    "key_path": "/tmp/truck-805", "config_added": True, "key_installed": True,
                    "install_detail": "installed", "next_step": ""}

        monkeypatch.setattr(launch.truck, "setup_ssh", fake_setup)
        launch.main()

        assert menu_returns == []
        out = capsys.readouterr().out
        assert "truck-805: identity created" in out
        assert "public key installed" in out
        assert "Cancelled." in out

    def test_setup_menu_entry_bad_number_does_not_crash(self, monkeypatch, capsys):
        monkeypatch.setattr(
            launch.questionary, "text", lambda message: type("P", (), {"ask": lambda s: "not-a-number"})()
        )
        monkeypatch.setattr(
            launch.truck, "setup_ssh",
            lambda vehicle, password="": (_ for _ in ()).throw(launch.truck.TruckError("the truck number is required and digits-only")),
        )
        launch.run_truck_ssh_setup("en")
        out = capsys.readouterr().out
        assert "Could not set up SSH:" in out

    def test_setup_menu_entry_empty_number_cancels(self, monkeypatch, capsys):
        monkeypatch.setattr(
            launch.questionary, "text", lambda message: type("P", (), {"ask": lambda s: ""})()
        )
        launch.run_truck_ssh_setup("en")
        assert "Cancelled." in capsys.readouterr().out


# --- closed-loop mileage mode ---------------------------------------------


class TestLoopMode:
    """Build a loop (base command + ordered stops), drive it lap after lap,
    keep it in its own bucket. All questionary prompts are queued fakes."""

    @pytest.fixture(autouse=True)
    def isolated_state(self, tmp_path, monkeypatch):
        import state as state_module

        path = tmp_path / "state.json"
        monkeypatch.setattr(state_module, "STATE_PATH", str(path))
        monkeypatch.setenv("BRAIN2_REPO_PATH", "/nonexistent-brain2")
        return path

    def confirms(self, monkeypatch, answers):
        """Queue answers for questionary.confirm; past the queue, decline."""
        queue = list(answers)

        def make(message, default=False):
            return type("A", (), {"ask": lambda s: queue.pop(0) if queue else False})()

        monkeypatch.setattr(launch.questionary, "confirm", make)

    def texts(self, monkeypatch, answers):
        queue = list(answers)

        def make(message):
            return type("A", (), {"ask": lambda s: queue.pop(0) if queue else ""})()

        monkeypatch.setattr(launch.questionary, "text", make)

    def routes(self, monkeypatch, answers):
        """Queue answers for launch.ask_route (the stop picker)."""
        queue = list(answers)
        monkeypatch.setattr(launch, "ask_route", lambda *a, **k: queue.pop(0))

    # -- add_stops ----------------------------------------------------------

    def test_add_stops_until_blank(self, monkeypatch, capsys):
        self.routes(monkeypatch, ["jp_loop", "shoreline_straight", ""])
        stops = launch.add_stops("en", make_options())
        assert stops == ["jp_loop", "shoreline_straight"]
        out = capsys.readouterr().out
        assert "+ jp_loop" in out and "+ shoreline_straight" in out

    def test_add_stops_done_keyword_finishes(self, monkeypatch, capsys):
        # Typing 'done' finishes the route — the fix for quitting the app
        # because the prompt never said how to end.
        self.routes(monkeypatch, ["jp_loop", "shoreline_straight", launch.LOOP_DONE_KEYWORD])
        stops = launch.add_stops("en", make_options())
        assert stops == ["jp_loop", "shoreline_straight"]
        out = capsys.readouterr().out
        assert "Route done — 2 stop(s)" in out

    def test_add_stops_finished_print_says_how_many(self, monkeypatch, capsys):
        self.routes(monkeypatch, ["jp_loop", ""])
        launch.add_stops("en", make_options())
        assert "Route done — 1 stop(s)" in capsys.readouterr().out

    def test_add_stops_none_choice_finishes(self, monkeypatch):
        # The picker's top row is the "route done" label; picking it (the
        # empty value) is the same as a blank line.
        self.routes(monkeypatch, ["jp_loop", ""])
        assert launch.add_stops("en", make_options()) == ["jp_loop"]

    def test_add_stops_back_drops_last_stop(self, monkeypatch, capsys):
        self.routes(monkeypatch, ["jp_loop", "shoreline_straight", BACK, ""])
        stops = launch.add_stops("en", make_options())
        assert stops == ["jp_loop"]
        assert "- shoreline_straight" in capsys.readouterr().out

    def test_add_stops_quit(self, monkeypatch):
        self.routes(monkeypatch, ["jp_loop", QUIT])
        assert launch.add_stops("en", make_options()) is QUIT

    def test_add_stops_empty_when_first_blank(self, monkeypatch):
        self.routes(monkeypatch, [""])
        assert launch.add_stops("en", make_options()) == []

    # -- build_loop ----------------------------------------------------------

    def wizard_steps(self, monkeypatch, answers=None):
        """Fake the wizard steps: vehicle, launch_config, japan toggle."""
        answers = answers or {}

        def fake_ask_step(step, values, options, state):
            return answers.get(step, {"vehicle_name": "truck-812"}.get(step, False))

        monkeypatch.setattr(launch, "ask_step", fake_ask_step)

    def test_build_loop_skips_route_and_forces_japan(self, monkeypatch, capsys):
        import state as state_module

        self.wizard_steps(monkeypatch)
        self.routes(monkeypatch, ["jp_loop", "shoreline_straight", ""])
        self.texts(monkeypatch, ["jp night"])
        self.confirms(monkeypatch, [False])  # drive now? no
        state = {}

        lang, outcome = launch.build_loop(state, "en", make_options())

        assert outcome is None  # saved, not driven
        entry = state["loops"]["jp night"]
        assert entry["stops"] == ["jp_loop", "shoreline_straight"]
        assert entry["vehicle_name"] == "truck-812"
        # Japan driving is forced on — the mode is a Japan route setup —
        # whatever the wizard answered for the toggle.
        assert entry["enable_japan_driving"] is True
        # No route answer anywhere: the stops replace it.
        assert "route" not in entry
        # Saved to disk too.
        with open(state_module.STATE_PATH) as f:
            assert "jp night" in f.read()
        out = capsys.readouterr().out
        assert "jp night" in out

    def test_build_loop_route_step_never_asked(self, monkeypatch):
        asked = []
        self.wizard_steps(monkeypatch, {})
        self.routes(monkeypatch, ["jp_loop", ""])
        self.texts(monkeypatch, ["x"])
        self.confirms(monkeypatch, [False])
        real_ask_step = launch.ask_step

        def spy(step, values, options, state):
            asked.append(step)
            return real_ask_step(step, values, options, state)

        monkeypatch.setattr(launch, "ask_step", spy)
        launch.build_loop({}, "en", make_options())
        assert "route" not in asked

    def test_build_loop_no_stops_saves_nothing(self, monkeypatch, capsys):
        self.wizard_steps(monkeypatch)
        self.routes(monkeypatch, [""])  # declared done with zero stops
        state = {}
        lang, outcome = launch.build_loop(state, "en", make_options())
        assert outcome is None
        assert not state.get("loops")
        assert "at least one stop" in capsys.readouterr().out

    def test_build_loop_full_bucket_refused_up_front(self, monkeypatch, capsys):
        # MAX_LOOPS loops already saved (Q/W/E/R all taken): refuse a
        # fifth BEFORE the wizard runs, so no stops get typed for nothing.
        import state as state_module

        asked = []
        monkeypatch.setattr(launch, "ask_step", lambda *a: asked.append(a[0]) or "x")
        state = {
            "loops": {f"L{i}": {"stops": ["jp_loop"]} for i in range(state_module.MAX_LOOPS)}
        }
        lang, outcome = launch.build_loop(state, "en", make_options())
        assert (lang, outcome) == ("en", None)
        assert asked == []  # no prompt happened at all
        assert len(state["loops"]) == state_module.MAX_LOOPS
        assert "Loops are full" in capsys.readouterr().out

    def test_build_loop_drive_now_returns_name(self, monkeypatch):
        self.wizard_steps(monkeypatch)
        self.routes(monkeypatch, ["jp_loop", ""])
        self.texts(monkeypatch, ["jp night"])
        self.confirms(monkeypatch, [True])  # drive now? yes
        state = {}
        lang, outcome = launch.build_loop(state, "en", make_options())
        assert outcome == "jp night"

    def test_build_loop_quit_propagates(self, monkeypatch, capsys):
        monkeypatch.setattr(
            launch, "ask_step", lambda *a: QUIT
        )
        lang, outcome = launch.build_loop({}, "en", make_options())
        assert outcome is QUIT
        assert "Cancelled." in capsys.readouterr().out

    # -- drive_loop ----------------------------------------------------------

    def saved_loop_state(self):
        from state import save_loop

        state = {}
        save_loop(
            state,
            "jp night",
            {"vehicle_name": "truck-812", "launch_config": "etc_sds_road_readiness"},
            ["jp_loop", "shoreline_straight"],
        )
        return state

    def test_drive_loop_runs_every_stop_then_wraps(self, monkeypatch, capsys):
        state = self.saved_loop_state()
        copied = []
        monkeypatch.setattr(launch.pyperclip, "copy", copied.append)
        # stop1->stop2 yes, wrap to lap2 yes, lap2 stop1->stop2 yes, wrap no.
        self.confirms(monkeypatch, [True, True, True, False])

        launch.drive_loop(state, "en", "jp night")

        out = capsys.readouterr().out
        # Two laps x two stops: every stop command printed, route swapped.
        assert out.count("--route jp_loop") == 2
        assert out.count("--route shoreline_straight") == 2
        assert out.count("--enable_japan_driving") == 4
        assert out.count("Lap complete!") == 1  # the wrap banner (lap 2)
        assert "Full laps driven: 2" in out
        # Each stop's command was copied and remembered.
        assert len(copied) == 4
        routes_in_history = [e["route"] for e in state["history"]]
        assert routes_in_history[:4] == [
            "shoreline_straight",
            "jp_loop",
            "shoreline_straight",
            "jp_loop",
        ]

    def test_drive_loop_mid_lap_exit_partial_summary(self, monkeypatch, capsys):
        state = self.saved_loop_state()
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        self.confirms(monkeypatch, [False])  # "ready for stop 2?" — no

        launch.drive_loop(state, "en", "jp night")

        out = capsys.readouterr().out
        assert out.count("--route jp_loop") == 1
        assert out.count("--route shoreline_straight") == 0
        assert "stop 1 of 2" in out
        assert "full laps driven: 0" in out

    def test_drive_loop_ctrl_c_at_wrap_ends(self, monkeypatch, capsys):
        state = self.saved_loop_state()
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        queue = [True, None]  # on to stop 2, then Ctrl-C at the wrap prompt

        def make(message, default=False):
            return type("A", (), {"ask": lambda s: queue.pop(0) if queue else False})()

        monkeypatch.setattr(launch.questionary, "confirm", make)

        launch.drive_loop(state, "en", "jp night")
        out = capsys.readouterr().out
        assert "Full laps driven: 1" in out

    def test_drive_loop_single_stop_wraps_without_stop_prompts(self, monkeypatch, capsys):
        state = self.saved_loop_state()
        from state import save_loop

        save_loop(state, "one stop", {"vehicle_name": "truck-812", "launch_config": "c"}, ["jp_loop"])
        monkeypatch.setattr(launch.pyperclip, "copy", lambda text: None)
        self.confirms(monkeypatch, [False])  # wrap? no after lap 1

        launch.drive_loop(state, "en", "one stop")
        out = capsys.readouterr().out
        assert out.count("--route jp_loop") == 1
        assert "Full laps driven: 1" in out

    def test_drive_loop_unknown_name(self, monkeypatch, capsys):
        launch.drive_loop({}, "en", "missing")
        assert "No loops saved yet" in capsys.readouterr().out

    # -- menu + session -------------------------------------------------------

    def test_menu_always_lists_build_and_loops_when_saved(self, monkeypatch):
        captured = {}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                captured["titles"] = [c.title for c in choices]
                captured["values"] = [c.value for c in choices]

            def ask(_):
                return None

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        state = self.saved_loop_state()
        ask_start_menu(state, "en")
        titles, values = captured["titles"], captured["values"]
        # Build is always there; the saved loop and remove appear too.
        assert "Build a closed-loop mileage route (Japan)" in titles
        assert "Drive a closed-loop mileage route (Japan) — jp night" in titles
        assert ("loop", "jp night") in values
        assert "Remove a saved loop" in titles

    def test_menu_without_loops_no_remove_entry(self, monkeypatch):
        captured = {}

        class FakeSelect:
            def __init__(self, message, choices=None, default=None, **kwargs):
                captured["titles"] = [c.title for c in choices]

            def ask(_):
                return None

        monkeypatch.setattr(launch.questionary, "select", FakeSelect)
        ask_start_menu({}, "en")
        assert "Remove a saved loop" not in captured["titles"]

    def test_session_dispatches_saved_loop_to_drive(self, monkeypatch):
        driven = []
        monkeypatch.setattr(launch, "ask_start_menu", lambda s, lang: ("loop", "jp night"))
        menu_returns = [("loop", "jp night"), QUIT]
        monkeypatch.setattr(
            launch, "ask_start_menu", lambda s, lang: menu_returns.pop(0)
        )
        monkeypatch.setattr(launch, "drive_loop", lambda s, lang, name: driven.append(name))
        monkeypatch.setattr(
            launch.questionary,
            "select",
            lambda message, choices=None, default=None: type("P", (), {"ask": lambda s: "en"})(),
        )
        launch.main()
        assert driven == ["jp night"]

    def test_session_builds_then_drives_when_drive_now(self, monkeypatch, capsys):
        state = self.saved_loop_state()
        built = []

        def fake_build(s, lang, options):
            built.append(lang)
            return lang, "jp night"

        driven = []
        monkeypatch.setattr(launch, "build_loop", fake_build)
        monkeypatch.setattr(launch, "drive_loop", lambda s, lang, name: driven.append(name))
        menu_returns = [BUILD_LOOP, QUIT]
        monkeypatch.setattr(
            launch, "ask_start_menu", lambda s, lang: menu_returns.pop(0)
        )
        monkeypatch.setattr(
            launch.questionary,
            "select",
            lambda message, choices=None, default=None: type("P", (), {"ask": lambda s: "en"})(),
        )
        launch.main()
        assert built == ["en"]
        assert driven == ["jp night"]

    def test_remove_loop_flow(self, monkeypatch, capsys):
        state = self.saved_loop_state()
        monkeypatch.setattr(
            launch.questionary,
            "select",
            lambda message, choices=None, default=None: type(
                "P", (), {"ask": lambda s: next(
                    c.value for c in choices if c.value == "jp night"
                )}
            )(),
        )
        self.confirms(monkeypatch, [True])
        launch.remove_loop(state, "en")
        assert state["loops"] == {}
        assert "Preset removed: jp night" in capsys.readouterr().out
