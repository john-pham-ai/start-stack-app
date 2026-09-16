import pytest

import brain2_routes
import shared_presets


@pytest.fixture(autouse=True)
def no_default_brain2_candidates(monkeypatch, tmp_path):
    """Keep route-loading tests hermetic on machines with a real checkout.

    find_brain2_repo() falls back to ~/brain2 and ~/Projects/brain2 when
    the env var doesn't pan out. On a dev machine those exist, which
    would leak real route files into tests that expect "no checkout
    found". Tests that want default-candidate discovery set the tuple
    explicitly (see TestFindBrain2Repo).

    ROUTES_SYNC=off keeps the suite off GitHub: route options default to
    the synced-from-origin cache clone (see routes_sync.py), so without
    this every load_options() call would try to hit the network. The
    sync unit tests pass an explicit env and a local fake remote instead.

    APP_UPDATE=off does the same for the app's self-update check (see
    self_update.py) — its tests point at a local fake remote instead.

    The repo's own presets/ directory is pointed at an empty dir too:
    every menu/page renders shared presets from it (see shared_presets.py),
    and the committed example would otherwise leak into exact-list tests.
    The dedicated shared-preset tests pass explicit directories instead.
    """
    monkeypatch.setattr(brain2_routes, "DEFAULT_REPO_CANDIDATES", ())
    monkeypatch.setenv("ROUTES_SYNC", "off")
    monkeypatch.setenv("APP_UPDATE", "off")
    monkeypatch.setattr(shared_presets, "PRESETS_DIR", str(tmp_path / "no-shared-presets"))
