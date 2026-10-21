import uvicorn

from gpu_marketplace_simulator.app import create_app
from gpu_marketplace_simulator.config import Settings


if __name__ == "__main__":
    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=False,
    )
