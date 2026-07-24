import questionary
from questionary import Choice

from stack_options import build_command, load_options


def choices_for(options, field, optional=False):
    result = [Choice(title=opt.label, value=opt.value) for opt in options[field]]
    if optional:
        result.insert(0, Choice(title="-- none --", value=""))
    return result


def main():
    options = load_options()

    vehicle_name = questionary.select("vehicle_name", choices=choices_for(options, "vehicle_name")).ask()
    launch_config = questionary.select("launch_config", choices=choices_for(options, "launch_config")).ask()
    map_key = questionary.select("map_key (optional)", choices=choices_for(options, "map_key", optional=True)).ask()
    route = questionary.select("route (optional)", choices=choices_for(options, "route", optional=True)).ask()
    enable_japan_driving = questionary.confirm("enable_japan_driving?", default=False).ask()
    local = questionary.confirm("local?", default=False).ask()

    command = build_command(
        vehicle_name=vehicle_name,
        launch_config=launch_config,
        map_key=map_key,
        route=route,
        enable_japan_driving=enable_japan_driving,
        local=local,
    )

    print("\n" + command + "\n")


if __name__ == "__main__":
    main()
