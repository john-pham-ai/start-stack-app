from flask import Flask, render_template_string, request

from stack_options import build_command, load_options

app = Flask(__name__)

PAGE = """
<!doctype html>
<title>start_stack builder</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; }
  label { display: block; margin-top: 12px; font-weight: 600; }
  select, input[type=checkbox] { margin-top: 4px; }
  pre { background: #222; color: #eee; padding: 12px; border-radius: 6px; overflow-x: auto; }
  button { margin-top: 20px; padding: 8px 16px; }
</style>
<h1>start_stack command builder</h1>
<form method="post">
  <label>vehicle_name
    <select name="vehicle_name">
      {% for opt in options.vehicle_name %}<option value="{{ opt.value }}" {% if opt.value == form.vehicle_name %}selected{% endif %}>{{ opt.label }}</option>{% endfor %}
    </select>
  </label>
  <label>launch_config
    <select name="launch_config">
      {% for opt in options.launch_config %}<option value="{{ opt.value }}" {% if opt.value == form.launch_config %}selected{% endif %}>{{ opt.label }}</option>{% endfor %}
    </select>
  </label>
  <label>map_key (optional)
    <select name="map_key">
      <option value="">-- none --</option>
      {% for opt in options.map_key %}<option value="{{ opt.value }}" {% if opt.value == form.map_key %}selected{% endif %}>{{ opt.label }}</option>{% endfor %}
    </select>
  </label>
  <label>route (optional)
    <select name="route">
      <option value="">-- none --</option>
      {% for opt in options.route %}<option value="{{ opt.value }}" {% if opt.value == form.route %}selected{% endif %}>{{ opt.label }}</option>{% endfor %}
    </select>
  </label>
  <label><input type="checkbox" name="enable_japan_driving" {% if form.enable_japan_driving %}checked{% endif %}> enable_japan_driving</label>
  <label><input type="checkbox" name="local" {% if form.local %}checked{% endif %}> local</label>
  <button type="submit">Build command</button>
</form>
{% if command %}
  <h3>Command</h3>
  <pre>{{ command }}</pre>
{% endif %}
"""


@app.route("/", methods=["GET", "POST"])
def index():
    options = load_options()
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
    return render_template_string(PAGE, options=options, form=form, command=command)


if __name__ == "__main__":
    app.run(debug=True, port=5050)
