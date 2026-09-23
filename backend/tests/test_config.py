from app.core.config import get_settings


def test_configuration_loads_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://app@db/app")
    monkeypatch.setenv("ANALYTICS_DATABASE_URL", "postgresql+psycopg://readonly@analytics/app")
    monkeypatch.setenv("LLM_MODE", "mock")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.database_url == "postgresql+psycopg://app@db/app"
    assert settings.analytics_database_url == "postgresql+psycopg://readonly@analytics/app"
    assert settings.llm_mode == "mock"

    get_settings.cache_clear()
