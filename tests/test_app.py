import io
import json
import os

import pytest

import shared_presets
import state as state_module
from app import app, normalize_route, normalize_vehicle_name
from stack_options import Option

SHARED_VALUES = {
    "vehicle_name": "truck-807",
    "launch_config": "sds_road_readiness",
    "route": "shoreline_straight",
    "enable_japan_driving": False,
}


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setattr(state_module, "STATE_PATH", str(path))
    return path


@pytest.fixture(autouse=True)
def no_brain2(monkeypatch):
    monkeypatch.setenv("BRAIN2_REPO_PATH", "/nonexistent-brain2")


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestNormalizeVehicleName:
    def test_bare_number_gets_truck_prefix(self):
        assert normalize_vehicle_name("807") == "truck-807"

    def test_full_name_untouched(self):
        assert normalize_vehicle_name("truck-807") == "truck-807"

    def test_whitespace_stripped(self):
        assert normalize_vehicle_name("  807 ") == "truck-807"

    def test_garbage_untouched(self):
        assert normalize_vehicle_name("bus-1") == "bus-1"


class TestNormalizeRoute:
    ROUTES = {
        "route": [
            Option("shoreline_terminal_10kph", "Shoreline Terminal - Slow", "shoreline_zone_10", ""),
            Option("shoreline_straight", "shoreline_straight", "shoreline_zone_10", ""),
        ]
    }

    def test_value_passthrough(self):
        assert normalize_route(self.ROUTES, "shoreline_straight") == "shoreline_straight"

    def test_label_resolves_to_value(self):
        assert normalize_route(self.ROUTES, "Shoreline Terminal - Slow") == "shoreline_terminal_10kph"

    def test_whitespace_stripped(self):
        assert normalize_route(self.ROUTES, "  shoreline_straight ") == "shoreline_straight"

    def test_unknown_becomes_empty(self):
        assert normalize_route(self.ROUTES, "not_a_route") == ""

    def test_empty_is_empty(self):
        assert normalize_route(self.ROUTES, "") == ""


