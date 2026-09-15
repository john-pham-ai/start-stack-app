import json

import pytest

import state as state_module
from app import app, normalize_vehicle_name


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

    def test_routes_grouped_by_map(self, client):
        page = client.get("/").get_data(as_text=True)
        assert '<optgroup label="usa_zone_10">' in page
        assert 'value="shoreline_straight"' in page
        # No map_key dropdown anywhere.
        assert 'name="map_key"' not in page

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
        assert "presets[" in page  # preset data embedded for the JS loader

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
