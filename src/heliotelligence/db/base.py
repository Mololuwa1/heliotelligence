"""SQLAlchemy declarative base and shared metadata."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Stable constraint naming — required for Alembic autogenerate and TimescaleDB DDL.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# Exported for Alembic env.py
metadata = Base.metadata
