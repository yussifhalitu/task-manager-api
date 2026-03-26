from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date
from sqlalchemy.sql import func
from database import Base


class TaskModel(Base):
    __tablename__ = "tasks"

    id          = Column(Integer, primary_key=True, index=True)
    title       = Column(String(100), nullable=False)
    description = Column(String(300), nullable=True)
    done        = Column(Boolean, default=False)
    priority    = Column(String(20), default="medium")
    owner       = Column(String(50), nullable=False)
    created_at  = Column(DateTime, server_default=func.now())
    due_date    = Column(Date, nullable=True)      # ← NEW


class UserModel(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String(50), unique=True, nullable=False)
    full_name       = Column(String(100), nullable=False)
    email           = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    disabled        = Column(Boolean, default=False)