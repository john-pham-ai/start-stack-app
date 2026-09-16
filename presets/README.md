# Shared presets

Every `*.json` file in this directory is a **shared preset**: a route
setup one tester built, exported, and sent in to be committed here.
Once committed, every machine running start-stack-app picks it up
automatically — the app self-updates from this repo on launch, and
reads this directory fresh on every run. No re-typing, no hand-edits.

## How a preset gets here

1. A tester builds their command in the wizard (or web UI) and saves it
   as a preset.
2. **TUI:** start menu → **Export a preset to share** → pick it — an
   export file lands in `../exports/<name>.json`.
   **Web UI:** select the preset → **Export** — the browser downloads
   `<name>.json`.
3. They send that file to the repo owner (Slack, email, a PR — anything).
4. The file gets dropped into this directory as `presets/<name>.json`
   and committed + pushed. Done — every machine has it on next launch.

## File format

The JSON is the state-file shape plus sharing metadata:

```json
{
  "vehicle_name": "truck-807",
  "launch_config": "sds_road_readiness",
  "route": "shoreline_straight",
  "enable_japan_driving": false,
  "kind": "values",
  "exported_by": "jp",
  "exported_at": "2026-09-16T10:00:00"
}
```

Rules the loader enforces (anything else is skipped, not fatal):

- Only **values presets** can be shared — the four command fields above.
  Raw custom-command presets stay personal: the whole point is a route
  setup that rebuilds on any machine.
- The file name (minus `.json`) becomes the preset's name shown in the
  menus; names use letters, digits, spaces and dashes, up to 64 chars.
- `exported_by` / `exported_at` are optional provenance, kept but not
  shown in the UI.

## Precedence

A personal preset with the same name as a shared one **wins** on that
machine (listed first, no "(shared)" tag) — recreating a shared preset
locally is always safe and never touches the repo. Removing a preset
from the menu only ever removes the local copy; shared ones can only
be changed or removed here, in the repo.

The file `shoreline-slow-demo.json` in this directory is a working
example — importing what it exports reproduces it exactly.
