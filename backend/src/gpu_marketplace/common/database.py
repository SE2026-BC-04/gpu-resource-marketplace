from sqlalchemy import text
from sqlalchemy.engine import Engine, create_engine as sqlalchemy_create_engine
from sqlalchemy.exc import SQLAlchemyError


def create_engine(database_url: str) -> Engine:
    return sqlalchemy_create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 2})


def database_is_ready(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True
