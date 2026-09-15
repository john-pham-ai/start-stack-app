import pyperclip
import questionary
from questionary import Choice

import recorder
import truck
from stack_options import build_command, load_options, map_key_for_route
from state import (
    CUSTOM_PRESET,
    command_entry_values,
    command_values,
    delete_preset,
    get_history,
    load_state,
    normalize_custom_command,
    preset_kind,
    remember_command,
    save_custom_preset,
    save_preset,
    save_state,
)
from translations import t

BACK = object()
QUIT = object()
NEW = object()  # "build a new command" on the start menu
RECORD_ONLY = object()  # "record the screen only" on the start menu
TRUCK_RUN = object()  # "fetch the latest run id from the truck" on the start menu
SAVE_CUSTOM = object()  # "save a custom command as a preset" on the start menu
REMOVE_PRESET = object()  # "remove a preset" on the start menu


class LoadedCommand:
    """A custom preset's raw command, handed back from the start menu."""

    def __init__(self, name, command):
        self.name = name
        self.command = command

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
    """One-line summary for a history entry in the shortcuts prompt.

    Custom command entries have no wizard fields to summarize, so the
    command itself (truncated) stands in.
    """
    parts = [entry.get("vehicle_name", ""), entry.get("launch_config", "")]
    if entry.get("route"):
        parts.append(entry["route"])
    summary = " · ".join(part for part in parts if part)
    if not summary and entry.get("command"):
        command = entry["command"]
        summary = command if len(command) <= 60 else command[:57] + "…"
    return summary or "(no command)"


def ask_start_menu(state, lang):
    """The first menu after the language pick.

    Always shown. Recording-only mode and saving a custom command preset
    are always one pick away; presets and recent commands join the list
    once they exist. Returns a sentinel (NEW / RECORD_ONLY / SAVE_CUSTOM /
    REMOVE_PRESET / QUIT), a values dict loaded from a values preset or
    history entry, or a LoadedCommand for a custom command preset.
    """
    presets = state.get("presets", {})
    history = get_history(state, limit=10)

    choices = [
        Choice(title=t(lang, "start_new"), value=NEW),
        Choice(title=t(lang, "record_only"), value=RECORD_ONLY),
        Choice(title=t(lang, "truck_run_menu"), value=TRUCK_RUN),
        Choice(title=t(lang, "save_custom_preset"), value=SAVE_CUSTOM),
    ]
    for name, entry in presets.items():
        title = f"{t(lang, 'preset_label')}: {name}"
        if preset_kind(entry) == CUSTOM_PRESET:
            title += f" {t(lang, 'custom_tag')}"
        choices.append(Choice(title=title, value=("preset", name)))
    for idx, entry in enumerate(history):
        summary = summarize_entry(entry)
        choices.append(Choice(title=f"{t(lang, 'recent_label')}: {summary}", value=("history", idx)))
    if presets:
        choices.append(Choice(title=t(lang, "remove_preset"), value=REMOVE_PRESET))
    choices.append(Choice(title=t(lang, "quit"), value=QUIT))

    answer = questionary.select(t(lang, "menu_prompt"), choices=choices).ask()
    if answer is None or answer is QUIT:
        return QUIT
    if answer in (NEW, RECORD_ONLY, TRUCK_RUN, SAVE_CUSTOM, REMOVE_PRESET):
        return answer

    kind, key = answer
    entry = presets[key] if kind == "preset" else history[key]
    if preset_kind(entry) == CUSTOM_PRESET or entry.get("custom"):
        return LoadedCommand(key, entry["command"])
    return command_values(entry)


def save_custom_command_preset(state, lang):
    """Ask for a raw command and save it as a custom preset."""
    raw = questionary.text(t(lang, "custom_command_prompt")).ask()
    command = normalize_custom_command(raw or "")
    if not command:
        return
    name = (questionary.text(t(lang, "preset_name_prompt")).ask() or "").strip()
    if save_custom_preset(state, name, command):
        print(t(lang, "preset_saved") + " " + name + "\n")
        save_state(state)


