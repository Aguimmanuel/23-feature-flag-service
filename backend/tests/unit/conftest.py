"""Keep backend unit applications independent of generated frontend builds."""

import pytest


@pytest.fixture(autouse=True)
def isolate_frontend_build_discovery(monkeypatch, tmp_path):
    # Unit tests add probe routes after create_app(). An auto-mounted SPA would
    # precede those probes and answer them with HTML instead of exercising them.
    # Explicit frontend_directory arguments still work; integration tests retain
    # the normal project root and the real built frontend.
    monkeypatch.setattr("app.main.PROJECT_ROOT", tmp_path / "unit-project")
