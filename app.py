from flask import Flask, render_template_string, request

from stack_options import build_command, load_options
from translations import t

app = Flask(__name__)

PAGE = """
<!doctype html>
<title>{{ t(lang, 'title') }}</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; }
  label { display: block; margin-top: 12px; font-weight: 600; }
  select, input[type=checkbox] { margin-top: 4px; }
  pre { background: #222; color: #eee; padding: 12px; border-radius: 6px; overflow-x: auto; }
  button { margin-top: 20px; padding: 8px 16px; }
  .lang-switch { float: right; font-weight: normal; }
</style>
<a class="lang-switch" href="?lang={{ 'ja' if lang == 'en' else 'en' }}">{{ t(lang, 'switch_language') }}</a>
<h1>{{ t(lang, 'title') }}</h1>
<form method="post">
  <input type="hidden" name="lang" value="{{ lang }}">
  <label>{{ t(lang, 'vehicle_name') }}
    <select name="vehicle_name">
      {% for opt in options.vehicle_name %}<option value="{{ opt.value }}" {% if opt.value == form.vehicle_name %}selected{% endif %}>{{ opt.label }}</option>{% endfor %}
    </select>
  </label>
  <label>{{ t(lang, 'launch_config') }}
    <select name="launch_config">
      {% for opt in options.launch_config %}<option value="{{ opt.value }}" {% if opt.value == form.launch_config %}selected{% endif %}>{{ opt.label }}</option>{% endfor %}
    </select>
  </label>
  <label>{{ t(lang, 'map_key') }}
    <select name="map_key" id="map_key">
      <option value="">{{ t(lang, 'none_option') }}</option>
      {% for opt in options.map_key %}<option value="{{ opt.value }}" {% if opt.value == form.map_key %}selected{% endif %}>{{ opt.label }}</option>{% endfor %}
    </select>
  </label>
  <label>{{ t(lang, 'route') }}
    <select name="route" id="route">
      <option value="">{{ t(lang, 'none_option') }}</option>
      {% for opt in options.route %}<option value="{{ opt.value }}" {% if opt.value == form.route %}selected{% endif %}>{{ opt.label }}</option>{% endfor %}
    </select>
  </label>
  <label><input type="checkbox" name="enable_japan_driving" {% if form.enable_japan_driving %}checked{% endif %}> {{ t(lang, 'enable_japan_driving') }}</label>
  <label><input type="checkbox" name="local" {% if form.local %}checked{% endif %}> {{ t(lang, 'local') }}</label>
  <button type="submit">{{ t(lang, 'build_command') }}</button>
</form>
{% if command %}
  <h3>{{ t(lang, 'command_heading') }}</h3>
  <pre id="command">{{ command }}</pre>
  <button type="button" id="copy-btn">{{ t(lang, 'copy_to_clipboard') }}</button>
  <span id="copy-status"></span>
{% endif %}
<script>
  (function () {
    var mapSelect = document.getElementById("map_key");
    var routeSelect = document.getElementById("route");
    var allRouteOptions = Array.prototype.slice.call(routeSelect.options);

    function applyFilter() {
      var mapKey = mapSelect.value;
      var matching = allRouteOptions.filter(function (opt) {
        return opt.value !== "" && opt.value.indexOf(mapKey) === 0;
      });
      var visible = mapKey && matching.length ? matching : allRouteOptions;
      var previousValue = routeSelect.value;

      routeSelect.innerHTML = "";
      allRouteOptions.forEach(function (opt) {
        if (opt.value === "" || visible.indexOf(opt) !== -1) {
          routeSelect.appendChild(opt);
        }
      });

      if (visible.some(function (opt) { return opt.value === previousValue; })) {
        routeSelect.value = previousValue;
      } else {
        routeSelect.value = "";
      }
    }

    mapSelect.addEventListener("change", applyFilter);
    applyFilter();
  })();

  (function () {
    var commandEl = document.getElementById("command");
    var copyBtn = document.getElementById("copy-btn");
    var status = document.getElementById("copy-status");
    if (!commandEl || !copyBtn) return;

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

    function showStatus(message) {
      status.textContent = message;
      setTimeout(function () { status.textContent = ""; }, 2000);
    }

    copyBtn.addEventListener("click", function () {
      copyText(commandEl.textContent).then(function () {
        showStatus(STR_COPIED);
      }).catch(function () {
        showStatus(STR_COPY_FAILED);
      });
    });

    // Best-effort auto-copy on page load. Browsers may silently block this
    // since it isn't tied to a direct user gesture on this page.
    copyText(commandEl.textContent).then(function () {
      showStatus(STR_COPIED);
    }).catch(function () {});
  })();
</script>
"""


@app.route("/", methods=["GET", "POST"])
def index():
    options = load_options()
    lang = request.values.get("lang", "en")
    if lang not in ("en", "ja"):
        lang = "en"
    form = {
        "vehicle_name": options["vehicle_name"][0].value,
        "launch_config": options["launch_config"][0].value,
        "map_key": "",
        "route": "",
        "enable_japan_driving": False,
        "local": False,
    }
    command = None
    if request.method == "POST":
        form["vehicle_name"] = request.form.get("vehicle_name", "")
        form["launch_config"] = request.form.get("launch_config", "")
        form["map_key"] = request.form.get("map_key", "")
        form["route"] = request.form.get("route", "")
        form["enable_japan_driving"] = "enable_japan_driving" in request.form
        form["local"] = "local" in request.form
        command = build_command(**form)
    return render_template_string(PAGE, options=options, form=form, command=command, lang=lang, t=t)


if __name__ == "__main__":
    app.run(debug=True, port=5050)
