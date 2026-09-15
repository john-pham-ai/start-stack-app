import pyperclip
import questionary
from questionary import Choice

import recorder
from stack_options import build_command, load_options, map_key_for_route
from state import command_values, get_history, load_state, remember_command, save_preset, save_state
from translations import t

BACK = object()
QUIT = object()
NEW = object()  # "build a new command" on the start menu
RECORD_ONLY = object()  # "record the screen only" on the start menu

STEPS = ["language", "vehicle_name", "launch_config", "route", "enable_japan_driving"]

PINNED_LAUNCH_CONFIG = {"en": ["sds_road_readiness"], "ja": ["etc_sds_road_readiness"]}


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


def ask_vehicle_name(lang, state, options, current_value=None):
    message = t(lang, "vehicle_name_number_prompt") + " " + t(lang, "nav_hint")
    if current_value and current_value.startswith("truck-"):
        default_number = current_value[len("truck-") :]
    else:
        default_number = state.get("vehicle_number", "")
    numbers = [
        opt.value[len("truck-") :] for opt in options["vehicle_name"] if opt.value.startswith("truck-")
    ]
    answer = questionary.autocomplete(
        message,
        choices=numbers,
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


def summarize_entry(entry):
    """One-line summary for a history entry in the shortcuts prompt."""
    parts = [entry.get("vehicle_name", ""), entry.get("launch_config", "")]
    if entry.get("route"):
        parts.append(entry["route"])
    return " · ".join(part for part in parts if part)


def ask_start_menu(state, lang):
    """The first menu after the language pick.

    Always shown. Recording-only mode is always one pick away, and presets
    and recent commands join the list once they exist. Returns NEW (build a
    command), RECORD_ONLY, QUIT, or a values dict loaded from a preset or
    history entry.
    """
    presets = state.get("presets", {})
    history = get_history(state, limit=10)

    choices = [
        Choice(title=t(lang, "start_new"), value=NEW),
        Choice(title=t(lang, "record_only"), value=RECORD_ONLY),
    ]
    for name in presets:
        choices.append(Choice(title=f"{t(lang, 'preset_label')}: {name}", value=("preset", name)))
    for idx, entry in enumerate(history):
        summary = summarize_entry(entry)
        choices.append(Choice(title=f"{t(lang, 'recent_label')}: {summary}", value=("history", idx)))
    choices.append(Choice(title=t(lang, "quit"), value=QUIT))

    answer = questionary.select(t(lang, "menu_prompt"), choices=choices).ask()
    if answer is None or answer is QUIT:
        return QUIT
    if answer is NEW or answer is RECORD_ONLY:
        return answer

    kind, key = answer
    return command_values(presets[key] if kind == "preset" else history[key])


def validated(values, options):
    """Drop saved values that no longer exist in the current options.

    vehicle_name is left alone (new trucks appear without an options edit),
    but launch configs / routes that have disappeared since the preset or
    history entry was saved are removed (launch_config falls back to the
    first available config) so the rebuilt command stays valid.

    Returns (values, dropped_labels).
    """
    dropped = []
    out = dict(values)

    if out.get("launch_config") and out["launch_config"] not in [o.value for o in options["launch_config"]]:
        dropped.append(out["launch_config"])
        out["launch_config"] = options["launch_config"][0].value

    routes = [o.value for o in options["route"]]
    if out.get("route") and out["route"] not in routes:
        dropped.append(out["route"])
        out["route"] = ""

    out["enable_japan_driving"] = bool(out.get("enable_japan_driving"))
    return out, dropped


def ask_step(step, values, options, state):
    lang = values.get("language", "en")
    default = None
    prior_answer = values.get(step)

    if step == "language":
        message = t("en", "language_prompt")
        choices = [Choice("English", "en"), Choice("日本語", "ja")]
        quit_label = "Quit / 終了"
    elif step == "vehicle_name":
        return ask_vehicle_name(lang, state, options, prior_answer)
    elif step == "launch_config":
        message = t(lang, "launch_config")
        ordered = pin_first(options["launch_config"], PINNED_LAUNCH_CONFIG[lang])
        choices = choices_for(options, "launch_config", opts_list=ordered)
        quit_label = t(lang, "quit")
        default = safe_default(prior_answer or state.get("launch_config", {}).get(lang), choices)
    elif step == "route":
        message = t(lang, "route")
        choices = choices_for(
            options, "route", optional=True, none_label=t(lang, "none_option")
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
    shortcut_values = None
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

        # Right after the language is picked, the start menu.
        if STEPS[i - 1] == "language":
            menu = ask_start_menu(state, values["language"])
            if menu is QUIT:
                print(t(values["language"], "cancelled"))
                return
            if menu is RECORD_ONLY:
                recorder.run_recording_flow(values["language"], state)
                return
            if menu is not NEW:
                shortcut_values = menu
                break

    lang = values["language"]
    if shortcut_values is not None:
        values, dropped = validated(shortcut_values, options)
        if dropped:
            print(t(lang, "invalid_option_note").format(", ".join(dropped)) + "\n")
        values["language"] = lang

    state["vehicle_number"] = values["vehicle_name"][len("truck-") :]
    state.setdefault("launch_config", {})[lang] = values["launch_config"]

    command = build_command(
        vehicle_name=values["vehicle_name"],
        launch_config=values["launch_config"],
        route=values["route"],
        enable_japan_driving=values["enable_japan_driving"],
    )

    print("\n" + command + "\n")

    remember_command(state, values, command)

    # Only offer to save a preset for hand-built commands — a preset loaded
    # from the shortcuts prompt is by definition already saved.
    if shortcut_values is None:
        if questionary.confirm(t(lang, "save_preset_prompt"), default=False).ask():
            name = (questionary.text(t(lang, "preset_name_prompt")).ask() or "").strip()
            if save_preset(state, name, values):
                print(t(lang, "preset_saved") + " " + name + "\n")

    save_state(state)

    try:
        pyperclip.copy(command)
        print(t(lang, "copied_clipboard") + "\n")
    except pyperclip.PyperclipException:
        print(t(lang, "could_not_copy") + "\n")

    # The recording half is shared with the standalone `recorder` flow.
    recorder.run_recording_flow(
        lang,
        state,
        vehicle_name=values["vehicle_name"],
        metadata={
            "command": command,
            "launch_config": values["launch_config"],
            # The map isn't a command flag anymore — routes carry
            # it — but it's still worth recording per run.
            "map_key": map_key_for_route(options, values["route"]),
            "route": values["route"],
            "enable_japan_driving": values["enable_japan_driving"],
        },
    )


if __name__ == "__main__":
    main()
