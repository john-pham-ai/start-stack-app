import brain2_routes
from brain2_routes import (
    Brain2RoutesError,
    build_route_options,
    find_brain2_repo,
    load_route_options,
    scan_route_pairs,
)


def make_repo(root, files):
    """Create a fake brain2 checkout; files maps filename -> file content
    (paths may include subdirectories under the routes dir)."""
    routes_dir = root / brain2_routes.ROUTES_SUBDIR
    routes_dir.mkdir(parents=True)
    for name, content in files.items():
        path = routes_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


class TestFindBrain2Repo:
    def test_env_var(self, tmp_path, monkeypatch):
        repo = make_repo(tmp_path / "brain2", {"a.txtpb": ""})
        monkeypatch.setenv("BRAIN2_REPO_PATH", str(repo))
        assert find_brain2_repo() == str(repo)

    def test_env_var_checked_first(self, tmp_path, monkeypatch):
        repo = make_repo(tmp_path / "brain2", {"a.txtpb": ""})
        monkeypatch.setenv("BRAIN2_REPO_PATH", str(repo))
        # Even if the default candidate paths existed, env var wins.
        # (Fake expanduser only rewrites ~ paths, like the real one.)
        monkeypatch.setattr(
            brain2_routes.os.path,
            "expanduser",
            lambda p: str(tmp_path / "nowhere") if p.startswith("~") else p,
        )
        assert find_brain2_repo() == str(repo)

    def test_none_when_nothing_matches(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BRAIN2_REPO_PATH", str(tmp_path / "missing"))
        assert find_brain2_repo() is None

    def test_candidate_needs_routes_dir(self, tmp_path, monkeypatch):
        # A checkout without the routes subdirectory doesn't count.
        (tmp_path / "brain2").mkdir()
        monkeypatch.setenv("BRAIN2_REPO_PATH", str(tmp_path / "brain2"))
        assert find_brain2_repo() is None


class TestScanRoutePairs:
    def test_parses_identifier_variants(self, tmp_path):
        repo = make_repo(
            tmp_path,
            {
                "a.txtpb": 'identifier { map_name: "m1" route_name: "r1" }\n',
                "b.txtpb": 'identifier: {\n  map_name: "m2",\n  route_name: "r2"\n}\n',
                "c.txtpb": 'identifier { map_name: "m3", route_name: "r3" }\n',
                "d.txtpb": 'version: 1\n# no identifiers here\n',
            },
        )
        assert scan_route_pairs(str(repo)) == [("m1", "r1"), ("m2", "r2"), ("m3", "r3")]

    def test_dedupe_across_files(self, tmp_path):
        repo = make_repo(
            tmp_path,
            {
                "a.txtpb": 'identifier { map_name: "m" route_name: "r" }\n',
                "b.txtpb": 'identifier { map_name: "m" route_name: "r" }\n',
            },
        )
        assert scan_route_pairs(str(repo)) == [("m", "r")]

    def test_recursive_scan_finds_subdirectories(self, tmp_path):
        repo = make_repo(
            tmp_path,
            {
                "top.txtpb": 'identifier { map_name: "m1" route_name: "r1" }\n',
                "japan/jp.txtpb": 'identifier { map_name: "m2" route_name: "r2" }\n',
                "archive/deep/old.txtpb": 'identifier { map_name: "m3" route_name: "r3" }\n',
            },
        )
        assert scan_route_pairs(str(repo)) == [("m1", "r1"), ("m2", "r2"), ("m3", "r3")]


class TestBuildRouteOptions:
    def test_unique_route_names_stay_bare(self):
        routes = build_route_options([("m1", "r1"), ("m2", "r2")])
        assert [o.value for o in routes] == ["r1", "r2"]
        assert [o.label for o in routes] == ["r1", "r2"]
        assert [o.owner for o in routes] == ["m1", "m2"]

    def test_ambiguous_route_names_get_map_prefix(self):
        routes = build_route_options([("m1", "loop"), ("m2", "loop"), ("m1", "main")])
        by_value = {o.value: o for o in routes}
        assert "m1:loop" in by_value and "m2:loop" in by_value
        # Labels say which map each ambiguous route belongs to...
        assert by_value["m1:loop"].label == "loop (m1)"
        assert by_value["m2:loop"].label == "loop (m2)"
        # ...while unique route names stay bare.
        assert by_value["main"].label == "main"

    def test_sorted_by_map_then_route(self):
        routes = build_route_options([("mB", "b"), ("mA", "z"), ("mA", "a")])
        assert [(o.owner, o.label) for o in routes] == [("mA", "a"), ("mA", "z"), ("mB", "b")]


class TestLoadRouteOptions:
    def test_happy_path(self, tmp_path):
        repo = make_repo(tmp_path, {"a.txtpb": 'identifier { map_name: "m" route_name: "r" }\n'})
        routes = load_route_options(str(repo))
        assert [o.value for o in routes] == ["r"]
        assert routes[0].owner == "m"

    def test_missing_repo_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BRAIN2_REPO_PATH", str(tmp_path / "missing"))
        try:
            load_route_options()
        except Brain2RoutesError:
            pass
        else:
            raise AssertionError("expected Brain2RoutesError")

    def test_no_routes_found_raises(self, tmp_path):
        repo = make_repo(tmp_path, {"empty.txtpb": "# nothing\n"})
        try:
            load_route_options(str(repo))
        except Brain2RoutesError:
            pass
        else:
            raise AssertionError("expected Brain2RoutesError")
