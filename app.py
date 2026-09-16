import re

from flask import Flask, render_template_string, request

import truck
from stack_options import build_command, load_options
from state import (
    CUSTOM_PRESET,
    command_entry_values,
    command_values,
    delete_preset,
    get_history,
    load_preset,
    load_state,
    normalize_custom_command,
    preset_kind,
    remember_command,
    save_custom_preset,
    save_preset,
    save_state,
)
from translations import t

app = Flask(__name__)

VEHICLE_NUMBER_RE = re.compile(r"^\d+$")

PAGE = """
<!doctype html>
<title>{{ t(lang, 'title') }}</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; }
  label { display: block; margin-top: 12px; font-weight: 600; }
  select, input[type=text], input[type=checkbox] { margin-top: 4px; }
  input[type=text] { width: 240px; }
  .combobox { position: relative; width: 340px; }
  .combobox input { width: 100%; box-sizing: border-box; }
  .combobox-list { display: none; position: absolute; top: 100%; left: 0; right: 0; max-height: 280px; overflow-y: auto; background: #fff; border: 1px solid #ccc; border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,.15); z-index: 20; margin-top: 2px; }
  .combobox-list.open { display: block; }
  .combobox-group { padding: 6px 12px 2px; font-size: 0.8em; font-weight: 700; color: #666; }
  .combobox-item { padding: 6px 12px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .combobox-item:hover, .combobox-item.active { background: #eef; }
  .combobox-empty { padding: 8px 12px; color: #999; }
  pre { background: #222; color: #eee; padding: 12px; border-radius: 6px; overflow-x: auto; margin-bottom: 8px; }
  button { margin-top: 8px; padding: 8px 16px; }
  .lang-switch { float: right; font-weight: normal; }
  .command-block { margin-top: 24px; }
  .history-meta { color: #666; font-size: 0.85em; margin-top: 8px; }
</style>
<a class="lang-switch" href="?lang={{ 'ja' if lang == 'en' else 'en' }}">{{ t(lang, 'switch_language') }}</a>
<h1>{{ t(lang, 'title') }}</h1>
{% if presets %}
<form method="post" class="preset-form">
  <input type="hidden" name="lang" value="{{ lang }}">
  <label>{{ t(lang, 'preset_label') }}
    <select id="preset-load" name="preset_name">
      <option value="">--</option>
      {% for name, entry in presets.items() %}<option value="{{ name }}">{{ name }}{% if entry.get('kind') == 'command' %} {{ t(lang, 'custom_tag') }}{% endif %}</option>{% endfor %}
    </select>
  </label>
  <button type="submit" name="action" value="load_preset" id="load-preset-btn" disabled>{{ t(lang, 'load_preset') }}</button>
  <button type="submit" name="action" value="remove_preset" id="remove-preset-btn" disabled>{{ t(lang, 'remove_preset') }}</button>
</form>
{% endif %}
<form method="post">
  <input type="hidden" name="lang" value="{{ lang }}">
  <label>{{ t(lang, 'vehicle_name') }}
    <input type="text" name="vehicle_name" list="vehicle-options" value="{{ form.vehicle_name }}">
    <datalist id="vehicle-options">
      {% for opt in options.vehicle_name %}<option value="{{ opt.value }}">{{ opt.label }}</option>{% endfor %}
    </datalist>
  </label>
  <label>{{ t(lang, 'launch_config') }}
    <select name="launch_config">
      {% for opt in options.launch_config %}<option value="{{ opt.value }}" {% if opt.value == form.launch_config %}selected{% endif %}>{{ opt.label }}</option>{% endfor %}
    </select>
  </label>
  <label>{{ t(lang, 'route') }}
    {# A combobox: click to see every route grouped by map, or type a few
       letters (route or map name) to filter. The hidden input carries the
       chosen route's value; the visible one is the search/display box.
       Routes carry their map, so the command needs no map flag — the
       grouping is just visual. #}
    <div class="combobox" id="route-box">
      <input type="text" id="route-input" autocomplete="off"
             placeholder="{{ t(lang, 'route_placeholder') }}" value="{{ route_label }}">
      <input type="hidden" name="route" id="route-value" value="{{ form.route }}">
      <div class="combobox-list" id="route-list"></div>
    </div>
  </label>
  <label><input type="checkbox" name="enable_japan_driving" {% if form.enable_japan_driving %}checked{% endif %}> {{ t(lang, 'enable_japan_driving') }}</label>
  <button type="submit" name="action" value="build">{{ t(lang, 'build_command') }}</button>
  <label>{{ t(lang, 'preset_name_label') }}
    <input type="text" name="preset_name">
  </label>
  <button type="submit" name="action" value="save_preset">{{ t(lang, 'save_as_preset') }}</button>
  <label>{{ t(lang, 'custom_command_label') }}
    <textarea name="custom_command" rows="2" cols="60"></textarea>
  </label>
  <button type="submit" name="action" value="save_custom_preset">{{ t(lang, 'save_custom_preset') }}</button>
  <label>{{ t(lang, 'truck_fetch_btn') }}</label>
  <button type="submit" name="action" value="truck_run">{{ t(lang, 'truck_fetch_btn') }}</button>
  <button type="submit" name="action" value="truck_ssh_setup">{{ t(lang, 'truck_setup_btn') }}</button>
</form>
{% if truck_result %}
  <div class="command-block">
    <h3>{{ t(lang, 'truck_run_heading') }}</h3>
    <pre id="truck-run-id">{{ truck_result.run_id }}</pre>
    <button type="button" class="copy-btn">{{ t(lang, 'copy_to_clipboard') }}</button>
    <span class="copy-status"></span>
    <div class="history-meta">{{ truck_result.hostname }} — {{ truck_result.path }}{% if truck_result.warning %} — ⚠️ {{ truck_result.warning }}{% endif %}</div>
  </div>
{% endif %}
{% if truck_error %}
  <div class="command-block">
    <h3>{{ t(lang, 'truck_run_heading') }}</h3>
    <p>{{ truck_error }}</p>
  </div>
{% endif %}
{% if truck_setup %}
  <div class="command-block">
    <h3>{{ t(lang, 'truck_setup_heading') }}</h3>
    <p>{{ truck_setup.alias }}: identity {{ 'created' if truck_setup.key_created else 'already existed' }} ({{ truck_setup.key_path }}),
       config block {{ 'added' if truck_setup.config_added else 'already existed' }}.</p>
    {% if truck_setup.key_installed %}
      <p>✅ {{ t(lang, 'truck_setup_installed') }} — {{ truck_setup.install_detail }}.</p>
    {% else %}
      <p>⚠️ {{ truck_setup.install_detail }}</p>
      <pre>{{ truck_setup.next_step }}</pre>
      <button type="button" class="copy-btn">{{ t(lang, 'copy_to_clipboard') }}</button>
      <span class="copy-status"></span>
    {% endif %}
  </div>
{% endif %}
{% if truck_setup_error %}
  <div class="command-block">
    <h3>{{ t(lang, 'truck_setup_heading') }}</h3>
    <p>{{ truck_setup_error }}</p>
  </div>
{% endif %}
{% if command %}
  <div class="command-block">
    <h3>{{ t(lang, 'command_heading') }}</h3>
    <pre id="command">{{ command }}</pre>
    <button type="button" class="copy-btn">{{ t(lang, 'copy_to_clipboard') }}</button>
    <span class="copy-status"></span>
  </div>
{% endif %}
{% if history %}
  <div class="command-block">
    <h3>{{ t(lang, 'recent_heading') }}</h3>
    {% for entry in history %}
    <div class="command-block history-item">
      <div class="history-meta">{{ entry.built_at }}{% if entry.vehicle_name %} — {{ entry.vehicle_name }} · {{ entry.launch_config }}{% if entry.route %} · {{ entry.route }}{% endif %}{% elif entry.command %} — {{ entry.command[:60] }}{% endif %}</div>
      <pre>{{ entry.command }}</pre>
      <button type="button" class="copy-btn">{{ t(lang, 'copy_to_clipboard') }}</button>
      <span class="copy-status"></span>
    </div>
    {% endfor %}
  </div>
{% endif %}
<script>
  (function () {
    // The load/remove buttons enable once a preset is actually selected.
    // Loading itself is server-side: it builds (or shows verbatim) the
    // command, and the copy script below auto-copies it on page load.
    var presetSelect = document.getElementById("preset-load");
    var loadBtn = document.getElementById("load-preset-btn");
    var removeBtn = document.getElementById("remove-preset-btn");
    if (presetSelect) {
      presetSelect.addEventListener("change", function () {
        var empty = !presetSelect.value;
        if (loadBtn) loadBtn.disabled = empty;
        if (removeBtn) removeBtn.disabled = empty;
      });
    }
  })();

  (function () {
    // Route combobox: focus/click shows the entire list grouped by map;
    // typing filters it (route name, value, or map name all match); a
    // click or arrow-keys + Enter picks. The hidden input carries the
    // picked route's value; the visible input is the search box.
    var ROUTES = {{ routes_data | tojson }};
    var NONE_LABEL = {{ t(lang, 'none_option') | tojson }};
    var box = document.getElementById("route-box");
    var input = document.getElementById("route-input");
    var hidden = document.getElementById("route-value");
    var list = document.getElementById("route-list");
    if (!box) return;

    var active = -1;       // highlighted index into visibleRows
    var visibleRows = [];  // {el, route} for the currently rendered rows

    function matches(route, text) {
      if (!text) return true;
      text = text.toLowerCase();
      return (route.l + "\n" + route.v + "\n" + route.o).toLowerCase().indexOf(text) !== -1;
    }

    function close() {
      list.classList.remove("open");
      active = -1;
    }

    function pick(route) {
      hidden.value = route ? route.v : "";
      input.value = route ? route.l : "";
      close();
    }

    function highlight(i) {
      if (active >= 0 && visibleRows[active]) visibleRows[active].el.classList.remove("active");
      active = i;
      if (i >= 0 && visibleRows[i]) {
        var el = visibleRows[i].el;
        el.classList.add("active");
        el.scrollIntoView({ block: "nearest" });
      }
    }

    function addRow(route, title) {
      var el = document.createElement("div");
      el.className = "combobox-item";
      el.textContent = title;
      if (route) el.title = route.v;
      // mousedown (not click) so the input keeps focus through the pick.
      el.addEventListener("mousedown", function (e) {
        e.preventDefault();
        pick(route);
      });
      list.appendChild(el);
      visibleRows.push({ el: el, route: route });
    }

    function render() {
      var text = input.value.trim();
      list.textContent = "";
      visibleRows = [];
      active = -1;

      addRow(null, NONE_LABEL);

      var groups = {};
      var order = [];
      ROUTES.forEach(function (r) {
        if (!matches(r, text)) return;
        if (!groups[r.o]) { groups[r.o] = []; order.push(r.o); }
        groups[r.o].push(r);
      });
      order.sort();
      var shown = 0;
      order.forEach(function (owner) {
        if (owner) {
          var head = document.createElement("div");
          head.className = "combobox-group";
          head.textContent = owner;
          list.appendChild(head);
        }
        groups[owner].forEach(function (r) { addRow(r, r.l); shown += 1; });
      });

      if (!shown) {
        var empty = document.createElement("div");
        empty.className = "combobox-empty";
        empty.textContent = "—";
        list.appendChild(empty);
      }
      list.classList.add("open");
    }

    input.addEventListener("focus", render);
    input.addEventListener("input", function () {
      hidden.value = "";  // typing invalidates any earlier pick
      render();
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { close(); return; }
      if (!list.classList.contains("open")) {
        if (e.key === "ArrowDown") { render(); highlight(0); e.preventDefault(); }
        return;
      }
      if (e.key === "ArrowDown") {
        highlight(Math.min(active + 1, visibleRows.length - 1));
        e.preventDefault();
      } else if (e.key === "ArrowUp") {
        highlight(Math.max(active - 1, 0));
        e.preventDefault();
      } else if (e.key === "Enter") {
        if (active >= 0 && visibleRows[active]) { pick(visibleRows[active].route); e.preventDefault(); }
        // No row highlighted: let the form submit — the submit handler
        // below resolves typed text against the list first.
      }
    });
    document.addEventListener("click", function (e) {
      if (!box.contains(e.target)) close();
    });

    // Submit-time resolution: if nothing was picked from the list, exact
    // typed text still counts when it equals a route's value or label.
    var form = input.closest("form");
    form.addEventListener("submit", function () {
      if (hidden.value) return;
      var text = input.value.trim().toLowerCase();
      if (!text) return;
      for (var i = 0; i < ROUTES.length; i++) {
        var r = ROUTES[i];
        if (r.v.toLowerCase() === text || r.l.toLowerCase() === text) {
          hidden.value = r.v;
          input.value = r.l;
          return;
        }
      }
      // Unmatched text: treat it as no route (the server does the same).
      input.value = "";
    });
  })();

  (function () {
    var STR_COPIED = {{ t(lang, 'copied') | tojson }};
    var STR_COPY_FAILED = {{ t(lang, 'copy_failed') | tojson }};

    function copyText(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text);
      }
      var textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      return Promise.resolve();
    }

    document.querySelectorAll(".copy-btn").forEach(function (btn) {
      var block = btn.closest(".command-block");
      var pre = block ? block.querySelector("pre") : null;
      var status = block ? block.querySelector(".copy-status") : null;
      if (!pre) return;

      function showStatus(message) {
        if (status) {
          status.textContent = message;
          setTimeout(function () { status.textContent = ""; }, 2000);
        }
      }

      btn.addEventListener("click", function () {
        copyText(pre.textContent).then(function () {
          showStatus(STR_COPIED);
        }).catch(function () {
          showStatus(STR_COPY_FAILED);
        });
      });

      // Best-effort auto-copy of the freshly built command on page load.
      // Browsers may silently block this since it isn't tied to a direct
      // user gesture on this page.
      if (pre.id === "command") {
        copyText(pre.textContent).then(function () {
          showStatus(STR_COPIED);
        }).catch(function () {});
      }
    });
  })();
</script>
"""


