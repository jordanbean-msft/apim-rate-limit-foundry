from unittest.mock import patch

from template_repository.main import main


class TestMain:
    @patch("template_repository.main.uvicorn.run")
    def test_main_starts_uvicorn(self, mock_run: object) -> None:
        main()

        mock_run.assert_called_once_with(
            "template_repository.app:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
        )

    @patch("template_repository.main.uvicorn.run")
    def test_main_uses_custom_settings(
        self, mock_run: object, monkeypatch: object
    ) -> None:
        monkeypatch.setenv("PORT", "9000")
        monkeypatch.setenv("HOST", "127.0.0.1")

        main()

        mock_run.assert_called_once_with(
            "template_repository.app:app",
            host="127.0.0.1",
            port=9000,
            reload=True,
        )
