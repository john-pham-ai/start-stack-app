import textwrap

import pytest

import stack_options
from stack_options import (
    Option,
    build_command,
    load_options,
    map_key_for_route,
)


@pytest.fixture
def csv_file(tmp_path):
    """A small options.csv exercising every column."""
    path = tmp_path / "options.csv"
    path.write_text(
        textwrap.dedent(
            """\
            field,value,nickname,owner_map_key,language
            vehicle_name,truck-807,,,
            launch_config,sds_road_readiness,,,
            route,shoreline_straight,Shoreline Straight,usa_zone_10,
            route,a_loop,Loop - Slow,usa_zone_10,
            """
        ),
        encoding="utf-8",
    )
    return str(path)


class TestBuildCommand:
    def test_minimal(self):
        assert build_command("truck-807", "sds_road_readiness") == (
            "start_stack \\\n  --vehicle_name truck-807 \\\n  --launch_config sds_road_readiness"
        )

    def test_with_route(self):
        command = build_command("truck-807", "sds_road_readiness", route="a_loop")
        assert "--route a_loop" in command

    def test_enable_japan_driving(self):
        command = build_command("truck-807", "sds_road_readiness", enable_japan_driving=True)
        assert "--enable_japan_driving" in command

    def test_off_by_default(self):
        assert "--enable_japan_driving" not in build_command("t", "c")

    def test_no_map_key_flag(self):
        """Routes carry their map; --map_key is never emitted."""
        command = build_command("truck-807", "sds_road_readiness", route="usa_zone_10:main")
        assert "--map_key" not in command

    def test_multiline_stays_shell_valid(self):
        lines = build_command("truck-807", "sds_road_readiness", route="a").splitlines()
        assert lines[0] == "start_stack \\"
        assert all(line.endswith("\\") for line in lines[:-1])
        assert not lines[-1].endswith("\\")


class TestLoadOptions:
    def test_csv_fallback_without_brain2(self, csv_file, monkeypatch):
        monkeypatch.setenv("BRAIN2_REPO_PATH", "/nonexistent-brain2")
        options = load_options(csv_path=csv_file)
        assert [o.value for o in options["vehicle_name"]] == ["truck-807"]
        assert [o.value for o in options["launch_config"]] == ["sds_road_readiness"]
        assert [o.value for o in options["route"]] == ["shoreline_straight", "a_loop"]
        assert options["route"][0].label == "Shoreline Straight"
        assert options["route"][0].owner == "usa_zone_10"

    def test_defaults_when_csv_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BRAIN2_REPO_PATH", "/nonexistent-brain2")
        options = load_options(csv_path=str(tmp_path / "nope.csv"))
        assert options["vehicle_name"][0].value == "truck-807"
        assert options["launch_config"][0].value == "sds_road_readiness"
        assert options["route"][0].value == "shoreline_terminal_10kph"

    def test_live_brain2_replaces_routes(self, csv_file, tmp_path, monkeypatch):
        repo = make_fake_brain2(tmp_path / "brain2")
        monkeypatch.setenv("BRAIN2_REPO_PATH", str(repo))
        options = load_options(csv_path=csv_file)
        by_value = {o.value: o for o in options["route"]}

        # Live values win; CSV-only rows disappear (a_loop isn't in brain2).
        assert "a_loop" not in by_value
        # Recursive scan: the subdirectory route file was picked up too.
        assert "legacy_route" in by_value
        assert by_value["legacy_route"].owner == "legacy_map"
        # Ambiguous route names get the map: prefix and a "route (map)" label...
        assert "usa_zone_10:main" in by_value and "walnut_creek:main" in by_value
        assert by_value["usa_zone_10:main"].label == "main (usa_zone_10)"
        # ...while unique route names stay bare, but with CSV nicknames
        # overlaid and live route→map ownership always winning.
        assert by_value["shoreline_straight"].label == "Shoreline Straight"
        assert by_value["shoreline_straight"].owner == "usa_zone_10"

    def test_vehicle_and_config_always_come_from_csv(self, tmp_path, monkeypatch):
        repo = make_fake_brain2(tmp_path / "brain2")
        monkeypatch.setenv("BRAIN2_REPO_PATH", str(repo))
        options = load_options(csv_path=str(tmp_path / "nope.csv"))
        assert options["vehicle_name"][0].value == "truck-807"  # the default

    def test_synced_cache_takes_precedence_over_local_checkouts(
        self, csv_file, tmp_path, monkeypatch
    ):
        # The GitHub-synced cache (routes_sync) is the primary source; the
        # local checkout (BRAIN2_REPO_PATH) only stands in when syncing
        # isn't possible. A different fake repo for each proves which won.
        cache = make_fake_brain2(tmp_path / "cache")
        local = tmp_path / "local"
        local_routes = local / "onroad" / "config" / "constants" / "behavior" / "routes"
        local_routes.mkdir(parents=True)
        (local_routes / "only_local.txtpb").write_text(
            'identifier { map_name: "local_map" route_name: "only_local" }\n'
        )
        monkeypatch.setattr(stack_options, "sync_routes", lambda: str(cache))
        monkeypatch.setattr(stack_options, "find_brain2_repo", lambda: str(local))

        options = load_options(csv_path=csv_file)
        by_value = {o.value for o in options["route"]}
        assert "legacy_route" in by_value  # from the synced cache
        assert "only_local" not in by_value  # the local checkout lost
        assert "a_loop" not in by_value  # CSV-only rows still disappear

    def test_local_checkout_used_when_sync_unavailable(
        self, csv_file, tmp_path, monkeypatch
    ):
        cache = tmp_path / "cache"
        local = make_fake_brain2(tmp_path / "local")
        monkeypatch.setattr(stack_options, "sync_routes", lambda: None)
        monkeypatch.setattr(stack_options, "find_brain2_repo", lambda: str(local))

        options = load_options(csv_path=csv_file)
        by_value = {o.value for o in options["route"]}
        assert "legacy_route" in by_value  # from the local checkout
        assert "a_loop" not in by_value


def make_fake_brain2(root):
    """A minimal brain2 checkout; "main" exists under both maps (ambiguous),
    and one route file hides in a subdirectory to prove the scan is
    recursive."""
    routes_dir = root / "onroad" / "config" / "constants" / "behavior" / "routes"
    routes_dir.mkdir(parents=True)
    (routes_dir / "usa_routes.txtpb").write_text(
        'identifier { map_name: "usa_zone_10" route_name: "shoreline_straight" }\n'
        'identifier { map_name: "usa_zone_10" route_name: "main" }\n',
        encoding="utf-8",
    )
    (routes_dir / "walnut_routes.txtpb").write_text(
        'identifier: {\n  map_name: "walnut_creek",\n  route_name: "main"\n}\n',
        encoding="utf-8",
    )
    subdir = routes_dir / "archive" / "old_maps"
    subdir.mkdir(parents=True)
    (subdir / "legacy.txtpb").write_text(
        'identifier { map_name: "legacy_map" route_name: "legacy_route" }\n',
        encoding="utf-8",
    )
    return root


class TestMapKeyForRoute:
    def test_returns_owner(self):
        options = {"route": [Option("a", "a", "usa_zone_10", ""), Option("b", "b", "", "")]}
        assert map_key_for_route(options, "a") == "usa_zone_10"

    def test_unknown_route_is_blank(self):
        options = {"route": [Option("a", "a", "usa_zone_10", "")]}
        assert map_key_for_route(options, "zzz") == ""

    def test_ownerless_route_is_blank(self):
        options = {"route": [Option("b", "b", "", "")]}
        assert map_key_for_route(options, "b") == ""
