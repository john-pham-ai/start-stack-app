import pyperclip
import questionary
from prompt_toolkit.styles import Style
from questionary import Choice

import recorder
import truck
from questionary.prompts.common import InquirerControl
from routes_sync import synced_commit
from self_update import BLOCKED, UPDATED, self_update
from shared_presets import (
    PresetImportError,
    export_preset,
    import_preset_file,
    load_shared_presets,
    merge_presets,
)
from stack_options import build_command, load_options, map_key_for_route
from state import (
    CUSTOM_PRESET,
    MAX_LOOPS,
    VALUES_PRESET,
    LoopBucketFull,
    command_entry_values,
    command_values,
    delete_loop,
    delete_preset,
    get_history,
    load_loop,
    load_preset,
    load_state,
    loop_values,
    normalize_custom_command,
    preset_kind,
    remember_command,
    save_custom_preset,
    save_loop,
    save_preset,
    save_state,
)
from translations import t

BACK = object()
QUIT = object()
NEW = object()  # "build a new command" on the start menu
RECORD_ONLY = object()  # "record the screen only" on the start menu
TRUCK_RUN = object()  # "fetch the latest run id from the truck" on the start menu
TRUCK_SETUP = object()  # "set up SSH for a truck" on the start menu
SAVE_CUSTOM = object()  # "save a custom command as a preset" on the start menu
REMOVE_PRESET = object()  # "remove a preset" on the start menu
DRIVE_LOOP = object()  # "drive a closed-loop mileage route" on the start menu
BUILD_LOOP = object()  # "build a closed-loop mileage route" on the start menu
REMOVE_LOOP = object()  # "remove a saved loop" on the start menu
EXPORT_PRESET = object()  # "export a preset to share" on the start menu
IMPORT_PRESET = object()  # "import a preset file" on the start menu
BACK_TO_MENU = object()  # a pass that should return to the start menu

# Start-menu shortcut keys (press, then Enter). Presets get the number-row
# symbols in save order; the recent runs sit at the bottom of the menu and
# take A/S/D/F (letters are bound lowercase — the physical key, unshifted);
# the saved Japan loops take Q/W/E/R, which is also why the loop bucket is
# capped at 4 (state.MAX_LOOPS).
PRESET_SHORTCUTS = ("!", "@", "#", "$", "%", "^", "&", "*", "(", ")")
RECENT_SHORTCUTS = ("a", "s", "d", "f")
LOOP_SHORTCUTS = ("q", "w", "e", "r")
RECENT_MENU_LIMIT = len(RECENT_SHORTCUTS)

# questionary only validates shortcut keys drawn from 1-0/a-z, and its
# auto-assign pool stops there too. The number-row symbols aren't in the
# pool, so extend it once here: with use_shortcuts=True the menu's symbol
# shortcuts pass validation and register their key bindings; the plain
# menu entries keep questionary's automatic 1, 2, 3, ... keys.
InquirerControl.SHORTCUT_KEYS = InquirerControl.SHORTCUT_KEYS + list(PRESET_SHORTCUTS)


class LoadedCommand:
    """A custom preset's raw command, handed back from the start menu."""

    def __init__(self, name, command):
        self.name = name
        self.command = command

STEPS = ["language", "vehicle_name", "launch_config", "route", "enable_japan_driving"]

# Easier-on-the-eyes styling for the type-to-autofill prompts. questionary's
# defaults paint every suggestion bold orange on a light-grey menu; this
# uses a dark menu with plain light text, a soft blue highlight for the
# current row, and a muted validation bar.
AUTOCOMPLETE_STYLE = Style(
    [
        ("completion-menu", "bg:#2b2b2b #d0d0d0"),
        ("completion-menu.completion", "bg:#2b2b2b #d0d0d0 nobold nounderline"),
        ("completion-menu.completion answer", "bg:#2b2b2b #d0d0d0 nobold"),
        ("completion-menu.completion.current", "bg:#3a5f8a #ffffff nobold"),
        ("completion-menu.completion.current answer", "bg:#3a5f8a #ffffff nobold"),
        # The current row also carries questionary's "selected" class, whose
        # prompt_toolkit default is "reverse" — undo that so the row stays
        # white-on-blue instead of flipping to blue-on-white.
        ("completion-menu.completion.current selected", "noreverse"),
        ("scrollbar.background", "bg:#3a3a3a"),
        ("scrollbar.button", "bg:#6a6a6a"),
        ("validation-toolbar", "bg:#3a3a3a #e0c060"),
    ]
)

