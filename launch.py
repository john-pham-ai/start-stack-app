import os

import pyperclip
import questionary
from questionary import Choice

import recorder
from stack_options import build_command, load_options, map_keys_for_language, routes_for_map_key
from state import load_state, save_state
from translations import t

BACK = object()
QUIT = object()

STEPS = ["language", "vehicle_name", "launch_config", "map_key", "route", "enable_japan_driving"]

PINNED_LAUNCH_CONFIG = {"en": ["sds_road_readiness"], "ja": ["etc_sds_road_readiness"]}
PINNED_MAP_KEY = {"en": ["sunnyvale_office", "usa_zone_10"], "ja": ["jp_zone_53", "jp_zone_54"]}


def choices_for(options, field, optional=False, opts_list=None, none_label="-- none --"):
    opts_list = opts_list if opts_list is not None else options[field]
    result = [Choice(title=opt.label, value=opt.value) for opt in opts_list]
    if optional:
        result.insert(0, Choice(title=none_label, value=""))
    return result


def pin_first(opts_list, pinned_values):
    """Move the given values to the front, in that order; keep the rest as-is."""
    pinned = [opt for v in pinned_values for opt in opts_list if opt.value == v]
    rest = [opt for opt in opts_list if opt.value not in pinned_values]
    return pinned + rest


def safe_default(remembered, choices):
    """Only use a remembered value as the default if it's still a valid choice."""
    return remembered if remembered in [c.value for c in choices] else None


def ask_vehicle_name(lang, state, current_value=None):
    message = t(lang, "vehicle_name_number_prompt") + " " + t(lang, "nav_hint")
    default_number = current_value[len("truck-") :] if current_value else state.get("vehicle_number", "")
    answer = questionary.text(
        message,
        default=default_number,
        validate=lambda text: True if text.strip() else "Enter a number (or 'back'/'quit').",
    ).ask()
    if answer is None:
        return QUIT
    answer = answer.strip()
    if answer.lower() == "back":
        return BACK
    if answer.lower() == "quit":
        return QUIT
    return f"truck-{answer}"


def ask_run_id_and_test_case(lang, state):
    """Ask for the run id, then the Polarion test case id.

    Typing 'back' at the test case prompt returns to the run id prompt;
    typing 'skip' (or leaving it blank) means no test case id. The skip
    choice is remembered in state so it's the default next time.
    """
    recording_state = state.setdefault("recording", {})
    run_id = ""
    while True:
        answer = questionary.text(t(lang, "run_id_prompt"), default=run_id).ask()
        run_id = (answer or "").strip()

        skip_default = recording_state.get("skip_polarion", False)
        default_tc = "skip" if skip_default else recording_state.get("last_test_case_id", "")
        tc_answer = questionary.text(t(lang, "test_case_prompt"), default=default_tc).ask()
        tc_answer = (tc_answer or "").strip()

        if tc_answer.lower() == "back":
            continue
        if tc_answer.lower() == "skip" or tc_answer == "":
            return run_id, "", True
        return run_id, tc_answer, False


