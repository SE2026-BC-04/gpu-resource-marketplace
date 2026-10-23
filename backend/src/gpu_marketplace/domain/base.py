from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Only primary keys can be derived from the table name. Every other constraint and index carries an
# explicit name from the GPU-002-A schema matrix because those names are the contract repositories
# use to map database errors.
NAMING_CONVENTION = {"pk": "pk_%(table_name)s"}


class Base(DeclarativeBase):
    """SQLAlchemy metadata root for the Phase 1B tables."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
