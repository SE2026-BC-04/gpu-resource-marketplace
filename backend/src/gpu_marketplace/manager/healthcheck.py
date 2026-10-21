from gpu_marketplace.common.config import Settings
from gpu_marketplace.common.database import create_engine, database_is_ready


def main() -> int:
    engine = create_engine(Settings().database_url)
    try:
        return 0 if database_is_ready(engine) else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