def normalize_vehicle_name(value):
    """Accept either a full name ("truck-807") or just the number ("807")."""
    value = (value or "").strip()
    if VEHICLE_NUMBER_RE.match(value):
        return f"truck-{value}"
    return value


def normalize_route(options, value):
    """Accept a route value or its display label; unknown text becomes "".

    The combobox normally submits a picked route's value, but typed text
    that exactly matches a label ("Shoreline Terminal - Slow") is also
    accepted. Anything else is treated as no route — a garbage --route
    would just make the built command invalid.
    """
    value = (value or "").strip()
    if not value:
        return ""
    for opt in options["route"]:
        if opt.value == value:
            return opt.value
    lowered = value.lower()
    for opt in options["route"]:
        if opt.label.lower() == lowered:
            return opt.value
    return ""


def route_label_for(options, value):
    """The display label for a route value ("" when unknown/empty)."""
    for opt in options["route"]:
        if opt.value == value:
            return opt.label
    return ""


@app.route("/", methods=["GET", "POST"])
def index():
    options = load_options()
    state = load_state()
    lang = request.values.get("lang", "en")
    if lang not in ("en", "ja"):
        lang = "en"
    form = {
        "vehicle_name": options["vehicle_name"][0].value,
        "launch_config": options["launch_config"][0].value,
        "route": "",
        "enable_japan_driving": lang == "ja",
    }
    command = None
    truck_result = None
    truck_error = None
    truck_setup = None
    truck_setup_error = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "truck_run":
            # The fetch identifies the truck by its hostname; the vehicle
            # picked in the form is only a cross-check (mismatch -> warning).
            vehicle = normalize_vehicle_name(request.form.get("vehicle_name", ""))
            number = vehicle[len("truck-"):] if vehicle.startswith("truck-") and vehicle[len("truck-"):].isdigit() else ""
            try:
                truck_result = truck.fetch_run_id(number)
            except truck.TruckError as err:
                truck_error = t(lang, "truck_error_prefix") + " " + str(err)
        elif action == "truck_ssh_setup":
            # The identity and alias are forced to the truck number from the
            # form's vehicle field.
            vehicle = normalize_vehicle_name(request.form.get("vehicle_name", ""))
            number = vehicle[len("truck-"):] if vehicle.startswith("truck-") and vehicle[len("truck-"):].isdigit() else ""
            try:
                if not number:
                    raise truck.TruckError(
                        "Enter the truck number in the vehicle field first — the SSH "
                        "identity and alias are named after it."
                    )
                truck_setup = truck.setup_ssh(number)
            except truck.TruckError as err:
                truck_setup_error = t(lang, "truck_error_prefix") + " " + str(err)
        elif action == "remove_preset":
            # The preset form carries no command fields, so it just deletes
            # (and re-renders) rather than building anything.
            delete_preset(state, request.form.get("preset_name", ""))
            save_state(state)
        elif action == "save_custom_preset":
            # A raw command saved verbatim; the normalizer strips shell-prompt
            # and line-continuation paste artifacts.
            custom = normalize_custom_command(request.form.get("custom_command", ""))
            save_custom_preset(state, request.form.get("preset_name"), custom)
            save_state(state)
        elif action == "load_preset":
            # Using a preset means the command comes out right away — values
            # presets get built, custom presets are shown verbatim — and the
            # copy script auto-copies it on page load. No re-walking the form.
            entry = load_preset(state, request.form.get("preset_name", "")) or {}
            if preset_kind(entry) == CUSTOM_PRESET:
                command = entry["command"]
                remember_command(state, command_entry_values(command), command, custom=True)
            elif entry:
                values = command_values(entry)
                form.update(values)
                command = build_command(
                    vehicle_name=values["vehicle_name"],
                    launch_config=values["launch_config"],
                    route=values["route"],
                    enable_japan_driving=values["enable_japan_driving"],
                )
                remember_command(state, values, command)
            save_state(state)
        else:  # build / save_preset
            form["vehicle_name"] = normalize_vehicle_name(request.form.get("vehicle_name", ""))
            form["launch_config"] = request.form.get("launch_config", "")
            form["route"] = normalize_route(options, request.form.get("route", ""))
            form["enable_japan_driving"] = "enable_japan_driving" in request.form
            command = build_command(
                vehicle_name=form["vehicle_name"],
                launch_config=form["launch_config"],
                route=form["route"],
                enable_japan_driving=form["enable_japan_driving"],
            )
            remember_command(state, form, command)
            if action == "save_preset":
                save_preset(state, request.form.get("preset_name"), form)
            save_state(state)
    return render_template_string(
        PAGE,
        options=options,
        routes=options["route"],
        # The combobox needs the routes as {v, l, o} JSON (value/label/map).
        routes_data=[
            {"v": opt.value, "l": opt.label, "o": opt.owner} for opt in options["route"]
        ],
        route_label=route_label_for(options, form["route"]),
        form=form,
        command=command,
        truck_result=truck_result,
        truck_error=truck_error,
        truck_setup=truck_setup,
        truck_setup_error=truck_setup_error,
        lang=lang,
        t=t,
        presets=state.get("presets", {}),
        history=get_history(state, limit=10),
    )


if __name__ == "__main__":
    app.run(debug=True, port=5050)
