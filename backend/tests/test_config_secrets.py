import pytest

from app.core.config import (
    ConfigurationError,
    Settings,
    get_settings,
    read_secret_files,
)


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch):
    for name in (
        "GEMINI_API_KEY",
        "GEMINI_API_KEY_FILE",
        "JWT_SECRET",
        "JWT_SECRET_FILE",
        "DATABASE_URL",
        "DATABASE_URL_FILE",
        "METRICS_TOKEN",
        "METRICS_TOKEN_FILE",
        "AUTH_MODE",
        "APP_ENV",
        "LLM_MODE",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _write(tmp_path, name: str, contents: str) -> str:
    path = tmp_path / name
    path.write_text(contents, encoding="utf-8")
    return str(path)


def test_file_secrets_are_read_and_trimmed(tmp_path) -> None:
    key_file = _write(tmp_path, "gemini", "  gemini-secret-from-file \n")

    values = read_secret_files({"GEMINI_API_KEY_FILE": key_file})

    assert values == {"gemini_api_key": "gemini-secret-from-file"}


def test_get_settings_uses_file_secrets(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY_FILE", _write(tmp_path, "gemini", "file-key\n"))
    monkeypatch.setenv("METRICS_TOKEN_FILE", _write(tmp_path, "metrics", "metrics-from-file"))

    settings = get_settings()

    assert settings.gemini_api_key.get_secret_value() == "file-key"
    assert settings.metrics_token.get_secret_value() == "metrics-from-file"
    assert "file-key" not in repr(settings)


def test_database_url_can_come_from_a_file(tmp_path, monkeypatch) -> None:
    url = "postgresql+psycopg://app:s3cret@db/app"
    monkeypatch.setenv("DATABASE_URL_FILE", _write(tmp_path, "db", url))

    assert get_settings().database_url == url


def test_empty_environment_value_does_not_block_the_file(tmp_path, monkeypatch) -> None:
    # Compose passes unset variables as empty strings (``${JWT_SECRET:-}``).
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY_FILE", _write(tmp_path, "gemini", "file-key"))

    assert get_settings().gemini_api_key.get_secret_value() == "file-key"


def test_setting_both_a_value_and_a_file_is_an_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    monkeypatch.setenv("GEMINI_API_KEY_FILE", _write(tmp_path, "gemini", "from-file"))

    with pytest.raises(ConfigurationError) as error:
        get_settings()

    assert "GEMINI_API_KEY" in str(error.value)
    assert "not both" in str(error.value)
    assert "from-env" not in str(error.value)
    assert "from-file" not in str(error.value)


def test_missing_and_empty_files_are_reported_by_name(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY_FILE", str(tmp_path / "does-not-exist"))
    monkeypatch.setenv("METRICS_TOKEN_FILE", _write(tmp_path, "empty", "  \n"))

    with pytest.raises(ConfigurationError) as error:
        get_settings()

    message = str(error.value)
    assert "GEMINI_API_KEY_FILE: the file is missing or unreadable" in message
    assert "METRICS_TOKEN_FILE: the file is empty" in message


def test_invalid_configuration_lists_every_problem_without_values(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LLM_MODE", "gemini")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://app:hunter2@db/app")
    monkeypatch.setenv("ANALYTICS_DATABASE_URL", "postgresql+psycopg://ro:hunter3@db/app")
    monkeypatch.setenv("AUTH_MODE", "disabled")

    with pytest.raises(ConfigurationError) as error:
        get_settings()

    message = str(error.value)
    assert message.startswith("Invalid configuration:")
    assert "Production requires AUTH_MODE=jwt." in message
    assert "hunter2" not in message
    assert "hunter3" not in message


def test_field_level_errors_use_the_environment_variable_name(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_DEADLINE_SECONDS", "-5")

    with pytest.raises(ConfigurationError) as error:
        get_settings()

    assert "REQUEST_DEADLINE_SECONDS" in str(error.value)


def test_redis_backend_requires_a_url() -> None:
    with pytest.raises(ValueError, match="REDIS_URL is required"):
        Settings(rate_limit_backend="redis")

    settings = Settings(rate_limit_backend="redis", redis_url="redis://cache:6379/0")
    assert settings.rate_limit_backend == "redis"
    assert "cache:6379" not in repr(settings)


def test_durable_stores_require_postgresql() -> None:
    with pytest.raises(ValueError, match="CONVERSATION_STORE=postgres requires"):
        Settings(conversation_store="postgres")
    with pytest.raises(ValueError, match="AUDIT_SINK=database requires"):
        Settings(audit_sink="database")

    postgres = "postgresql+psycopg://app@db/app"
    assert Settings(conversation_store="postgres", database_url=postgres).conversation_store == (
        "postgres"
    )
    assert Settings(audit_sink="both", database_url=postgres).audit_sink == "both"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("250000", 250000.0), ("", None), ("off", None), ("0", None), ("-1", None)],
)
def test_query_cost_limit_parsing(raw: str, expected: float | None) -> None:
    assert Settings(query_cost_limit=raw).query_cost_limit == expected


def test_query_cost_limit_has_a_safe_default() -> None:
    assert Settings().query_cost_limit == 1_000_000.0
