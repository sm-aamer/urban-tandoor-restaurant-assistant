import pytest
from pydantic import SecretStr

from app.core.config import Settings


def test_gemini_model_defaults_to_flash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.gemini_model == "gemini-3.8-flash"


def test_gemini_model_can_be_configured_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "custom-gemini-model")

    settings = Settings(_env_file=None)

    assert settings.gemini_model == "custom-gemini-model"


def test_missing_gemini_api_key_does_not_prevent_settings_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.gemini_api_key is None


def test_gemini_api_key_is_secret_and_masked_in_settings_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "test-gemini-api-key"
    monkeypatch.setenv("GEMINI_API_KEY", api_key)

    settings = Settings(_env_file=None)

    assert isinstance(settings.gemini_api_key, SecretStr)
    assert settings.gemini_api_key.get_secret_value() == api_key
    assert api_key not in repr(settings)
    assert api_key not in settings.model_dump_json()
    assert str(settings.gemini_api_key) == "**********"


def test_openrouter_settings_use_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.openrouter_api_key is None
    assert settings.openrouter_model == "openrouter/free"
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"


def test_openrouter_settings_load_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-secret")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/model")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://router.example/v1")

    settings = Settings(_env_file=None)

    assert settings.openrouter_api_key is not None
    assert settings.openrouter_api_key.get_secret_value() == "test-openrouter-secret"
    assert settings.openrouter_model == "test/model"
    assert settings.openrouter_base_url == "https://router.example/v1"


def test_openrouter_api_key_is_masked_in_settings_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "test-openrouter-secret"
    monkeypatch.setenv("OPENROUTER_API_KEY", api_key)

    settings = Settings(_env_file=None)

    assert isinstance(settings.openrouter_api_key, SecretStr)
    assert api_key not in repr(settings)
    assert api_key not in settings.model_dump_json()
    assert str(settings.openrouter_api_key) == "**********"


def test_chat_memory_limits_are_configurable_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHAT_MEMORY_TTL_SECONDS", "600")
    monkeypatch.setenv("CHAT_MEMORY_MAX_CONVERSATIONS", "25")
    monkeypatch.setenv("CHAT_MEMORY_MAX_MESSAGES", "8")
    monkeypatch.setenv("CHAT_MEMORY_MAX_MESSAGE_LENGTH", "1500")

    settings = Settings(_env_file=None)

    assert settings.chat_memory_ttl_seconds == 600
    assert settings.chat_memory_max_conversations == 25
    assert settings.chat_memory_max_messages == 8
    assert settings.chat_memory_max_message_length == 1_500
