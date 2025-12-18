import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://elhaq:elhaq_pass@localhost:5432/elhaq")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("Tables created")