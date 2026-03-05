"""SQLAlchemy models for expert-service."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False, unique=True)
    domain = Column(String, nullable=False)
    config = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    sources = relationship("Source", back_populates="project", cascade="all, delete-orphan")
    entries = relationship("Entry", back_populates="project", cascade="all, delete-orphan")
    claims = relationship("Claim", back_populates="project", cascade="all, delete-orphan")
    nogoods = relationship("Nogood", back_populates="project", cascade="all, delete-orphan")
    assessments = relationship("Assessment", back_populates="project", cascade="all, delete-orphan")
    pipeline_runs = relationship("PipelineRun", back_populates="project", cascade="all, delete-orphan")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("project_id", "slug"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    url = Column(String)
    slug = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    word_count = Column(Integer)
    fetched_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="sources")


class Entry(Base):
    __tablename__ = "entries"

    id = Column(String, primary_key=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    topic = Column(String, nullable=False)
    title = Column(String)
    content = Column(Text, nullable=False)
    source_id = Column(UUID(as_uuid=True), ForeignKey("sources.id"))
    metadata_ = Column("metadata", JSONB)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="entries")


class Claim(Base):
    __tablename__ = "claims"

    id = Column(String, primary_key=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    text = Column(Text, nullable=False)
    status = Column(String, default="IN")
    source = Column(String)
    source_hash = Column(String)
    review_status = Column(String, default="pending")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="claims")


class Nogood(Base):
    __tablename__ = "nogoods"

    id = Column(String, primary_key=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    description = Column(Text, nullable=False)
    resolution = Column(Text)
    claim_ids = Column(JSONB)
    discovered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True))

    project = relationship("Project", back_populates="nogoods")


class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    assessment_type = Column(String, nullable=False)
    input_data = Column(JSONB)
    results = Column(JSONB, nullable=False)
    score = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="assessments")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    graph_name = Column(String, nullable=False)
    thread_id = Column(String, nullable=False)
    status = Column(String, default="running")
    progress = Column(JSONB, default=dict)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True))
    error = Column(Text)

    project = relationship("Project", back_populates="pipeline_runs")


class Embedding(Base):
    __tablename__ = "embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_table = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    label = Column(String)
    embedding = Column(Vector(384), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
