from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String(20), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    salt = Column(String(32), nullable=False)
    tier = Column(String(20), nullable=False, default="free")
    valid_until = Column(DateTime, nullable=True)

    alerts = relationship("Alert", back_populates="user")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_url = Column(Text, nullable=False)
    target_price = Column(Numeric(10, 2), nullable=False)
    active_status = Column(Boolean, default=True, nullable=False)

    user = relationship("User", back_populates="alerts")