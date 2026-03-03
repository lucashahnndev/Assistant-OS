from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="viewer", nullable=False)  # admin, operator, viewer
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True) # Nullable for system actions or before auth
    username = Column(String, nullable=True) # Snapshot in case user is deleted
    action = Column(String, nullable=False) # e.g., "login", "update_config", "cancel_task"
    target = Column(String, nullable=True) # e.g., "skill:web_search", "session:123"
    payload_hash = Column(String, nullable=True) # SHA256 of the change payload
    details = Column(Text, nullable=True) # Small JSON summary
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

class ConfigVersion(Base):
    __tablename__ = "config_versions"

    id = Column(Integer, primary_key=True, index=True)
    config_json = Column(Text, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    comment = Column(String, nullable=True)


class ExternalAccountConnection(Base):
    __tablename__ = "external_account_connections"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String, nullable=False, index=True)
    provider_account_id = Column(String, nullable=True, index=True)
    account_email = Column(String, nullable=True, index=True)
    account_name = Column(String, nullable=True)
    profile_json = Column(Text, nullable=True)
    encrypted_tokens = Column(Text, nullable=False)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    scopes = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

# Database Setup
import os

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "data")
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR)

DB_PATH = os.path.join(DB_DIR, "portal.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