class TestWebUI:
    def test_get_renders_form(self, client):
        page = client.get("/").get_data(as_text=True)
        assert "start_stack command builder" in page
        assert 'name="vehicle_name"' in page

    def test_post_builds_command(self, client):
        page = client.post(
            "/",
            data={
                "lang": "en",
                "vehicle_name": "807",
                "launch_config": "sds_road_readiness",
                "route": "shoreline_straight",
            },
        ).get_data(as_text=True)
        assert "--vehicle_name truck-807" in page  # bare number normalized
        assert "--route shoreline_straight" in page
        assert "--map_key" not in page  # never emitted

    def test_page_javascript_parses(self, client):
        """PAGE is a Python string, so a stray "\\n" or "\\t" escape inside
        the inline JS silently becomes a real newline/tab and kills the
        whole script (the combobox once shipped broken exactly this way).
        Parse the served <script> with node when it's available."""
        import shutil
        import subprocess

        if shutil.which("node") is None:
            pytest.skip("node not installed")
        page = client.get("/").get_data(as_text=True)
        js = page[page.index("<script>") + len("<script>"):page.rindex("</script>")]
        result = subprocess.run(
            ["node", "--check", "--input-type=module", "-"],
            input=js, capture_output=True, text=True,
        )
        # `--check` refuses stdin; fall back to a temp file when it does.
        if result.returncode and "check" in (result.stderr or "").lower():
            import tempfile

            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(js)
            result = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_route_combobox_rendered(self, client):
        page = client.get("/").get_data(as_text=True)
        # The route picker is a combobox: search input + hidden value field...
        assert 'id="route-input"' in page
        assert 'id="route-value"' in page
        assert "Type to filter — click for the full list" in page
        # ...with every route (and its map) riding along as JSON for the JS.
        assert "usa_zone_10" in page
        assert "shoreline_straight" in page
        # No map_key dropdown anywhere.
        assert 'name="map_key"' not in page

    def test_route_label_post_normalizes_to_value(self, client):
        # Typed text matching a route's label submits as that route's value.
        page = client.post(
            "/",
            data={
                "lang": "en",
                "vehicle_name": "807",
                "launch_config": "sds_road_readiness",
                "route": "Shoreline Terminal - Slow",
            },
        ).get_data(as_text=True)
        assert "--route shoreline_terminal_10kph" in page

    def test_unknown_route_left_out_of_command(self, client):
        page = client.post(
            "/",
            data={
                "lang": "en",
                "vehicle_name": "807",
                "launch_config": "sds_road_readiness",
                "route": "not_a_route",
            },
        ).get_data(as_text=True)
        assert "--route" not in page

    def test_history_persisted_across_visits(self, client, isolated_state):
        client.post(
            "/",
            data={"lang": "en", "vehicle_name": "807", "launch_config": "sds_road_readiness"},
        )
        page = client.get("/").get_data(as_text=True)
        assert "Recent commands" in page
        assert "--vehicle_name truck-807" in page

    def test_save_preset_action(self, client, isolated_state):
        client.post(
            "/",
            data={
                "lang": "en",
                "action": "save_preset",
                "preset_name": "night loop",
                "vehicle_name": "807",
                "launch_config": "sds_road_readiness",
                "route": "shoreline_straight",
            },
        )
        state = json.loads(isolated_state.read_text())
        assert state["presets"]["night loop"]["vehicle_name"] == "truck-807"
        assert state["presets"]["night loop"]["route"] == "shoreline_straight"

    def test_saved_preset_appears_in_page(self, client):
        client.post(
            "/",
            data={
                "lang": "en",
                "action": "save_preset",
                "preset_name": "night loop",
                "vehicle_name": "807",
                "launch_config": "sds_road_readiness",
            },
        )
        page = client.get("/").get_data(as_text=True)
        assert 'value="night loop"' in page
        # Loading is a server-side action with its own button now.
        assert 'id="load-preset-btn" disabled' in page

    def test_remove_preset_action(self, client, isolated_state):
        client.post(
            "/",
            data={
                "lang": "en",
                "action": "save_preset",
                "preset_name": "night loop",
                "vehicle_name": "807",
                "launch_config": "sds_road_readiness",
            },
        )
        page = client.post(
            "/",
            data={
                "lang": "en",
                "action": "remove_preset",
                "preset_name": "night loop",
            },
        ).get_data(as_text=True)
        state = json.loads(isolated_state.read_text())
        assert "presets" not in state or "night loop" not in state.get("presets", {})
        # The preset dropdown (and the whole remove form) disappears with it...
        assert 'value="night loop"' not in page
        # ...and no command block was built from the remove-only POST
        # (history entries from earlier runs may still show, that's fine).
        assert 'id="command"' not in page

    def test_remove_preset_keeps_the_others(self, client, isolated_state):
        for name in ("a", "b"):
            client.post(
                "/",
                data={
                    "lang": "en",
                    "action": "save_preset",
                    "preset_name": name,
                    "vehicle_name": "807",
                    "launch_config": "sds_road_readiness",
                },
            )
        client.post(
            "/", data={"lang": "en", "action": "remove_preset", "preset_name": "a"}
        )
        state = json.loads(isolated_state.read_text())
        assert list(state["presets"]) == ["b"]

    def test_remove_preset_blank_name_is_noop(self, client, isolated_state):
        client.post(
            "/",
            data={
                "lang": "en",
                "action": "save_preset",
                "preset_name": "night loop",
                "vehicle_name": "807",
                "launch_config": "sds_road_readiness",
            },
        )
        client.post("/", data={"lang": "en", "action": "remove_preset", "preset_name": ""})
        state = json.loads(isolated_state.read_text())
        assert "night loop" in state["presets"]

    def test_remove_button_disabled_until_selection(self, client):
        client.post(
            "/",
            data={
                "lang": "en",
                "action": "save_preset",
                "preset_name": "night loop",
                "vehicle_name": "807",
                "launch_config": "sds_road_readiness",
            },
        )
        page = client.get("/").get_data(as_text=True)
        assert 'id="remove-preset-btn" disabled' in page

    def test_load_values_preset_builds_command_immediately(self, client, isolated_state):
        """Loading a preset is one click: command built, rendered, auto-copied."""
        client.post(
            "/",
            data={
                "lang": "en",
                "action": "save_preset",
                "preset_name": "night loop",
                "vehicle_name": "807",
                "launch_config": "sds_road_readiness",
                "route": "shoreline_straight",
            },
        )
        page = client.post(
            "/", data={"lang": "en", "action": "load_preset", "preset_name": "night loop"}
        ).get_data(as_text=True)
        assert 'id="command"' in page  # rendered -> the auto-copy JS picks it up
        assert "--vehicle_name truck-807" in page
        assert "--route shoreline_straight" in page
        # The form reflects the preset's values too: the hidden route field
        # carries the value, the visible box shows its label.
        assert 'id="route-value" value="shoreline_straight"' in page
        # And the load was recorded in history.
        state = json.loads(isolated_state.read_text())
        assert state["history"][0]["custom"] is False
        assert state["history"][0]["command"].startswith("start_stack")

    def test_load_custom_preset_shows_command_verbatim(self, client, isolated_state):
        isolated_state.write_text(
            json.dumps(
                {
                    "presets": {
                        "raw run": {
                            "kind": "command",
                            "command": "my_tool --flag --vehicle_name truck-42",
                        }
                    }
                }
            )
        )
        page = client.post(
            "/", data={"lang": "en", "action": "load_preset", "preset_name": "raw run"}
        ).get_data(as_text=True)
        assert "my_tool --flag --vehicle_name truck-42" in page
        assert 'id="command"' in page
        state = json.loads(isolated_state.read_text())
        entry = state["history"][0]
        assert entry["custom"] is True
        assert entry["vehicle_name"] == "truck-42"

    def test_load_preset_blank_name_is_noop(self, client):
        page = client.post(
            "/", data={"lang": "en", "action": "load_preset", "preset_name": ""}
        ).get_data(as_text=True)
        assert 'id="command"' not in page

    def test_save_custom_preset_action(self, client, isolated_state):
        # Pasting the multi-line backslash form normalizes to one line.
        page = client.post(
            "/",
            data={
                "lang": "en",
                "action": "save_custom_preset",
                "preset_name": "raw run",
                "custom_command": "start_stack \\\n  --vehicle_name truck-807 \\\n  --launch_config cfg",
            },
        ).get_data(as_text=True)
        state = json.loads(isolated_state.read_text())
        assert state["presets"]["raw run"] == {
            "kind": "command",
            "command": "start_stack --vehicle_name truck-807 --launch_config cfg",
        }
        # The dropdown marks it as custom, and the command textarea is back empty.
        assert "raw run (custom)" in page
        assert ">start_stack" not in page.split("<textarea")[1].split("</textarea>")[0]

    def test_save_custom_preset_blank_command_ignored(self, client, isolated_state):
        client.post(
            "/",
            data={
                "lang": "en",
                "action": "save_custom_preset",
                "preset_name": "raw run",
                "custom_command": "   ",
            },
        )
        state = json.loads(isolated_state.read_text())
        assert "presets" not in state

    def test_custom_command_html_escaping(self, client, isolated_state):
        nasty = 'echo "<b>&x</b>" --vehicle_name=truck-1'
        client.post(
            "/",
            data={
                "lang": "en",
                "action": "save_custom_preset",
                "preset_name": "weird",
                "custom_command": nasty,
            },
        )
        page = client.post(
            "/", data={"lang": "en", "action": "load_preset", "preset_name": "weird"}
        ).get_data(as_text=True)
        assert "&lt;b&gt;&amp;x&lt;/b&gt;" in page  # escaped, not injected
        assert "<b>&x</b>" not in page

    def test_japanese_ui(self, client):
        page = client.get("/?lang=ja").get_data(as_text=True)
        assert "start_stack コマンドビルダー" in page
        assert "最近のコマンド" not in page  # no history yet → section hidden

    def test_enable_japan_driving_reaches_command(self, client):
        page = client.post(
            "/",
            data={
                "lang": "en",
                "vehicle_name": "807",
                "launch_config": "sds_road_readiness",
                "enable_japan_driving": "on",
            },
        ).get_data(as_text=True)
        assert "--enable_japan_driving" in page