def ask_step(step, values, options, state):
    lang = values.get("language", "en")
    default = None
    prior_answer = values.get(step)

    if step == "language":
        message = t("en", "language_prompt")
        choices = [Choice("English", "en"), Choice("日本語", "ja")]
        quit_label = "Quit / 終了"
    elif step == "vehicle_name":
        return ask_vehicle_name(lang, state, prior_answer)
    elif step == "launch_config":
        message = t(lang, "launch_config")
        ordered = pin_first(options["launch_config"], PINNED_LAUNCH_CONFIG[lang])
        choices = choices_for(options, "launch_config", opts_list=ordered)
        quit_label = t(lang, "quit")
        default = safe_default(prior_answer or state.get("launch_config", {}).get(lang), choices)
    elif step == "map_key":
        message = t(lang, "map_key")
        available_map_keys = map_keys_for_language(options, lang)
        ordered = pin_first(available_map_keys, PINNED_MAP_KEY[lang])
        choices = choices_for(
            options, "map_key", optional=True, opts_list=ordered, none_label=t(lang, "none_option")
        )
        quit_label = t(lang, "quit")
        remembered = prior_answer if prior_answer is not None else state.get("map_key", {}).get(lang)
        default = safe_default(remembered, choices)
    elif step == "route":
        message = t(lang, "route")
        filtered_routes = routes_for_map_key(options, values.get("map_key", ""))
        choices = choices_for(
            options, "route", optional=True, opts_list=filtered_routes, none_label=t(lang, "none_option")
        )
        quit_label = t(lang, "quit")
    else:  # enable_japan_driving
        message = t(lang, step)
        choices = [Choice(title=t(lang, "yes"), value=True), Choice(title=t(lang, "no"), value=False)]
        quit_label = t(lang, "quit")
        default = lang == "ja"

    nav = [Choice(title=quit_label, value=QUIT)]
    if step != "language":
        nav.insert(0, Choice(title=t(lang, "back"), value=BACK))

    answer = questionary.select(message, choices=choices + nav, default=default).ask()
    return QUIT if answer is None else answer


def main():
    options = load_options()
    state = load_state()
    values = {}
    i = 0
    while i < len(STEPS):
        answer = ask_step(STEPS[i], values, options, state)
        if answer is BACK:
            i -= 1
            continue
        if answer is QUIT:
            print(t(values.get("language", "en"), "cancelled"))
            return
        values[STEPS[i]] = answer
        i += 1

    lang = values["language"]

    state["vehicle_number"] = values["vehicle_name"][len("truck-") :]
    state.setdefault("launch_config", {})[lang] = values["launch_config"]
    state.setdefault("map_key", {})[lang] = values["map_key"]
    save_state(state)

    command = build_command(
        vehicle_name=values["vehicle_name"],
        launch_config=values["launch_config"],
        route=values["route"],
        enable_japan_driving=values["enable_japan_driving"],
    )

    print("\n" + command + "\n")
    try:
        pyperclip.copy(command)
        print(t(lang, "copied_clipboard") + "\n")
    except pyperclip.PyperclipException:
        print(t(lang, "could_not_copy") + "\n")

    if not recorder.ensure_ffmpeg():
        print(t(lang, "ffmpeg_missing") + "\n")
    else:
        should_finalize = False
        with recorder.keypress_mode():
            if recorder.wait_for_start(t(lang, "record_prompt")):
                try:
                    recording = recorder.ScreenRecording()
                    recording.start()
                except recorder.RecordingError as exc:
                    print(t(lang, "record_failed") + " " + str(exc) + "\n")
                else:
                    print(t(lang, "record_started") + "\n")
                    try:
                        recorder.wait_for_stop(
                            recording, label=t(lang, "recording_label"), hint=t(lang, "press_s_to_stop")
                        )
                    finally:
                        recording.stop()

                    if recorder.wait_for_keep_or_discard(t(lang, "keep_or_discard_prompt")):
                        should_finalize = True
                    else:
                        recording.discard()
                        print(t(lang, "recording_discarded") + "\n")

        if should_finalize:
            run_id, test_case_id, skipped_polarion = ask_run_id_and_test_case(lang, state)
            video_path, sidecar_path = recording.finalize(
                vehicle_name=values["vehicle_name"],
                run_id=run_id,
                test_case_id=test_case_id,
                metadata={
                    "command": command,
                    "launch_config": values["launch_config"],
                    "map_key": values["map_key"],
                    "route": values["route"],
                    "enable_japan_driving": values["enable_japan_driving"],
                },
            )

            state["recording"]["skip_polarion"] = skipped_polarion
            if not skipped_polarion and test_case_id:
                state["recording"]["last_test_case_id"] = test_case_id
            save_state(state)

            print(t(lang, "recording_saved") + " " + video_path)
            print(sidecar_path)
            print(recorder.hyperlink(os.path.dirname(video_path), label=t(lang, "open_folder")) + "\n")
            url = recorder.polarion_url(test_case_id)
            if url:
                print(t(lang, "polarion_link") + " " + url + "\n")


if __name__ == "__main__":
    main()