# Shared kwargs for both autocomplete prompts: the style above, and no
# validation while typing — partial text is never a full route/number,
# so a red bar on every keystroke was just noise. Enter still validates.
AUTOCOMPLETE_KWARGS = {"style": AUTOCOMPLETE_STYLE, "validate_while_typing": False}

PINNED_LAUNCH_CONFIG = {"en": ["sds_road_readiness"], "ja": ["etc_sds_road_readiness"]}


def choices_for(options, field, optional=False, opts_list=None, none_label="-- none --"):
    opts_list = opts_list if opts_list is not None else options[field]
    result = [Choice(title=opt.label, value=opt.value) for opt in opts_list]
    if optional:
        result.insert(0, Choice(title=none_label, value=""))
    return result


def route_choices_for(options, none_label="-- none --"):
    """Route choices with the map named in each title.

    Both UIs search on the displayed text, so a "map_name — route_name"
    title lets typing a map name narrow things to that map's routes.
    Values are untouched — the map is search/display context only (the
    command needs no map flag; routes carry their map).
    """
    choices = [Choice(title=none_label, value="")]
    for opt in options["route"]:
        title = f"{opt.owner} — {opt.label}" if opt.owner else opt.label
        choices.append(Choice(title=title, value=opt.value))
    return choices


def ask_route(
    lang, options, none_label="-- none --", message=None, extra_valid=()
):
    """The route step as a type-to-autofill prompt.

    Start typing (a route or map name — both match) and the suggestions
    filter live; Tab or → accepts the highlighted one; ↓ on an empty
    line shows every route. An empty line means no route. The answer
    must resolve to a route — a suggestion title, its value, or its
    label (the same resolution the web combobox does) — or back/quit.

    Callers that reuse the picker for something else can pass their own
    prompt message and extra typed keywords (lowercased, returned as-is
    when nothing they would shadow resolves first): the closed-loop stop
    picker accepts 'done' to finish the route without hunting for the
    mouse, and says so in its prompt.
    """
    choices = route_choices_for(options, none_label=none_label)
    resolvable = {choice.title: choice.value for choice in choices}
    resolvable[""] = ""  # an empty line is a valid answer: no route
    for opt in options["route"]:
        resolvable.setdefault(opt.value, opt.value)
        resolvable.setdefault(opt.label, opt.value)
    extra = tuple(kw.lower() for kw in extra_valid)

    def resolve(text):
        return resolvable.get((text or "").strip())

    def valid(text):
        stripped = (text or "").strip()
        if stripped.lower() in ("back", "quit"):
            return True
        if resolve(stripped) is not None:
            return True
        if stripped.lower() in extra:
            return True
        return "Pick a route from the suggestions (or leave blank for none)."

    answer = questionary.autocomplete(
        message if message is not None else t(lang, "route") + " " + t(lang, "nav_hint"),
        choices=[choice.title for choice in choices],
        validate=valid,
        **AUTOCOMPLETE_KWARGS,
    ).ask()
    if answer is None:
        return QUIT
    answer = answer.strip()
    if answer.lower() == "back":
        return BACK
    if answer.lower() == "quit":
        return QUIT
    resolved = resolve(answer)
    if resolved is not None:
        return resolved or ""
    if answer.lower() in extra:
        return answer.lower()
    return resolved or ""


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
        **AUTOCOMPLETE_KWARGS,
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

    Always shown, and keyboard-first: every entry has a shortcut (press
    the key, then Enter — questionary hands out 1, 2, 3... to the fixed
    entries), presets take the number-row symbols !..) in save order, the
    Japan loops take Q/W/E/R, and the recent runs sit at the bottom with
    A/S/D/F — only the last RECENT_MENU_LIMIT runs are listed. Recording-
    only mode and saving a custom command preset are always one pick
    away; the closed-loop entries join once relevant — driving one per
    saved loop, building one always available, removing one once any are
    saved.     Returns a sentinel (NEW / RECORD_ONLY / SAVE_CUSTOM / REMOVE_PRESET /
    DRIVE_LOOP / BUILD_LOOP / REMOVE_LOOP / EXPORT_PRESET / IMPORT_PRESET /
    QUIT), a ("loop", name) tuple for a saved loop, a values dict loaded
    from a values preset or history entry, or a LoadedCommand for a custom
    command preset.
    """
    personal = state.get("presets", {})
    shared, rejected = load_shared_presets()
    if rejected:
        print(t(lang, "shared_broken").format(n=len(rejected)))
    presets = merge_presets(personal, shared)
    history = get_history(state, limit=RECENT_MENU_LIMIT)
    loops = state.get("loops", {})

    def shortcut(keys, index):
        """The key for the index-th entry of a shortcutted group, or None
        past the end (questionary then auto-assigns a spare key)."""
        return keys[index] if index < len(keys) else None

    choices = [
        Choice(title=t(lang, "start_new"), value=NEW),
        Choice(title=t(lang, "record_only"), value=RECORD_ONLY),
        Choice(title=t(lang, "truck_run_menu"), value=TRUCK_RUN),
        Choice(title=t(lang, "truck_setup_menu"), value=TRUCK_SETUP),
        Choice(title=t(lang, "save_custom_preset"), value=SAVE_CUSTOM),
        Choice(title=t(lang, "loop_build_menu"), value=BUILD_LOOP),
    ]
    for index, (name, entry) in enumerate(presets.items()):
        title = f"{t(lang, 'preset_label')}: {name}"
        if entry.get("shared"):
            title += f" {t(lang, 'shared_tag')}"
        elif preset_kind(entry) == CUSTOM_PRESET:
            title += f" {t(lang, 'custom_tag')}"
        choices.append(
            Choice(title=title, value=("preset", name),
                   shortcut_key=shortcut(PRESET_SHORTCUTS, index))
        )
    if presets:
        choices.append(Choice(title=t(lang, "remove_preset"), value=REMOVE_PRESET))
    if any(preset_kind(e) == VALUES_PRESET for e in personal.values()):
        choices.append(Choice(title=t(lang, "export_menu"), value=EXPORT_PRESET))
    choices.append(Choice(title=t(lang, "import_menu"), value=IMPORT_PRESET))
    # Saved loops: drive entries right after the presets, each one a
    # Q/W/E/R keystroke away.
    for index, name in enumerate(loops):
        title = f"{t(lang, 'loop_menu')} — {name}"
        choices.append(
            Choice(title=title, value=("loop", name),
                   shortcut_key=shortcut(LOOP_SHORTCUTS, index))
        )
    if loops:
        choices.append(Choice(title=t(lang, "loop_remove_menu"), value=REMOVE_LOOP))
    # The recent runs live at the bottom of the menu, last 4 only.
    for index, entry in enumerate(history):
        summary = summarize_entry(entry)
        choices.append(
            Choice(title=f"{t(lang, 'recent_label')}: {summary}", value=("history", index),
                   shortcut_key=shortcut(RECENT_SHORTCUTS, index))
        )
    choices.append(Choice(title=t(lang, "quit"), value=QUIT))

    answer = questionary.select(
        t(lang, "menu_prompt"),
        choices=choices,
        use_shortcuts=True,
        instruction=t(lang, "menu_shortcut_hint"),
    ).ask()
    if answer is None or answer is QUIT:
        return QUIT
    if answer in (
        NEW,
        RECORD_ONLY,
        TRUCK_RUN,
        TRUCK_SETUP,
        SAVE_CUSTOM,
        REMOVE_PRESET,
        BUILD_LOOP,
        REMOVE_LOOP,
        EXPORT_PRESET,
        IMPORT_PRESET,
    ):
        return answer
    if isinstance(answer, tuple) and answer[0] == "loop":
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
    carries one. Afterwards it's the start menu again, like every flow.
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


def run_truck_fetch(lang, state):
    """Fetch the latest run id from the cabled truck, print it, copy it.

    The remembered vehicle number rides along so a configured per-truck
    alias (see truck.setup_ssh) is used when one exists. A fetch failure is
    printed and swallowed — it shouldn't kill the wizard, which loops back
    to the start menu afterwards.
    """
    try:
        info = truck.fetch_run_id((state.get("vehicle_number") or "").strip())
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


def run_truck_ssh_setup(lang):
    """One-time per-truck SSH setup (see truck.py): identity + alias named
    after the truck number, then the public key installed. The password is
    only asked for when the existing key was rejected. Failure prints the
    reason and the manual ssh-copy-id line; the wizard then returns to the
    start menu.
    """
    answer = questionary.text(t(lang, "truck_setup_vehicle_prompt")).ask()
    vehicle = (answer or "").strip().removeprefix("truck-") if answer else ""
    if not vehicle:
        print(t(lang, "cancelled") + "\n")
        return

    try:
        res = truck.setup_ssh(vehicle)
    except truck.TruckError as err:
        print(t(lang, "truck_setup_error_prefix") + " " + str(err) + "\n")
        return

    if not res["key_installed"]:
        password = questionary.password(t(lang, "truck_setup_password_prompt")).ask() or ""
        if password:
            installed, detail = truck.retry_install(vehicle, res["public_key"], password)
            res["key_installed"], res["install_detail"] = installed, detail

    print("")
    truck.print_setup_result(res)
    print("")


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


# --- closed-loop mileage mode ------------------------------------------------
#
# A "closed loop" wraps a base command around an ordered list of stops, each
# stop a route. Driving it is the same command with the route swapped at each
# stop; the last stop leads back to the first, so the loop closes and laps
# accumulate mileage until the tester declares the run done. Every stop
# command lands on the clipboard and is history-remembered, so a stop
# behaves exactly like a hand-built command.


# Typed keywords that finish stop-adding, so "done" works from the keyboard
# instead of hunting for the suggestion row. A route named the same wins,
# because resolution runs first.
LOOP_DONE_KEYWORD = "done"


def add_stops(lang, options, stops=None):
    """Add stops (routes) in driving order until the tester declares the
    route done — a blank line, the 'done' keyword, or picking the
    '-- route done --' row.

    The same route picker as the wizard, repeated, but the prompt says
    what ends the route so nobody has to guess (typing 'quit' there
    quits the app, which is why the prompt is explicit). BACK drops the
    most recent stop, or leaves with nothing when there is none to drop.
    Returns the stop list (possibly empty), or the QUIT sentinel.
    """
    stops = list(stops or [])
    print(t(lang, "loop_add_stops") + "\n")
    while True:
        stop = ask_route(
            lang,
            options,
            none_label=t(lang, "loop_add_done"),
            message=t(lang, "loop_stop_prompt").format(n=len(stops) + 1),
            extra_valid=(LOOP_DONE_KEYWORD,),
        )
        if stop is QUIT:
            return QUIT
        if stop is BACK:
            if stops:
                print(f"- {stops.pop()}\n")
                continue
            return stops
        if stop == "" or stop == LOOP_DONE_KEYWORD:
            # Blank, 'done', or the done row: the tester declares the
            # whole route done rather than the app guessing.
            print(t(lang, "loop_route_done").format(n=len(stops)) + "\n")
            return stops
        stops.append(stop)
        print(f"+ {stop}  ({t(lang, 'loop_stop_count').format(n=len(stops))})\n")


def build_loop(state, lang, options):
    """Build a new closed loop: the wizard's base command, then the stops.

    The base is the wizard minus the route step — the stops define the
    routes — and Japan driving is forced on: this mode is a Japan route
    setup. The loop bucket holds MAX_LOOPS loops (the Q/W/E/R menu
    shortcuts); a full bucket is refused up front rather than after the
    stops have been typed in. Returns (lang, outcome): outcome is the
    loop's name when the tester wants to drive it right away, None when
    they don't, and the QUIT / BACK_TO_MENU sentinels to leave
    (BACK_TO_MENU re-asked the language first, so lang may change — same
    contract as run_command_flow).
    """
    if len(state.get("loops", {})) >= MAX_LOOPS:
        print(t(lang, "loops_full") + "\n")
        return lang, None
    values = {"language": lang}
    i = 1
    while i < len(STEPS):
        step = STEPS[i]
        if step == "route":  # the stops replace the single-route answer
            i += 1
            continue
        answer = ask_step(step, values, options, state)
        if answer is BACK:
            if i == 1:
                # Backing off the first step re-asks the language, then
                # it's the start menu again — as the wizard does.
                new_lang = ask_step("language", values, options, state)
                if new_lang is QUIT:
                    print(t(values.get("language", "en"), "cancelled"))
                    return values["language"], QUIT
                return new_lang, BACK_TO_MENU
            i -= 1
            continue
        if answer is QUIT:
            print(t(values.get("language", "en"), "cancelled"))
            return values["language"], QUIT
        values[step] = answer
        i += 1
    values["enable_japan_driving"] = True

    stops = add_stops(lang, options)
    if stops is QUIT:
        return lang, QUIT
    if not stops:
        print(t(lang, "loop_no_stops") + "\n")
        return lang, None

    name = (questionary.text(t(lang, "preset_name_prompt")).ask() or "").strip()
    try:
        saved = save_loop(state, name, values, stops)
    except LoopBucketFull:
        print(t(lang, "loops_full") + "\n")
        return lang, None
    if not saved:
        print(t(lang, "loop_no_stops") + "\n")
        return lang, None
    save_state(state)

    base = build_command(
        vehicle_name=values["vehicle_name"],
        launch_config=values["launch_config"],
        route="",
        enable_japan_driving=True,
    )
    print(t(lang, "loop_saved") + " " + name + "\n")
    print(f"$ {base} --route <stop>   ({t(lang, 'loop_stop_count').format(n=len(stops))})\n")
    for index, stop in enumerate(stops, start=1):
        print(f"  {index}. {stop}")
    print("")

    if questionary.confirm(t(lang, "loop_drive_q"), default=False).ask():
        return lang, name
    return lang, None


def _stop_command(values, stop):
    """The base command with the route set to this one stop."""
    return build_command(
        vehicle_name=values["vehicle_name"],
        launch_config=values["launch_config"],
        route=stop,
        enable_japan_driving=True,
    )


def drive_loop(state, lang, name):
    """Drive one saved loop: each stop's command in order, then wrap.

    At each stop the command is rebuilt with that stop's route, printed,
    put on the clipboard and remembered in history — the tester runs it
    there, then continues. After the last stop the loop closes back to
    the first and the wrap prompt asks for another lap; the run only ends
    when the tester says so (or quits), which is the point of a mileage
    accumulation mode. Ctrl-C at any prompt also ends the drive.
    """
    entry = load_loop(state, name)
    if not entry:
        print(t(lang, "loop_none_saved") + "\n")
        return
    values = loop_values(entry)
    stops = values["stops"]

    laps = 0
    while True:  # laps — the tester declares the run done at the wrap prompt
        laps += 1
        for index, stop in enumerate(stops, start=1):
            command = _stop_command(values, stop)
            print(f"\n=== {t(lang, 'loop_stop_n').format(i=index, n=len(stops))}: {stop} ===")
            print("\n" + command + "\n")
            remember_command(
                state,
                {
                    "vehicle_name": values["vehicle_name"],
                    "launch_config": values["launch_config"],
                    "route": stop,
                    "enable_japan_driving": True,
                },
                command,
            )
            save_state(state)
            try:
                pyperclip.copy(command)
                print(t(lang, "copied_clipboard") + "\n")
            except pyperclip.PyperclipException:
                print(t(lang, "could_not_copy") + "\n")

            if index < len(stops):
                proceed = questionary.confirm(
                    t(lang, "loop_next_stop").format(next=index + 1), default=True
                ).ask()
                if proceed is None or not proceed:
                    _loop_summary(lang, laps, index, len(stops))
                    return
        # The last stop is done: the loop closes back to stop 1.
        proceed = questionary.confirm(
            t(lang, "loop_wrap_body").format(lap=laps + 1), default=True
        ).ask()
        if proceed is None or not proceed:
            _loop_summary(lang, laps, len(stops), len(stops))
            return
        print(f"\n{t(lang, 'loop_wrap_title')}\n")


def _loop_summary(lang, laps, stop_index, stop_count):
    """The end-of-run line: laps driven, and where the drive stopped."""
    if stop_index == stop_count:
        print("\n" + t(lang, "loop_summary").format(laps=laps) + "\n")
    else:
        print(
            "\n"
            + t(lang, "loop_summary_partial").format(
                laps=laps, i=stop_index, n=stop_count, full=laps - 1
            )
            + "\n"
        )


def remove_loop(state, lang):
    """Pick one of the saved loops and delete it; back leaves untouched."""
    names = list(state.get("loops", {}))
    if not names:
        return

    choices = [Choice(title=t(lang, "back"), value=BACK)]
    for name in names:
        choices.append(Choice(title=name, value=name))
    answer = questionary.select(t(lang, "loop_remove_which"), choices=choices).ask()
    if answer is None or answer is BACK:
        return

    message = t(lang, "confirm_remove_prompt").format(name=answer)
    if not questionary.confirm(message, default=False).ask():
        return

    delete_loop(state, answer)
    save_state(state)
    print(t(lang, "preset_removed").format(name=answer) + "\n")


def export_preset_flow(state, lang):
    """Pick a personal values preset and write its share file.

    The export lands in exports/<name>.json next to the tool, carrying
    the exporter's user and a timestamp; sending that file in gets it
    committed under presets/, where every machine picks it up (see
    shared_presets.py). Custom command presets can't be shared — the
    point is route setups that rebuild anywhere.
    """
    exportable = {
        name: entry
        for name, entry in state.get("presets", {}).items()
        if preset_kind(entry) == VALUES_PRESET
    }
    if not exportable:
        print(t(lang, "export_none") + "\n")
        return

    choices = [Choice(title=t(lang, "back"), value=BACK)]
    for name in exportable:
        choices.append(Choice(title=name, value=name))
    answer = questionary.select(t(lang, "export_prompt"), choices=choices).ask()
    if answer is None or answer is BACK:
        return

    try:
        path = export_preset(answer, exportable[answer])
    except PresetImportError as err:
        print(str(err) + "\n")
        return
    if path is None:  # unreachable from this picker; kept for safety
        print(t(lang, "export_none") + "\n")
        return
    print(t(lang, "export_done").format(name=answer, path=path) + "\n")
    print(t(lang, "export_next_step") + "\n")


def import_preset_flow(state, lang):
    """Read a preset export file in as a local preset.

    The file's name (minus .json) becomes the preset's name; an existing
    preset under that name is only replaced after an explicit confirm.
    The imported preset is personal — it saves to local state, not the
    repo (that's what presets/ + a commit is for).
    """
    answer = (questionary.path(t(lang, "import_prompt")).ask() or "").strip()
    if not answer:
        print(t(lang, "cancelled") + "\n")
        return

    try:
        name, entry = import_preset_file(answer)
    except PresetImportError as err:
        print(str(err) + "\n")
        return

    if load_preset(state, name) is not None:
        message = t(lang, "import_overwrite").format(name=name)
        if not questionary.confirm(message, default=False).ask():
            print(t(lang, "cancelled") + "\n")
            return

    save_preset(state, name, entry)
    save_state(state)
    print(t(lang, "import_done").format(name=name) + "\n")


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
        return ask_route(lang, options, none_label=t(lang, "none_option"))
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


def run_command_flow(options, state, lang, shortcut_values):
    """Build (or reuse) a command, print and copy it, then offer recording.

    shortcut_values is None to walk the wizard for a hand-built command,
    or a values dict loaded from a preset / recent entry. The wizard
    starts past the language step (lang carries it), and 'back' on the
    wizard's first step re-asks the language before returning to the
    start menu — same back behavior the wizard always had.

    Returns (lang, outcome): outcome is BACK_TO_MENU when the pass should
    return to the start menu (the recording was discarded, or the user
    backed off the wizard's first step), QUIT when the user quit, None
    when the pass is over. lang is the language to continue with — it
    changes when the language was re-picked on the way back out.
    """
    if shortcut_values is None:
        values = {"language": lang}
        i = 1  # the language is already picked
        while i < len(STEPS):
            answer = ask_step(STEPS[i], values, options, state)
            if answer is BACK:
                if i == 1:
                    # Backing off the wizard's first step re-asks the
                    # language; afterwards it's the start menu again.
                    new_lang = ask_step("language", values, options, state)
                    if new_lang is QUIT:
                        print(t(values.get("language", "en"), "cancelled"))
                        return values["language"], QUIT
                    return new_lang, BACK_TO_MENU
                i -= 1
                continue
            if answer is QUIT:
                print(t(values.get("language", "en"), "cancelled"))
                return values["language"], QUIT
            values[STEPS[i]] = answer
            i += 1
    else:
        values, dropped = validated(shortcut_values, options)
        if dropped:
            print(t(lang, "invalid_option_note").format(", ".join(dropped)) + "\n")
        values["language"] = lang

    lang = values["language"]
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
    if (
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
        is recorder.DISCARDED
    ):
        return lang, BACK_TO_MENU
    return lang, None


def run_start_menu_session(options, state, lang, app_update=None):
    """The start menu loop — the app's only way out is an explicit Quit.

    Every flow (truck fetch/setup, preset save/remove, record-only, a
    custom preset, a built or reused command with its recording offer)
    ends back at the menu rather than closing the app. Quit is the only
    exit: picked on the start menu, or at a wizard step.

    app_update is the (status, detail) tuple self_update() returned before
    the wizard started — the interesting ones get a line below.

    Returns the language (it can be re-picked by backing out of the
    wizard's first step), and nothing else — the loop only ends on Quit.
    """
    # Startup notes, said in the picked language: where the routes came
    # from (see routes_sync.py: GitHub-synced cache → local checkout →
    # options.csv; silence means not synced — offline, disabled, or
    # falling back, the lists still work) and whether the app itself just
    # fast-forwarded to origin (see self_update.py).
    commit = synced_commit()
    if commit:
        print(t(lang, "routes_synced").format(commit=commit))
    if app_update and app_update[0] == UPDATED:
        print(t(lang, "app_updated").format(hash=app_update[1]))
    elif app_update and app_update[0] == BLOCKED:
        print(t(lang, "app_update_blocked").format(hash=app_update[1]))
    while True:
        menu = ask_start_menu(state, lang)
        if menu is QUIT:
            print(t(lang, "cancelled"))
            return lang
        if menu is TRUCK_RUN:
            run_truck_fetch(lang, state)
            continue
        if menu is TRUCK_SETUP:
            run_truck_ssh_setup(lang)
            continue
        if menu is REMOVE_PRESET:
            remove_preset(state, lang)
            continue
        if menu is SAVE_CUSTOM:
            save_custom_command_preset(state, lang)
            continue
        if menu is BUILD_LOOP:
            lang, outcome = build_loop(state, lang, options)
            if outcome is QUIT:
                return lang
            if isinstance(outcome, str):  # the loop's name — drive it now
                drive_loop(state, lang, outcome)
            continue  # BACK_TO_MENU or nothing saved — menu either way
        if menu is REMOVE_LOOP:
            remove_loop(state, lang)
            continue
        if menu is EXPORT_PRESET:
            export_preset_flow(state, lang)
            continue
        if menu is IMPORT_PRESET:
            import_preset_flow(state, lang)
            continue
        if isinstance(menu, tuple) and menu[0] == "loop":
            drive_loop(state, lang, menu[1])
            continue
        if menu is RECORD_ONLY:
            recorder.run_recording_flow(lang, state)
            continue  # kept, skipped, failed or discarded — menu either way
        if isinstance(menu, LoadedCommand):
            run_custom_command(state, lang, menu)
            continue
        # NEW, or a values preset / recent command. Quitting at a wizard
        # step is the one command-flow outcome that ends the app; a
        # discarded recording or backing out of the first step both land
        # back here, like every other finished flow.
        lang, outcome = run_command_flow(options, state, lang, None if menu is NEW else menu)
        if outcome is QUIT:
            return lang
        continue


def main():
    # The app fetches its own repo first (see self_update.py): a clean
    # tree fast-forwards to origin, a dirty one is left alone — the
    # menu reports either, and the update lands on the next launch.
    app_update = self_update()

    options = load_options()
    state = load_state()

    # The language is picked once, up front — then the start menu loop,
    # where every flow begins and ends. The app only exits on Quit.
    answer = ask_step("language", {}, options, state)
    if answer is QUIT:
        print(t("en", "cancelled"))
        return

    run_start_menu_session(options, state, answer, app_update=app_update)


if __name__ == "__main__":
    main()
