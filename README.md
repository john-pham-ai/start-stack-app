# start_stack command builder

*[日本語版はこちら](README.ja.md)*

A small local tool for building the `start_stack` launch command without memorizing flags. It ships two interfaces that share the same options and logic:

- a **web UI** (Flask) you build the command in and copy out, and
- a **TUI** (terminal wizard) for driving it entirely from the command line.

Both build a command in this shape:

```
start_stack --vehicle_name truck-807 --launch_config sds_road_readiness [--map_key shirosato_zone_54] [--route shoreline_terminal_10kph] [--enable_japan_driving]
```

`map_key`, `route`, and `enable_japan_driving` are optional; `vehicle_name` and `launch_config` are always required.

## Setup

The first run needs a Python virtual environment with `flask`, `questionary`, and `pyperclip` installed. Both launcher scripts do this automatically — if `venv/` doesn't exist yet, they create it and run `pip install -r requirements.txt` before starting.

## Running it

From the project directory:

```
./run.sh       # web UI, then open http://127.0.0.1:5050
./launch.sh    # terminal wizard
```

The first time you run `./launch.sh`, it also adds a `launch` alias to your shell config (`.zshrc` for zsh; `.bash_profile` on macOS or `.bashrc`/`.bash_aliases` on Linux for bash), so afterward you can just type `launch` from anywhere instead of `cd`-ing into this directory. Open a new terminal (or `source` the file it mentions) for the alias to take effect. If it can't detect your shell, it prints the alias line to add yourself instead of guessing.

## Web UI

Pick values from the dropdowns and click **Build command** to see the resulting `start_stack` command, with a button to copy it to your clipboard.

- The **route** dropdown filters automatically based on which **map_key** you picked — a route only shows up if it's tied to that specific map key (see [Editing the options](#editing-the-options) below). Pick a different map key and the route list updates; pick no map key and every route shows.
- The **日本語 / English** link in the top right switches the page's language. Switching languages resets the form to its defaults (it doesn't carry over your other picks).
- Selecting **English** narrows the map_key dropdown to `crows_landing`, `sunnyvale_office`, `usa_zone_10`, `walnut_creek`, and `shoreline_zone_10`. Selecting **日本語** shows the remaining map keys (`jp_tokyo`, `jp_zone_53`, `jp_zone_54`, `shirosato_zone_54`, `shirosato_reversed_zone_54`) and also pre-checks `enable_japan_driving` (you can still uncheck it).

## TUI

Run `./launch.sh` and answer each prompt with the arrow keys and Enter. Every screen after the first offers `<< Back` to return to the previous answer, and `Quit` to cancel immediately (Ctrl+C also quits).

Steps, in order:

1. **Language** — English or 日本語. This affects every later step's wording, plus the map_key list and the `enable_japan_driving` default (see below).
2. **Vehicle name** — a text prompt, not a dropdown. Type just the number (e.g. `807`) and it's assembled into `truck-807`. You can also type `back` or `quit` here instead of a number to navigate.
3. **Launch config** — a list of the 4 available configs. `sds_road_readiness` is listed first if you picked English; `etc_sds_road_readiness` is listed first if you picked 日本語.
4. **Map key** (optional) — narrowed to the same English/Japanese subset as the web UI. For English, `sunnyvale_office` and `usa_zone_10` are listed first; for 日本語, `jp_zone_53` and `jp_zone_54` are listed first.
5. **Route** (optional) — narrowed to whichever routes are tied to the map key you just picked (or all routes, if you picked none).
6. **Enable Japan driving mode?** — Yes/No. Defaults to **No** if you picked English, **Yes** if you picked 日本語 — either way, you can still pick the other answer.

At the end, the command prints to the terminal and is copied to your clipboard automatically (if your system clipboard is accessible).

### It remembers your last answers

Your vehicle number, launch config, and map key choices are saved to a local `.launch_state.json` file (not tracked in git) and pre-filled as the default the next time you run `./launch.sh` — so you can usually just press Enter through the prompts you don't want to change. Launch config and map key are remembered **separately per language** (an English run and a Japanese run each keep their own last pick). This only happens after you complete a full run; quitting partway through doesn't save anything.

## Editing the options

All the dropdown/prompt values live in `options.csv` — a single table with one row per option, and these columns:

| column | meaning |
| --- | --- |
| `field` | which list this row belongs to: `vehicle_name`, `launch_config`, `map_key`, or `route` |
| `value` | the actual value passed to `start_stack` (or, for `map_key`, the value routes tie themselves to) |
| `nickname` | optional friendly display name; leave blank to just show `value` as-is |
| `owner_map_key` | **routes only** — which `map_key` this route belongs to. A route only ever shows up once that exact map_key is selected; leave blank and the route never shows up for any specific map_key |
| `language` | **map keys only** — `en`, `ja`, or blank. Blank means the map_key shows up regardless of language |

To add a new option, just add a row. For example, a new route tied to `usa_zone_10`:

```
route,my_new_route,My Friendly Name,usa_zone_10,
```

No code changes needed — both the web UI and the TUI read this file fresh on every run.
