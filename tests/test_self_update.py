"""self_update: the app updating its own repo, exercised against a local
fake remote (a bare repo on disk) — never against GitHub itself."""

import subprocess

import pytest

import self_update as self_update_module
from self_update import BLOCKED, CURRENT, SKIPPED, UPDATED, self_update


def git(*args, cwd=None):
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@test"] + list(args),
        cwd=cwd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def make_app_remote(tmp_path):
    """A bare 'start-stack-app' remote seeded with one commit, plus a
    local clone of it standing in for the running app."""
    bare = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "VERSION").write_text("1.0.0")
    git("init", "--bare", "-b", "master", str(bare))
    git("init", "-b", "master", str(seed))
    git("add", ".", cwd=seed)
    git("commit", "-m", "init", cwd=seed)
    git("push", "--quiet", str(bare), "master", cwd=seed)
    clone = tmp_path / "app"
    git("clone", "--quiet", "-b", "master", str(bare), str(clone))
    git("remote", "add", "origin", str(bare), cwd=seed)
    return bare, seed, clone


def commit_file(repo, filename, content, message):
    (repo / filename).write_text(content)
    git("add", ".", cwd=repo)
    git("commit", "-m", message, cwd=repo)
    git("push", "--quiet", "origin", "master", cwd=repo)


@pytest.fixture(autouse=True)
def isolated_marker(tmp_path, monkeypatch):
    """The TTL marker lives in ~/.cache; pin it into the test's tmp dir so
    a test run can't make the developer's next real launch skip its
    self-update check."""
    marker = tmp_path / "self-update.last"
    monkeypatch.setattr(self_update_module, "_marker_path", lambda: str(marker))
    return marker


class TestSelfUpdate:
    def test_current_when_origin_not_ahead(self, tmp_path):
        _, _, clone = make_app_remote(tmp_path)
        assert self_update(repo_dir=str(clone), env={})[0] == CURRENT

    def test_fast_forwards_when_origin_ahead(self, tmp_path):
        bare, seed, clone = make_app_remote(tmp_path)
        commit_file(seed, "VERSION", "2.0.0", "bump")
        status, detail = self_update(repo_dir=str(clone), env={})
        assert status == UPDATED
        expected = subprocess.run(
            ["git", "-C", str(clone), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        assert detail == expected
        assert (clone / "VERSION").read_text() == "2.0.0"
        # And now it's current.
        assert self_update(repo_dir=str(clone), env={})[0] == CURRENT

    def test_dirty_tree_blocks_the_pull(self, tmp_path):
        bare, seed, clone = make_app_remote(tmp_path)
        commit_file(seed, "VERSION", "2.0.0", "bump")
        # A local edit must never be clobbered by the auto-update.
        (clone / "local_notes.txt").write_text("uncommitted work")
        status, _ = self_update(repo_dir=str(clone), env={})
        assert status == BLOCKED
        assert (clone / "VERSION").read_text() == "1.0.0"
        assert (clone / "local_notes.txt").exists()

    def test_off_switch(self, tmp_path):
        _, _, clone = make_app_remote(tmp_path)
        assert self_update(repo_dir=str(clone), env={"APP_UPDATE": "off"}) == (SKIPPED, "")

    def test_not_a_repo_is_silent(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert self_update(repo_dir=str(plain), env={}) == (SKIPPED, "")

    def test_bad_remote_is_silent(self, tmp_path):
        bare, seed, clone = make_app_remote(tmp_path)
        # Point origin at nothing: the fetch fails, the app still starts.
        git("remote", "set-url", "origin", "file:///nowhere.git", cwd=clone)
        assert self_update(repo_dir=str(clone), env={})[0] == SKIPPED

    def test_ttl_skips_recheck(self, tmp_path, isolated_marker):
        bare, seed, clone = make_app_remote(tmp_path)
        self_update(repo_dir=str(clone), env={})
        commit_file(seed, "VERSION", "2.0.0", "bump")
        # Within the TTL the second check is a no-op: no fetch happened —
        # the marker is untouched and the new commit has NOT arrived.
        fresh = isolated_marker.read_text()
        assert self_update(repo_dir=str(clone), env={})[0] == CURRENT
        assert isolated_marker.read_text() == fresh
        assert (clone / "VERSION").read_text() == "1.0.0"
        # Forced: fetches again and fast-forwards.
        assert self_update(repo_dir=str(clone), env={}, force=True)[0] == UPDATED
