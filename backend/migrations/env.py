from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database import Base
import app.models  # noqa: F401 - register models in SQLAlchemy metadata.
import app.identity.models  # noqa: F401 - register identity models in SQLAlchemy metadata.
import app.organization.models  # noqa: F401 - register organization tables.
import app.personnel.models  # noqa: F401 - register personnel models.
import app.competence.models  # noqa: F401 - register competence tables.
import app.credentials.models  # noqa: F401 - register credentials tables.
import app.availability.models  # noqa: F401 - register scheduling tables.
import app.work.models  # noqa: F401 - register work management tables.
import app.configuration.models  # noqa: F401 - register configuration tables.

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
