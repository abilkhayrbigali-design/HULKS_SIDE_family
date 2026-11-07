from alembic import context
from app.db.session import make_engine
from app.models.data import Base

config = context.config


def run_online(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=Base.metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        run_online(supplied_connection)
    else:
        engine = make_engine(config.get_main_option("sqlalchemy.url"))
        try:
            with engine.connect() as connection:
                run_online(connection)
        finally:
            engine.dispose()
