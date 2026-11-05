import uvicorn

from template_repository.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "template_repository.app:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    main()
