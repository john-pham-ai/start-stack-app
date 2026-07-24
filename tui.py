import pyperclip
import questionary
from questionary import Choice

from stack_options import build_command, load_options, map_keys_for_language, routes_for_map_key
from translations import t

BACK = object()
QUIT = object()

STEPS = ["language", "vehicle_name", "launch_config", "map_key", "route", "enable_japan_driving"]


def choices_for(options, field, optional=False, opts_list=None, none_label="-- none --"):
    opts_list = opts_list if opts_list is not None else options[field]
    result = [Choice(title=opt.label, value=opt.value) for opt in opts_list]
    if optional:
        result.insert(0, Choice(title=none_label, value=""))
    return result


def ask_step(step, values, options):
    lang = values.get("language", "en")
    default = None

    if step == "language":
        message = t("en", "language_prompt")
        choices = [Choice("English", "en"), Choice("日本語", "ja")]
        quit_label = "Quit / 終了"
    elif step == "vehicle_name":
        message = t(lang, "vehicle_name")
        choices = choices_for(options, "vehicle_name")
        quit_label = t(lang, "quit")
    elif step == "launch_config":
        message = t(lang, "launch_config")
        choices = choices_for(options, "launch_config")
        quit_label = t(lang, "quit")
    elif step == "map_key":
        message = t(lang, "map_key")
        available_map_keys = map_keys_for_language(options, lang)
        choices = choices_for(
            options, "map_key", optional=True, opts_list=available_map_keys, none_label=t(lang, "none_option")
        )
        quit_label = t(lang, "quit")
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
    values = {}
    i = 0
    while i < len(STEPS):
        answer = ask_step(STEPS[i], values, options)
        if answer is BACK:
            i -= 1
            continue
        if answer is QUIT:
            print(t(values.get("language", "en"), "cancelled"))
            return
        values[STEPS[i]] = answer
        i += 1

    command = build_command(
        vehicle_name=values["vehicle_name"],
        launch_config=values["launch_config"],
        map_key=values["map_key"],
        route=values["route"],
        enable_japan_driving=values["enable_japan_driving"],
    )

    lang = values["language"]
    print("\n" + command + "\n")
    try:
        pyperclip.copy(command)
        print(t(lang, "copied_clipboard") + "\n")
    except pyperclip.PyperclipException:
        print(t(lang, "could_not_copy") + "\n")


if __name__ == "__main__":
    main()
