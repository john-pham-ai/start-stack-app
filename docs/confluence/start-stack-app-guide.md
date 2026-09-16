# start_stack command builder — User Guide

> **Confluence page source.** This Markdown is the readable version of the
> guide; `start-stack-app-guide.storage.xhtml` next to it is the same page in
> Confluence *storage format* — paste that into a new page via **⋯ → Insert →
> Markup (Confluence wiki / storage)** or the REST API, then attach the six
> videos from `docs/videos/` (each `<ac:image>` references them by file name).

---

## What it is

A small local tool that builds the `start_stack` launch command so nobody has
to memorize flags. Two interfaces share one set of options, presets and history:

- **TUI** — `./launch.sh` (or the `launch` alias): a keyboard-first wizard.
- **Web UI** — `./run.sh`, then open <http://127.0.0.1:5050>.

Both produce a command like:

```
start_stack \
  --vehicle_name truck-807 \
  --launch_config sds_road_readiness \
  --route shoreline_straight \
  --enable_japan_driving
```

and put it on your clipboard.

## Get the tool (once)

**Video:** `07-setup-clone.mp4`

**Repository: <https://github.com/john-pham-ai/start-stack-app>** — clone it, run
one script, and you're on the start menu. The tool then keeps itself up to date
from this repo, so cloning is a one-time step.

1. Clone:
   ```
   git clone https://github.com/john-pham-ai/start-stack-app.git
   cd start-stack-app
   ```
2. First run — builds the venv, installs dependencies, adds a `launch` alias (~1 min):
   ```
   ./launch.sh
   ```
3. Pick your language — you're on the start menu. Next time, just `launch` from
   anywhere; `./run.sh` for the web UI at <http://127.0.0.1:5050>.

**Requirements:** `git`, `python3` 3.10+ with `venv` (`sudo apt install python3-venv`
on Ubuntu if asked), GitHub access. Optional: a local `brain2` checkout at
`~/brain2` (or `BRAIN2_REPO_PATH`) as an offline fallback for the route list.

## The app keeps itself current

