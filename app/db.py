from sqlmodel import SQLModel, Session, create_engine
from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)


def init_db() -> None:
    import app.models  # noqa: F401
    from sqlalchemy import text
    SQLModel.metadata.create_all(engine)
    for ddl in [
        "ALTER TABLE notes ADD COLUMN folder_id INTEGER REFERENCES note_folders(id)",
        "ALTER TABLE tasks ADD COLUMN category VARCHAR DEFAULT 'task'",
        "ALTER TABLE tasks ADD COLUMN color VARCHAR DEFAULT 'indigo'",
    ]:
        with engine.begin() as conn:
            try:
                conn.execute(text(ddl))
            except Exception:
                pass


def get_session():
    with Session(engine) as session:
        yield session
