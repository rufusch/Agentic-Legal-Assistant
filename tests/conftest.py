"""Unit/API tests use stub models and must not contact real government websites."""
import pytest


@pytest.fixture(autouse=True)
def offline_official_sources(monkeypatch):
    monkeypatch.setenv('LEXIMIND_OFFICIAL_SOURCES','0')