class TestAppsPlatform:
    """The packaging the Apps Platform deploys: health probe + guards."""

    def test_health_endpoint(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.get_json() == {"status": "healthy"}

    def test_gunicorn_pinned_and_procfile_bind(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        requirements = (open(os.path.join(root, "requirements.txt")).read())
        assert "gunicorn" in requirements
        procfile = open(os.path.join(root, "Procfile")).read()
        # Binds the platform's PORT on all interfaces, like the deployed form.
        assert "0.0.0.0:$PORT" in procfile
        assert "app:app" in procfile

    def test_image_excludes_developer_only_files(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ignored = open(os.path.join(root, ".gcloudignore")).read()
        for junk in ("venv/", "tests/", ".git", ".launch_state.json"):
            assert junk in ignored
        # ...but the shared presets ship with the image.
        assert "presets/" not in ignored

    def test_project_toml_declares_the_platform_bits(self):
        import tomllib

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "project.toml"), "rb") as f:
            config = tomllib.load(f)
        assert config["name"] == "start-stack-app"
        # State must survive redeploys (presets!) — hence the Filestore.
        assert config["enable_filestore"] is True
        assert config["metadata"]["owner"] == "john.pham@applied.co"


class TestSharedPresets:
    """The repo's presets/: listed, loadable, exportable, importable."""

    @pytest.fixture
    def shared_dir(self, tmp_path, monkeypatch):
        presets_dir = tmp_path / "presets"
        presets_dir.mkdir()
        (presets_dir / "repo route.json").write_text(json.dumps(SHARED_VALUES))
        monkeypatch.setattr(shared_presets, "PRESETS_DIR", str(presets_dir))
        return presets_dir

    def test_shared_in_dropdown_with_tag(self, client, shared_dir):
        page = client.get("/").get_data(as_text=True)
        assert "repo route (shared)" in page
        # The Export button rides the preset form now.
        assert 'value="export_preset"' in page

    def test_loading_shared_builds_its_command(self, client, shared_dir, isolated_state):
        page = client.post(
            "/",
            data={"lang": "en", "action": "load_preset", "preset_name": "repo route"},
        ).get_data(as_text=True)
        assert "--route shoreline_straight" in page
        # And the use is remembered like any preset load.
        state = json.loads(isolated_state.read_text())
        assert state["history"][0]["command"].startswith("start_stack")

    def test_personal_copy_shadows_the_shared_name(self, client, shared_dir, isolated_state):
        # Saving a personal preset under a shared name keeps both: the
        # dropdown lists it once (personal wins), the command is personal.
        client.post(
            "/",
            data={
                "lang": "en", "action": "save_preset", "preset_name": "repo route",
                "vehicle_name": "807", "launch_config": "sds_road_readiness",
                "route": "crows_landing_anticw_inner_loop",
            },
        )
        page = client.post(
            "/",
            data={"lang": "en", "action": "load_preset", "preset_name": "repo route"},
        ).get_data(as_text=True)
        assert "--route crows_landing_anticw_inner_loop" in page

    def test_remove_shared_says_where_it_lives(self, client, shared_dir):
        page = client.post(
            "/",
            data={"lang": "en", "action": "remove_preset", "preset_name": "repo route"},
        ).get_data(as_text=True)
        assert "comes from the repo" in page
        assert "repo route (shared)" in page  # still there — it's the repo's

    def test_export_downloads_a_share_file(self, client, isolated_state):
        client.post(
            "/",
            data={
                "lang": "en", "action": "save_preset", "preset_name": "night loop",
                "vehicle_name": "807", "launch_config": "sds_road_readiness",
                "route": "shoreline_straight",
            },
        )
        response = client.post(
            "/", data={"lang": "en", "action": "export_preset", "preset_name": "night loop"}
        )
        assert response.status_code == 200
        assert "attachment" in response.headers.get("Content-Disposition", "")
        assert "night loop.json" in response.headers.get("Content-Disposition", "")
        entry = json.loads(response.get_data())
        assert entry["route"] == "shoreline_straight"
        assert entry["kind"] == "values"

    def test_import_upload_saves_the_preset(self, client, isolated_state):
        data = json.dumps(SHARED_VALUES)
        page = client.post(
            "/",
            data={
                "lang": "en",
                "action": "import_preset",
                "preset_file": (io.BytesIO(data.encode()), "night loop.json"),
            },
            content_type="multipart/form-data",
        ).get_data(as_text=True)
        assert "Imported preset: night loop" in page
        state = json.loads(isolated_state.read_text())
        assert state["presets"]["night loop"]["route"] == "shoreline_straight"

    def test_import_bad_upload_says_why(self, client, isolated_state):
        page = client.post(
            "/",
            data={
                "lang": "en",
                "action": "import_preset",
                "preset_file": (io.BytesIO(b'{"kind": "command"}'), "raw.json"),
            },
            content_type="multipart/form-data",
        ).get_data(as_text=True)
        assert "not a shared-able values preset" in page
        # Nothing was saved: no state file appeared.
        assert not isolated_state.exists() or "presets" not in json.loads(
            isolated_state.read_text()
        )

    def test_import_without_a_file_prompts(self, client):
        page = client.post(
            "/", data={"lang": "en", "action": "import_preset", "preset_file": ""}
        ).get_data(as_text=True)
        assert "Choose a preset .json file first." in page


class TestTruckFetch:
    INFO = {
        "vehicle": "805",
        "run_id": "2026-09-15_14-48-57_truck-805",
        "path": "/media/hotswap1/frontier/truck-805/2026/09/15/2026-09-15_14-48-57_truck-805",
        "date": "2026/09/15",
        "hostname": "truck-805-primarypc",
        "warning": "",
    }

    def test_button_rendered(self, client):
        page = client.get("/").get_data(as_text=True)
        assert 'value="truck_run"' in page
        assert "Fetch Run ID from truck" in page

    def test_fetch_renders_result_block(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module.truck, "fetch_run_id", lambda vehicle: dict(self.INFO))
        page = client.post(
            "/",
            data={"lang": "en", "vehicle_name": "805", "action": "truck_run"},
        ).get_data(as_text=True)
        assert "Latest run on the truck" in page
        assert "2026-09-15_14-48-57_truck-805" in page
        assert "/media/hotswap1/frontier/truck-805/" in page

    def test_fetch_error_renders_message(self, client, monkeypatch):
        import app as app_module

        def boom(vehicle):
            raise app_module.truck.TruckError("could not SSH to applied@192.168.1.11")

        monkeypatch.setattr(app_module.truck, "fetch_run_id", boom)
        page = client.post(
            "/",
            data={"lang": "en", "vehicle_name": "805", "action": "truck_run"},
        ).get_data(as_text=True)
        assert "Could not fetch the run id:" in page
        assert "could not SSH" in page
        assert "2026-09-15" not in page  # no stale result block

    def test_fetch_does_not_record_history(self, client, monkeypatch, isolated_state):
        import app as app_module

        monkeypatch.setattr(app_module.truck, "fetch_run_id", lambda vehicle: dict(self.INFO))
        client.post("/", data={"lang": "en", "vehicle_name": "805", "action": "truck_run"})
        # A fetch builds no command, so nothing lands in the history.
        assert not isolated_state.exists()


class TestTruckSSHSetup:
    SETUP = {
        "vehicle": "805", "alias": "truck-805", "key_path": "/home/x/.ssh/truck-805",
        "public_key": "ssh-ed25519 AAAA truck-805", "key_created": True,
        "config_added": True, "key_installed": True,
        "install_detail": "installed using your existing SSH key/agent", "next_step": "",
    }

    def test_button_rendered(self, client):
        page = client.get("/").get_data(as_text=True)
        assert 'value="truck_ssh_setup"' in page
        assert "Set up SSH for truck" in page

    def test_setup_renders_result(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module.truck, "setup_ssh", lambda v: dict(self.SETUP))
        page = client.post(
            "/",
            data={"lang": "en", "vehicle_name": "805", "action": "truck_ssh_setup"},
        ).get_data(as_text=True)
        assert "Truck SSH setup" in page
        assert "identity created" in page
        assert "✅ public key installed" in page

    def test_setup_install_failure_shows_next_step(self, client, monkeypatch):
        import app as app_module

        setup = dict(self.SETUP, key_installed=False, install_detail="key rejected",
                     next_step="ssh-copy-id -i ~/.ssh/truck-805.pub applied@192.168.1.11")
        monkeypatch.setattr(app_module.truck, "setup_ssh", lambda v: setup)
        page = client.post(
            "/",
            data={"lang": "en", "vehicle_name": "805", "action": "truck_ssh_setup"},
        ).get_data(as_text=True)
        assert "⚠️ key rejected" in page
        assert "ssh-copy-id -i ~/.ssh/truck-805.pub" in page

    def test_setup_without_vehicle_renders_the_rule(self, client, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module.truck, "setup_ssh", lambda v: dict(self.SETUP))
        page = client.post(
            "/",
            data={"lang": "en", "vehicle_name": "", "action": "truck_ssh_setup"},
        ).get_data(as_text=True)
        assert "named after it" in page