def run_custom_command(state, lang, loaded):
    """Print a custom preset's command and put it on the clipboard.

    The command is used verbatim — nothing is re-derived from wizard
    fields. Like any other one-pick reuse, the same recording offer as a
    hand-built command follows (r to record, q to skip); the vehicle name
    for the recording's filename comes from the command itself, when it
    carries one.
    """
    command = loaded.command
    print("\n" + command + "\n")

    entry_values = command_entry_values(command)
    remember_command(state, entry_values, command, custom=True)
    save_state(state)

    try:
        pyperclip.copy(command)
        print(t(lang, "copied_clipboard") + "\n")
    except pyperclip.PyperclipException:
        print(t(lang, "could_not_copy") + "\n")

    recorder.run_recording_flow(
        lang,
        state,
        vehicle_name=entry_values.get("vehicle_name", ""),
        metadata={"command": command},
    )


def run_truck_fetch(lang):
    """Fetch the latest run id from the cabled truck, print it, copy it.

    A fetch failure is printed and swallowed — it shouldn't kill the wizard,
    which loops back to the start menu afterwards.
    """
    try:
        info = truck.fetch_run_id()
    except truck.TruckError as err:
        print(t(lang, "truck_error_prefix") + " " + str(err) + "\n")
        return

    date = info.get("date", "")
    header = " · ".join(part for part in (info["vehicle"], info["hostname"], date) if part)
    print("\n" + header)
    print("run_id: " + info["run_id"])
    print("path:   " + info["path"])
    if info.get("warning"):
        print("⚠️  " + info["warning"])
    print("")

    try:
        pyperclip.copy(info["run_id"])
        print(t(lang, "copied_clipboard") + "\n")
    except pyperclip.PyperclipException:
        print(t(lang, "could_not_copy") + "\n")


def remove_preset(state, lang):
    """Pick one of the saved presets and delete it.

    Back (or declining the confirm) leaves everything untouched; removing
    saves the state right away so a quit afterwards can't resurrect it.
    """
    names = list(state.get("presets", {}))
    if not names:
        return

    choices = [Choice(title=t(lang, "back"), value=BACK)]
    for name, entry in state["presets"].items():
        title = name
        if preset_kind(entry) == CUSTOM_PRESET:
            title += f" {t(lang, 'custom_tag')}"
        choices.append(Choice(title=title, value=name))
    answer = questionary.select(t(lang, "remove_preset_prompt"), choices=choices).ask()
    if answer is None or answer is BACK:
        return

    message = t(lang, "confirm_remove_prompt").format(name=answer)
    if not questionary.confirm(message, default=False).ask():
        return

    delete_preset(state, answer)
    save_state(state)
    print(t(lang, "preset_removed").format(name=answer) + "\n")


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

        # Right after the language is picked, the start menu. Removing or
        # saving a preset loops back to the menu so you can carry on.
        if STEPS[i - 1] == "language":
            while True:
                menu = ask_start_menu(state, values["language"])
                if menu is QUIT:
                    print(t(values["language"], "cancelled"))
                    return
                if menu is RECORD_ONLY:
                    recorder.run_recording_flow(values["language"], state)
                    return
                if menu is TRUCK_RUN:
                    run_truck_fetch(values["language"])
                    continue
                if menu is REMOVE_PRESET:
                    remove_preset(state, values["language"])
                    continue
                if menu is SAVE_CUSTOM:
                    save_custom_command_preset(state, values["language"])
                    continue
                if isinstance(menu, LoadedCommand):
                    run_custom_command(state, values["language"], menu)
                    return
                if menu is not NEW:
                    # A values preset / recent command: the wizard is done —
                    # exhaust the outer loop so no step gets asked, and the
                    # command is built straight from the shortcut.
                    shortcut_values = menu
                    i = len(STEPS)
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

    # The recording offer follows every command — hand-built or loaded
    # from a preset/recent shortcut. The shortcut path already has all the
    # wizard values (validated above), so the metadata is identical; the
    # only thing a loaded preset skips is the save-preset prompt above,
    # since it's by definition already saved.
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
