from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from backend.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
Session = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope():
    with Session() as session:
        with session.begin():
            yield session


def initialize():
    from backend import models  # noqa: F401

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)


def db_health():
    with engine.connect() as conn:
        return {
            "database": conn.scalar(text("SELECT version()")),
            "pgvector": conn.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'")),
        }
