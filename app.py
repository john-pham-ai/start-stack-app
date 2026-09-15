import re

from flask import Flask, render_template_string, request

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
    <select name="route">
      <option value="">{{ t(lang, 'none_option') }}</option>
      {# Routes grouped by the map they belong to (routes carry their map,
         so the command needs no map flag — this is just visual grouping). #}
      {% set routes_by_owner = routes | groupby('owner') %}
      {% for owner, group in routes_by_owner %}
        {% if owner %}
          <optgroup label="{{ owner }}">
            {% for opt in group %}<option value="{{ opt.value }}" {% if opt.value == form.route %}selected{% endif %}>{{ opt.label }}</option>{% endfor %}
          </optgroup>
        {% else %}
          {% for opt in group %}<option value="{{ opt.value }}" {% if opt.value == form.route %}selected{% endif %}>{{ opt.label }}</option>{% endfor %}
        {% endif %}
      {% endfor %}
    </select>
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
</form>
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
    if request.method == "POST":
        action = request.form.get("action")
        if action == "remove_preset":
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
            form["route"] = request.form.get("route", "")
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
        form=form,
        command=command,
        lang=lang,
        t=t,
        presets=state.get("presets", {}),
        history=get_history(state, limit=10),
    )


if __name__ == "__main__":
    app.run(debug=True, port=5050)
