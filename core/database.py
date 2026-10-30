import os
import time
from functools import wraps
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import DB_PATH

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"timeout": 60, "check_same_thread": False},
)

Base = declarative_base()

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=60000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def with_db_retry(max_retries: int = 3, delay: float = 0.2):
    """Decorator to retry database operations when encountering transient SQLite lock errors."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except OperationalError as e:
                    if "locked" in str(e).lower() and attempt < max_retries:
                        time.sleep(delay * attempt)
                        last_err = e
                        continue
                    raise
                except Exception:
                    raise
            if last_err:
                raise last_err
        return wrapper
    return decorator
