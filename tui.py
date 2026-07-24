import pyperclip
import questionary
from questionary import Choice

from stack_options import build_command, load_options, routes_for_map_key
from translations import t


def choices_for(options, field, optional=False, opts_list=None, none_label="-- none --"):
    opts_list = opts_list if opts_list is not None else options[field]
    result = [Choice(title=opt.label, value=opt.value) for opt in opts_list]
    if optional:
        result.insert(0, Choice(title=none_label, value=""))
    return result


def main():
    lang = questionary.select(
        t("en", "language_prompt"), choices=[Choice("English", "en"), Choice("日本語", "ja")]
    ).ask()

    options = load_options()

    vehicle_name = questionary.select(t(lang, "vehicle_name"), choices=choices_for(options, "vehicle_name")).ask()
    launch_config = questionary.select(t(lang, "launch_config"), choices=choices_for(options, "launch_config")).ask()
    map_key = questionary.select(
        t(lang, "map_key"),
        choices=choices_for(options, "map_key", optional=True, none_label=t(lang, "none_option")),
    ).ask()
    filtered_routes = routes_for_map_key(options, map_key)
    route = questionary.select(
        t(lang, "route"),
        choices=choices_for(
            options, "route", optional=True, opts_list=filtered_routes, none_label=t(lang, "none_option")
        ),
    ).ask()
    enable_japan_driving = questionary.confirm(t(lang, "enable_japan_driving"), default=False).ask()
    local = questionary.confirm(t(lang, "local"), default=False).ask()

    command = build_command(
        vehicle_name=vehicle_name,
        launch_config=launch_config,
        map_key=map_key,
        route=route,
        enable_japan_driving=enable_japan_driving,
        local=local,
    )

    print("\n" + command + "\n")
    try:
        pyperclip.copy(command)
        print(t(lang, "copied_clipboard") + "\n")
    except pyperclip.PyperclipException:
        print(t(lang, "could_not_copy") + "\n")


if __name__ == "__main__":
    main()
