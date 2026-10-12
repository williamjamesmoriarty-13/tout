import os
import sys

from alembic import context
from sqlalchemy import create_engine, pool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import db  # noqa: E402

config = context.config

DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_HOST = os.environ.get("DB_HOST", "postgres")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ["DB_NAME"]
DB_SCHEMA = os.environ.get("DB_SCHEMA", "student_schema")

# IMPORTANT : ne JAMAIS mettre de caractère "%" dans une valeur passée à
# config.set_main_option() / au fichier .ini : alembic.ini est lu par
# configparser, qui interprète "%" comme le début d'une séquence
# d'interpolation et lève une ValueError ("invalid interpolation syntax")
# dès qu'il rencontre une séquence non reconnue (ex: "%3D" venant d'une
# URL-encodée). Le search_path est donc transmis via connect_args,
# jamais dans l'URL elle-même.
db_url = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
connect_args = {"options": f"-c search_path={DB_SCHEMA}"}

config.set_main_option("sqlalchemy.url", db_url)

target_metadata = db.metadata


def run_migrations_offline():
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        version_table_schema=DB_SCHEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = create_engine(
        db_url, poolclass=pool.NullPool, connect_args=connect_args
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=DB_SCHEMA,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
