"""Alembic env: plain SQL migrations, DSN from inventory_common.config (DATABASE_URL or DB_SECRET_ARN)."""

from alembic import context
from sqlalchemy import create_engine, pool

from inventory_common.config import database_dsn


def _url() -> str:
    return database_dsn().replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
