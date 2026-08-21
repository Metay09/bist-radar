"""Acceptance check for the production PostgreSQL migration target."""

from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings

EXPECTED = {
    "research_baselines",
    "feature_definitions",
    "feature_observations",
    "data_freshness_observations",
    "ml_experiments",
    "research_cycles",
    "research_labels",
    "research_dataset_versions",
    "daily_research_snapshots",
    "weekly_research_reports",
}


def main() -> None:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        dialect = connection.dialect.name
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    if dialect != "postgresql":
        raise RuntimeError(f"production migration acceptance requires PostgreSQL, got {dialect}")
    if revision != "0013":
        raise RuntimeError(f"expected migration head 0013, got {revision}")
    missing = EXPECTED - set(inspect(engine).get_table_names())
    if missing:
        raise RuntimeError(f"missing research tables: {sorted(missing)}")


if __name__ == "__main__":
    main()
