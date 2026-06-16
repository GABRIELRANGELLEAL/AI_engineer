import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:password@localhost:5432/legal_assistant_db')

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models import Base
    Base.metadata.create_all(bind=engine)


if __name__ == '__main__':
    init_db()
    print("Database initialized")
