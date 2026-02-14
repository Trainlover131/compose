"""Database models and session management using SQLAlchemy."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from apps.api.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(String, default="queued", nullable=False)
    progress_step = Column(String, default="uploading")
    prompt = Column(Text, default="")
    preset_id = Column(String, default="snappy-creator")
    original_file_path = Column(String, default="")
    original_filename = Column(String, default="")
    duration_sec = Column(Float, default=0.0)
    transcript_json = Column(JSONB, default=dict)
    analysis_json = Column(JSONB, default=dict)
    edit_plan_json = Column(JSONB, default=dict)
    output_url = Column(String, default="")
    output_file_path = Column(String, default="")
    error = Column(Text, default="")
    error_trace = Column(Text, default="")
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    revisions = relationship("Revision", back_populates="job", order_by="Revision.revision_number")


class Revision(Base):
    __tablename__ = "revisions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    revision_number = Column(Integer, nullable=False)
    instruction = Column(Text, default="")
    patch_json = Column(JSONB, default=dict)
    edit_plan_json = Column(JSONB, default=dict)
    status = Column(String, default="queued")
    output_url = Column(String, default="")
    output_file_path = Column(String, default="")
    error = Column(Text, default="")
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    job = relationship("Job", back_populates="revisions")


class PexelsAssetCache(Base):
    __tablename__ = "pexels_cache"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    url_hash = Column(String, unique=True, nullable=False, index=True)
    query = Column(String, default="")
    pexels_url = Column(String, default="")
    local_path = Column(String, default="")
    attribution = Column(Text, default="")
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
