"""Tests for analyzer settings (pydantic v2 migration)."""

from services.analyzer.settings import AnalyzerSettings


def _make_settings(monkeypatch, timescale_url=None):
    """Build an AnalyzerSettings with the required env vars set.

    `timescale_url` of None means "unset" (delenv); a string sets it.
    """
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    if timescale_url is None:
        monkeypatch.delenv("TIMESCALE_URL", raising=False)
    else:
        monkeypatch.setenv("TIMESCALE_URL", timescale_url)
    return AnalyzerSettings()


def test_timescale_url_optional_defaults_to_none(monkeypatch):
    # pydantic v2 requires an Optional type for a nullable str field; the
    # default must be None when TIMESCALE_URL is not provided.
    settings = _make_settings(monkeypatch, timescale_url=None)
    assert settings.timescale_url is None


def test_timescale_url_reads_env_when_set(monkeypatch):
    settings = _make_settings(monkeypatch, timescale_url="postgresql://x/y")
    assert settings.timescale_url == "postgresql://x/y"
