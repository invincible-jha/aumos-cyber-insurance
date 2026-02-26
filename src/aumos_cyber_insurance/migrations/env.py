"""Alembic environment configuration for AumOS Cyber Insurance migrations."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from aumos_cyber_insurance.core.models import (  # noqa: F401 — imports register metadata
    EvidencePackage,
    ImpactAnalysis,
    PostureAssessment,
    PremiumRecommendation,
    RiskCalculation,
)
from aumos_common.database import AumOSModel

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = AumOSModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in offline mode (SQL script generation)."""
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
    """Run migrations against a live database connection."""
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
