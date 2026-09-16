"""routes_sync: the routes-only cache clone, exercised against a local
fake remote (a bare repo on disk) — never against GitHub itself."""

import re
import subprocess

import pytest

import brain2_routes
import routes_sync
from routes_sync import sync_routes, synced_commit


def git(*args, cwd=None):
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test"] + list(args),
        cwd=cwd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class FakeRemote:
    """A bare 'brain2' on local disk, with a push-able seed checkout."""

    def __init__(self, bare, seed):
        self.bare = bare
        self.seed = seed

    @property
    def url(self):
        return "file://" + str(self.bare)

    def add_route(self, filename, content):
        routes_dir = self.seed / brain2_routes.ROUTES_SUBDIR
        routes_dir.mkdir(parents=True, exist_ok=True)
        (routes_dir / filename).write_text(content, encoding="utf-8")
        git("add", ".", cwd=self.seed)
        git("commit", "-m", filename, cwd=self.seed)
        git("push", "--quiet", str(self.bare), "master", cwd=self.seed)


@pytest.fixture
def fake_remote(tmp_path):
    bare = tmp_path / "origin.git"
    git("init", "--bare", "-b", "master", str(bare))
    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "-b", "master", str(seed))
    remote = FakeRemote(bare, seed)
    remote.add_route(
        "usa.txtpb",
        'identifier { map_name: "usa_zone_10" route_name: "r1" }\n',
    )
    return remote


class TestSyncRoutes:
    def test_off_switch_returns_none(self, fake_remote, tmp_path):
        # ROUTES_SYNC=off never clones or fetches (tests use it to stay
        # off the network; users use it to pin to their local checkout).
        result = sync_routes(
            remote=fake_remote.url,
            cache_dir=str(tmp_path / "cache"),
            env={"ROUTES_SYNC": "off"},
        )
        assert result is None
        assert not (tmp_path / "cache").exists()

    def test_clones_routes_only_and_scans(self, fake_remote, tmp_path):
        cache = str(tmp_path / "cache")
        assert sync_routes(remote=fake_remote.url, cache_dir=cache, env={}) == cache
        # The clone really is routes-only: nothing else came along.
        routes_dir = tmp_path / "cache" / brain2_routes.ROUTES_SUBDIR
        assert routes_dir.is_dir()
        behavior = tmp_path / "cache" / "onroad" / "config" / "constants" / "behavior"
        assert [p.name for p in behavior.iterdir()] == ["routes"]
        assert brain2_routes.scan_route_pairs(cache) == [("usa_zone_10", "r1")]

    def test_refresh_picks_up_new_routes(self, fake_remote, tmp_path):
        cache = str(tmp_path / "cache")
        sync_routes(remote=fake_remote.url, cache_dir=cache, env={})
        fake_remote.add_route(
            "jp.txtpb",
            'identifier { map_name: "jp_zone_53" route_name: "r2" }\n',
        )
        assert sync_routes(remote=fake_remote.url, cache_dir=cache, env={}, force=True) == cache
        assert brain2_routes.scan_route_pairs(cache) == [
            ("jp_zone_53", "r2"),
            ("usa_zone_10", "r1"),
        ]

    def test_ttl_skips_refetch(self, fake_remote, tmp_path):
        cache = str(tmp_path / "cache")
        sync_routes(remote=fake_remote.url, cache_dir=cache, env={})
        fake_remote.add_route(
            "jp.txtpb",
            'identifier { map_name: "jp_zone_53" route_name: "r2" }\n',
        )
        # Within the TTL the sync is a no-op: the new route is NOT there,
        # and the marker's timestamp is untouched.
        marker = tmp_path / "cache" / ".routes-sync-last"
        before = marker.read_text()
        assert sync_routes(remote=fake_remote.url, cache_dir=cache, env={}) == cache
        assert marker.read_text() == before
        assert brain2_routes.scan_route_pairs(cache) == [("usa_zone_10", "r1")]
        # Forcing it refetches.
        sync_routes(remote=fake_remote.url, cache_dir=cache, env={}, force=True)
        assert brain2_routes.scan_route_pairs(cache) == [
            ("jp_zone_53", "r2"),
            ("usa_zone_10", "r1"),
        ]

    def test_unreachable_remote_with_no_cache_returns_none(self, tmp_path):
        assert sync_routes(
            remote="file:///nonexistent-origin.git",
            cache_dir=str(tmp_path / "cache"),
            env={},
        ) is None

    def test_failed_refresh_returns_the_stale_cache(self, fake_remote, tmp_path):
        cache = str(tmp_path / "cache")
        sync_routes(remote=fake_remote.url, cache_dir=cache, env={})
        # Offline moment: the remote is unreachable, but the previously
        # synced cache still has usable (if stale) routes.
        result = sync_routes(
            remote="file:///nonexistent-origin.git",
            cache_dir=cache,
            env={},
            force=True,
        )
        assert result == cache
        assert brain2_routes.scan_route_pairs(result) == [("usa_zone_10", "r1")]

    def test_corrupt_cache_is_recloned(self, fake_remote, tmp_path):
        cache = str(tmp_path / "cache")
        # A leftover directory without a routes subdir (an aborted clone).
        (tmp_path / "cache").mkdir()
        (tmp_path / "cache" / "junk.txt").write_text("half a clone")
        assert sync_routes(remote=fake_remote.url, cache_dir=cache, env={}) == cache
        assert brain2_routes.scan_route_pairs(cache) == [("usa_zone_10", "r1")]


class TestSyncedCommit:
    def test_empty_when_off(self, tmp_path):
        assert synced_commit(cache_dir=str(tmp_path), env={"ROUTES_SYNC": "off"}) == ""

    def test_empty_without_a_cache(self, tmp_path):
        assert synced_commit(cache_dir=str(tmp_path / "nope"), env={}) == ""

    def test_short_hash_after_sync(self, fake_remote, tmp_path):
        cache = str(tmp_path / "cache")
        sync_routes(remote=fake_remote.url, cache_dir=cache, env={})
        commit = synced_commit(cache_dir=cache, env={})
        assert re.fullmatch(r"[0-9a-f]{7,}", commit)
