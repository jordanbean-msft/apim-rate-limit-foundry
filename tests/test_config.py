from template_repository.config import Settings


class TestConfig:
    def test_default_settings(self) -> None:
        settings = Settings()
        assert settings.log_level == "INFO"
        assert settings.port == 8000
        assert settings.host == "0.0.0.0"

    def test_custom_settings(self, monkeypatch: object) -> None:
        import pytest

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("PORT", "9000")
        settings = Settings()
        assert settings.log_level == "DEBUG"
        assert settings.port == 9000
        monkeypatch.undo()
