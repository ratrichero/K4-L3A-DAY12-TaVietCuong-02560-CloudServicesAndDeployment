"""Safety policy for local grading; original lab tests/conftest.py stays untouched.

That file loads .env. Set the opt-in flag first so plain pytest/grade.py cannot
accidentally spend real money. New adapter tests use explicit Settings + mocked
transports. CP5 can still check the already deployed URL as the lab requires.
"""
import os

import pytest

os.environ["REAL_AGENT_ENABLED"] = "false"


@pytest.fixture(autouse=True)
def offline_lab_mode(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("REAL_AGENT_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
