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
  --route shoreline_terminal_10kph \
  --enable_japan_driving
```

`route` and `enable_japan_driving` are optional (they're left out of the command entirely if unset); `vehicle_name` and `launch_config` are always required. There's no `--map_key` flag and no map picker — routes carry their map, so `--route` alone is enough (a route name used by more than one map is emitted as `map_name:route_name`). In the UIs, the route list is grouped by map instead, so you still see which map each route belongs to.

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

- The **vehicle name** is a text box with suggestions — start typing (either `807` or `truck-807` works) or click it to pick from the list. A bare number is assembled into `truck-<number>` for you.
- The **route** dropdown lists every route, grouped by the map it belongs to (routes carry their map — see [Where the options come from](#where-the-options-come-from) below — so there's no separate map picker).
- The **日本語 / English** link in the top right switches the page's language. Switching languages resets the form to its defaults (it doesn't carry over your other picks), and selecting **日本語** pre-checks `enable_japan_driving` (you can still uncheck it).
- If you've saved any **presets**, a dropdown above the form with a **Load** button uses one immediately: values presets get built into a command, custom command presets are shown verbatim, and the page auto-copies the result to your clipboard — no re-walking the form. Pick one and click **Remove a preset** to delete it (both buttons enable once a preset is selected). In the main form, type a name and click **Save as preset** to save the currently picked values, or paste any raw command into the **Custom command** box and click **Save a custom command as a preset**.
- **Recent commands** lists the last commands you built (from either the web UI or the TUI — they share one history), each with its own copy button, so re-copying an earlier command never means re-walking the form.

## TUI

Run `./launch.sh` and answer each prompt with the arrow keys and Enter. Every screen after the first offers `<< Back` to return to the previous answer, and `Quit` to cancel immediately (Ctrl+C also quits).

Steps, in order:

1. **Language** — English or 日本語. This affects every later step's wording plus the `enable_japan_driving` default (see below).
2. **What do you want to do?** — always shown. **Build a new command** walks the full wizard; **Record the screen only** jumps straight into recording (the same flow `./recorder.sh` runs, in the language you just picked); **Fetch the latest Run ID from the truck** grabs the newest run id off the cabled truck (see [Fetch the latest Run ID from the truck](#fetch-the-latest-run-id-from-the-truck)), puts it on your clipboard, and brings the menu back; **Save a custom command as a preset** stores any raw command — one you didn't build here — under a name for verbatim reuse (leading `$` prompts and the multi-line `\` form are cleaned up automatically); saved presets and recent commands join the menu once they exist, for one-step rebuilds — picking one prints the command, puts it on your clipboard, and exits: no wizard steps, no further prompts (the recording offer belongs to hand-built commands and the record-only entry); **Remove a preset** (shown once you have presets) picks one, confirms, and deletes it — then brings the menu back. Values that no longer exist in the current options (e.g. a route brain2 no longer has) are dropped with a note.
3. **Vehicle name** — type to search: start entering a number and the matching trucks show up as suggestions. Type just the number (e.g. `807`) and it's assembled into `truck-807`. You can also type `back` or `quit` here instead of a number to navigate.
4. **Launch config** — a list of the 4 available configs. `sds_road_readiness` is listed first if you picked English; `etc_sds_road_readiness` is listed first if you picked 日本語.
5. **Route** (optional) — every available route, sorted by map. A route name used by more than one map shows up as `route_name (map_name)` so the duplicates stay tellable apart.
6. **Enable Japan driving mode?** — Yes/No. Defaults to **No** if you picked English, **Yes** if you picked 日本語 — either way, you can still pick the other answer.

At the end, the command prints to the terminal and is copied to your clipboard automatically (if your system clipboard is accessible). For hand-built commands you're then asked whether to **save the choices as a preset** — give it a name and you can rebuild it in one step next time.

### It remembers your last answers

Your vehicle number and launch config are saved to a local `.launch_state.json` file (not tracked in git) and pre-filled as the default the next time you run `./launch.sh` — so you can usually just press Enter through the prompts you don't want to change. Launch config is remembered **separately per language** (an English run and a Japanese run each keep their own last pick). The same file also holds your **presets** and the last 20 **built commands**, which is how the presets/recent-commands shortcuts (and the web UI's preset and history sections) persist. This only happens after you complete a full run; quitting partway through doesn't save anything.

## Recording the screen

After the command is built and copied, you're asked whether to record the screen for this run. What happens under the hood depends on the machine — the right capture tool is picked automatically:

| machine | capture tool |
| --- | --- |
| macOS | ffmpeg's `avfoundation` |
| Linux, X11 | ffmpeg's `x11grab` |
| Linux, Wayland (KDE/GNOME) | `gpu-screen-recorder` |
| Linux, Wayland (Sway/Hyprland and other wlroots compositors) | `wf-recorder` |

Whatever's missing gets installed automatically when a supported package manager is around (Homebrew on macOS; apt/dnf/pacman on Linux — so both Debian and Arch work out of the box). If the auto-install fails (e.g. `gpu-screen-recorder` isn't packaged for your distro), recording is skipped and you're told exactly what to install and how. On Linux Wayland the first recording per machine may pop a screen-share approval dialog — approve it and the recording starts.

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

If you just want to capture a recording without building a `start_stack` command first, pick **Record the screen only** on the wizard's first menu — or run `./recorder.sh` (or type `recorder` once the alias is set up). Both go straight to the same `r` to start / `s` to stop / keep-or-discard / naming flow described above, in your chosen language for the wizard route — the video just won't have a vehicle name in its filename. They share the same remembered `skip`/last-test-case-id state as the full wizard.

## Fetch the latest Run ID from the truck

With the laptop cabled to a test truck, any of the three interfaces can grab the newest run id straight off the truck's log disk:

- the standalone script — `./truck.sh [vehicle]`, or just `truck` from anywhere once the alias is set up (added automatically on first run, same as `launch`/`recorder`). It prints the run id, the full log path and the truck's hostname, and exits 1 with a readable error when the truck is unreachable.
- the TUI wizard — **Fetch the latest Run ID from the truck** on the start menu prints the same information, puts the run id on your clipboard, and returns you to the menu.
- the web UI — the **Fetch Run ID from truck** button under the form (the vehicle in the form field is a cross-check; the fetched run id shows up with a copy button).

The truck this works against is the one the SSH target points at (`applied@192.168.1.11` by default) — the truck identifies itself by hostname (`truck-805-primarypc`), so the fetch knows which vehicle it's connected to. The log layout is `/media/hotswap1/frontier/truck-<N>/<year>/<month>/<day>/<run_id>`, and the newest run of the truck's *today* is preferred — if there's none yet today, the newest overall is used with a visible warning.

Under the hood it runs the same fixed, read-only `ls | sort | tail -1` script over your own system `ssh` (`BatchMode=yes`, so it never prompts) that the Master Checklist app's fetch button uses — your `~/.ssh` keys do the authenticating, nothing from the UI ever reaches a shell, and the whole round trip is capped at 10 seconds.

| env var | default | purpose |
| --- | --- | --- |
| `TRUCK_SSH_TARGET` | `applied@192.168.1.11` | SSH destination for the cabled truck |
| `TRUCK_LOG_ROOT` | `/media/hotswap1/frontier` | root of the on-truck log tree |
| `TRUCK_SSH_BIN` | `ssh` | SSH binary to invoke (test hook for a fake `ssh`) |

`python3 truck.py [vehicle] [--json]` is the underlying CLI — `--json` prints machine-readable output (errors included, with exit code 1). `truck.py` is pure stdlib, so it runs without the venv.

## Where the options come from

- **Vehicles and launch configs** always come from `options.csv` (see [Editing the options](#editing-the-options) below).
- **Routes** are scanned live from a brain2 checkout when one is available: every `onroad/config/constants/behavior/routes/**/*.txtpb` file (recursively, so route files for every map are picked up however they're organized) is read for its `identifier { map_name, route_name }` pairs, so the list can never go stale against brain2. Each route carries its map for grouping in the UI. Point the tool at your checkout with the `BRAIN2_REPO_PATH` env var (defaults to trying `~/brain2` and `~/Projects/brain2`).
- When no checkout is found, the tool **falls back to the `route` rows in `options.csv`** instead of failing — that's the CSV's fallback role.
- Either way, the CSV's route rows still contribute their `nickname` column to any live-scanned route they match, so curated labels ("Shoreline Terminal - Slow") survive the merge.

## Editing the options

All the vehicle/config dropdown values live in `options.csv` — a single table with one row per option, and these columns:

| column | meaning |
| --- | --- |
| `field` | which list this row belongs to: `vehicle_name`, `launch_config`, or `route` (route rows act as the brain2 fallback plus nickname overrides — see above) |
| `value` | the actual value passed to `start_stack` |
| `nickname` | optional friendly display name; leave blank to just show `value` as-is |
| `owner_map_key` | **routes only** — which map this route belongs to, used to group the route list in the UI |

To add a new vehicle or config, just add a row. For example:

```
vehicle_name,truck-831,
```

No code changes needed — both the web UI and the TUI read this file fresh on every run. Routes, though, don't need a CSV edit at all — they come from brain2 (see [Where the options come from](#where-the-options-come-from)).

## Tests

```
./venv/bin/pip install -r requirements-dev.txt
./venv/bin/python -m pytest
```

Covers the command builder, options loading (including the brain2 live scan, its CSV fallback, and the nickname overlay), state/history/presets, the recorder's capture-backend detection and filename/sidecar helpers, the truck run-id fetch (script construction, output parsing, and the ssh round trip against a fake `ssh` binary), an end-to-end drive of the TUI wizard with mocked prompts, and the web UI via Flask's test client.
