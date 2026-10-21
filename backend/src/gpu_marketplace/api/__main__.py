import uvicorn

from gpu_marketplace.api.app import create_app
from gpu_marketplace.common.config import Settings
from gpu_marketplace.common.logging import configure_logging


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        create_app(settings),
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
