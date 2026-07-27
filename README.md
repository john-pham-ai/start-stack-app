# start_stack command builder

*[日本語版はこちら](README.ja.md)*

*New to this tool, or don't write code? See [GETTING_STARTED.md](GETTING_STARTED.md) — a plain-language walkthrough with screenshots.*

A small local tool for building the `start_stack` launch command without memorizing flags. It ships two interfaces that share the same options and logic:

- a **web UI** (Flask) you build the command in and copy out, and
- a **TUI** (terminal wizard) for driving it entirely from the command line.

Both build a command in this shape — one flag per line, with a trailing `\` so it still runs as a single command when pasted into a shell:

```
start_stack \
  --vehicle_name truck-807 \
  --launch_config sds_road_readiness \
  --map_key shirosato_zone_54 \
  --route shoreline_terminal_10kph \
  --enable_japan_driving
```

`map_key`, `route`, and `enable_japan_driving` are optional (they're left out of the command entirely if unset); `vehicle_name` and `launch_config` are always required.

## Setup

The first run needs a Python virtual environment with `flask`, `questionary`, and `pyperclip` installed. All three launcher scripts do this automatically — if `venv/` doesn't exist yet, they create it and run `pip install -r requirements.txt` before starting.

## Running it

From the project directory:

```
./run.sh        # web UI, then open http://127.0.0.1:5050
./launch.sh     # terminal wizard
./recorder.sh   # just the screen recorder, no command wizard
```

The first time you run `./launch.sh`, it also adds a `launch` alias to your shell config (`.zshrc` for zsh; `.bash_profile` on macOS or `.bashrc`/`.bash_aliases` on Linux for bash), so afterward you can just type `launch` from anywhere instead of `cd`-ing into this directory. `./recorder.sh` does the same for a `recorder` alias. Open a new terminal (or `source` the file it mentions) for either alias to take effect. If a script can't detect your shell, it prints the alias line to add yourself instead of guessing.

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

## Recording the screen

After the command is built and copied, you're asked whether to record the screen for this run. This needs `ffmpeg`; if it's not already installed, the wizard installs it for you automatically (via Homebrew on macOS, or apt/dnf/pacman on Linux — whichever it finds first). If none of those are available, or the install fails, recording is skipped and you're told to install `ffmpeg` yourself.

The whole thing is driven by single keypresses — no Enter needed except at the text prompts:

1. Press **`r`** to start recording, or **`q`** to skip it entirely.
2. Once started, the terminal shows a live `● Recording... 00:07 (press 's' to stop)` line that ticks up every second so you can tell it's actually running. Perform your test run, then press **`s`** to stop.
3. You're asked **keep or discard**: press **`k`** to keep it and continue, or **`d`** to throw it away — the file is deleted immediately and you're done, no naming prompts.
4. If you kept it, you're asked to paste a **run id** (optional — leave it blank to skip).
5. You're asked for a **Polarion test case id**. Type it, or:
   - `back` — re-enter the run id
   - `skip` (or just press Enter) — no test case id for this recording
6. The video is saved to `~/screen_recordings/<today's date>/`, named `<timestamp>_<vehicle_name>_run-<run id>_tc-<test case id>.mp4` (any part you skipped is left out of the name). A sidecar `.json` file with the same name holds the run id, test case id, the Polarion link, the `start_stack` command, and the recording's duration.
7. An **"Open recording folder"** link is printed right after — click it (in a terminal that supports clickable links, e.g. iTerm2, VS Code, kitty, recent Terminal.app) to jump straight to that dated folder in Finder. The plain folder path is also printed above it either way.

If you type `skip` at the test case prompt, that's remembered — the next recording defaults to `skip` too, so you don't have to keep re-declining it. Entering a real test case id switches the default back.

The Polarion link is built from a URL template in `recorder.py` (`POLARION_URL_TEMPLATE`, or the `POLARION_URL_TEMPLATE` env var) — edit it to point at your actual Polarion server; the placeholder won't resolve to anything real. You can also change where recordings are saved with the `RECORDINGS_DIR` env var (defaults to `~/screen_recordings`).

### Recording without the command wizard

If you just want to capture a recording without building a `start_stack` command first, run `./recorder.sh` (or type `recorder` once the alias is set up). It goes straight to the same `r` to start / `s` to stop / keep-or-discard / naming flow described above — the video just won't have a vehicle name in its filename. It shares the same remembered `skip`/last-test-case-id state as the full wizard.

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
