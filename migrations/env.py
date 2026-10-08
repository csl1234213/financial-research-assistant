import os
import sys
from importlib import import_module
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./financial_rag.db")

config.set_main_option("sqlalchemy.url", DATABASE_URL)

database_module = import_module("storage.database")
for model_module in (
    "billing.models",
    "models.document",
    "models.financial_fact",
    "models.ingestion_persistence",
    "models.llm_provider_setting",
    "models.plan",
    "models.subscription",
    "models.task",
    "models.tenant",
    "models.usage",
    "models.user",
    "models.worker_node",
    "observability.models",
    "storage.agent.models",
):
    import_module(model_module)

target_metadata = database_module.Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(connection=supplied_connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
