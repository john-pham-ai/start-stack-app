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
    """
    monkeypatch.setattr(brain2_routes, "DEFAULT_REPO_CANDIDATES", ())
