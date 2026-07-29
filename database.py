import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

engine = create_engine(
    DATABASE_URL,
    # Test every connection from the pool before using it.
    # If Neon has closed the idle connection, SQLAlchemy will
    # discard it and open a fresh one — preventing the crash.
    pool_pre_ping=True,
    # Recycle connections every 5 minutes (Neon idles out after ~5–10 min)
    pool_recycle=300,
    # Keep TCP sockets alive so the OS/network doesn't silently drop them
    connect_args={
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    },
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