| What | How | Knob |
|---|---|---|
| **App code** | On launch the app fetches its own GitHub repo and fast-forwards when origin is ahead; new code runs on the *next* launch. A dirty tree is never clobbered (you'll see a note instead). | `APP_UPDATE=off` |
| **Routes / maps** | A routes-only sparse clone of `brain2` (`origin/master`) is kept in `~/.cache/start-stack-app/routes` and refreshed on launch (≤ once/min). Falls back to a local brain2 checkout, then to `options.csv`. | `ROUTES_SYNC=off` |
| **Shared presets** | Committed JSON files in the repo's `presets/` — arrive with the app update. | — |

---

## 1. The start menu & shortcut keys

**Video:** `01-start-menu-shortcuts.mp4`

After picking the language, every menu entry has a shortcut: **press the key,
then Enter**.

| Keys | Group |
|---|---|
| `1` `2` `3` … | Fixed entries (build, record-only, truck fetch, SSH setup, save-custom, build loop, import/export, quit) |
| `!` `@` `#` `$` `%` `^` `&` `*` `(` `)` | **Presets**, in save order (repo-shared ones are marked *(shared)*) |
| `Q` `W` `E` `R` | **Japan closed loops** (4 max — one key per loop) |
| `A` `S` `D` `F` | **Recent runs** — the last 4, at the bottom of the menu |

Picking a preset or a recent run prints the command, copies it, and offers to
record the screen (`r` to record, `q` to skip). The menu comes back after every
flow; only **Quit** exits.

## 2. Building a command

**Video:** `02-build-command.mp4`

1. **Language** — English or 日本語 (the whole UI is bilingual).
2. **Build a new command** (`1`).
3. **Vehicle** — type just the number: `807` → `truck-807`. Type `back`/`quit` to navigate.
4. **Launch config** — your last pick is pinned first; Enter takes it.
5. **Route** (optional) — see §3. Blank + Enter = no route.
6. **Japan driving** — Yes/No (defaults to Yes if you picked 日本語).

The command prints one flag per line (shell-pasteable) and is already on the
clipboard. Answer **Save these choices as a preset?** to keep it as a preset.

## 3. The route prompt (type to autofill)

**Video:** `03-route-autofill.mp4`

Type a few letters of a **route name or a map name** — both filter the 180+
routes live. **Tab** (or →) accepts the highlighted suggestion; ↑/↓ browse;
↓ on an empty line shows everything. Suggestions are titled `map — route`.
Routes carry their own map, so there is no separate map flag.

## 4. Closed-loop mileage mode (Japan)

**Video:** `04-closed-loop.mp4`

**Build a closed-loop mileage route (Japan)** (`6`) asks for the base command
(vehicle, launch config — Japan driving is forced on), then each **stop**
(a route) in driving order using the same autofill picker. Finish with a
blank line, `done`, or the *-- route done --* row; `back` removes the last stop.
Name it and it's saved (4 loops max → `Q`/`W`/`E`/`R`).

**Driving** a loop prints stop 1's command (copied), waits while you drive,
then stop 2 … after the last stop it wraps to stop 1 for another lap, until
you say the run is done. It reports full laps driven.

**Long runs resume where they left off:** a drive that ends mid-lap is
remembered per loop — the next drive of it offers to pick up at the stop
that was next (completed laps carried over). Declining starts fresh; a lap
completed at the wrap prompt clears the point.

**The drive records like a test run:** it opens with a recording offer
(`r` = one recording spans the whole drive, stopping itself when the run
ends; `q` = drive without one). Keeping it runs the usual close-out — the
**run-id pull from the truck** and the Polarion id — and the sidecar notes
the loop and its stops.

## 5. Presets: personal, shared, export & import

**Video:** `05-shared-presets.mp4`

- **Personal presets** are saved from the wizard/web form and live only on your machine.
- **Shared presets** live in the repo's `presets/` folder and appear on every machine, marked *(shared)*. They can't be removed from the menu (only from the repo).
- A personal preset with the same name as a shared one **wins** locally.

**Sharing your preset with the team:**

1. TUI: **Export a preset to share** → pick it → the file lands in `exports/<name>.json`.
   Web: select the preset → **Export** → the browser downloads `<name>.json`.
2. Send that file to the repo owner (Slack / email / PR).
3. Owner drops it into `presets/` and pushes. Everyone's app picks it up on next launch.

**Importing** a file someone sent *you*: TUI **Import a preset file** → path;
Web **Import a preset file** → choose file → **Import**. It becomes a personal preset.

Only *values* presets (vehicle / config / route / Japan toggle) can be shared —
raw custom-command presets stay personal.

## 6. The web UI

**Video:** `06-web-ui.mp4`

Same options, presets and history as the TUI, in the browser. The route box is
a **combobox**: click for the full list grouped by map, type to filter, click or
↑/↓ + Enter to pick. **Build command** shows the command (auto-copied). Presets
load/remove/export from the dropdown; the import form takes a `.json` file.

## 7. Truck helpers & screen recording

- **Fetch the latest Run ID from the truck** (`3`) — SSHes to the cabled truck, copies the newest run id.
- **Set up SSH for a truck** (`4`) — one-time per truck: identity + alias named after the truck number.
- **Record the screen** — offered after every command (`r` / `q`), or standalone via **Record the screen only** (`2`) / `./recorder.sh`. Keep/discard, then a run-id and Polarion test-case id name the file.

## Environment knobs

| Variable | Default | Purpose |
|---|---|---|
| `APP_UPDATE` | on | `off` skips the self-update check |
| `ROUTES_SYNC` | on | `off` skips the GitHub routes sync (use local checkout) |
| `ROUTES_REMOTE_URL` / `ROUTES_BRANCH` | brain2 / `master` | where routes sync from |
| `ROUTES_CACHE_DIR` | `~/.cache/start-stack-app/routes` | routes cache location |
| `BRAIN2_REPO_PATH` | `~/brain2` | local checkout fallback |
| `TRUCK_SSH_TARGET` | `applied@192.168.1.11` | truck SSH destination |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `(start-stack-app <hash> is available — commit or stash…)` | You have local edits; `git stash` or commit them, relaunch. |
| Routes look stale / missing | Check network; `rm -rf ~/.cache/start-stack-app/routes` forces a fresh clone. Or `git pull` in `~/brain2` and run with `ROUTES_SYNC=off`. |
| A shared preset doesn't appear | Its file was skipped as malformed — the TUI prints a note; ask the repo owner to fix `presets/<name>.json`. |
| "Loops are full" | 4 loops max; **Remove a saved loop** first. |
| Truck fetch fails: *could not reach the truck* | Check the cable/network; run **Set up SSH for a truck** once per truck. |

---

*Videos are generated from the real app by `tools/make_videos.py` — rerun it after UI changes so the guide never drifts.*
