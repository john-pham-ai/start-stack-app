import pytest

import brain2_routes


@pytest.fixture(autouse=True)
def no_default_brain2_candidates(monkeypatch):
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
    """
    monkeypatch.setattr(brain2_routes, "DEFAULT_REPO_CANDIDATES", ())
    monkeypatch.setenv("ROUTES_SYNC", "off")
    monkeypatch.setenv("APP_UPDATE", "off")
