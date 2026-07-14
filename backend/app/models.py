"""Database models: TestRun, Finding, Step."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from .database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TestRun(Base):
    __tablename__ = "test_runs"

    id = Column(String, primary_key=True, default=_uuid)
    target_url = Column(String, nullable=False)
    goals = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending|running|completed|failed
    summary = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    steps_count = Column(Integer, nullable=False, default=0)
    findings_count = Column(Integer, nullable=False, default=0)
    config = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    findings = relationship("Finding", back_populates="run", cascade="all, delete-orphan")
    steps = relationship("Step", back_populates="run", cascade="all, delete-orphan")


class Finding(Base):
    __tablename__ = "findings"

    id = Column(String, primary_key=True, default=_uuid)
    run_id = Column(String, ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    severity = Column(String, nullable=False, default="medium")  # critical|high|medium|low|info
    category = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    steps_to_reproduce = Column(Text, nullable=True)
    expected = Column(Text, nullable=True)
    actual = Column(Text, nullable=True)
    evidence = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)

    run = relationship("TestRun", back_populates="findings")


class Step(Base):
    __tablename__ = "steps"

    id = Column(String, primary_key=True, default=_uuid)
    run_id = Column(String, ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    index = Column(Integer, nullable=False, default=0)
    tool_name = Column(String, nullable=False)
    tool_input = Column(Text, nullable=True)
    result_summary = Column(Text, nullable=True)
    is_error = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=_now)

    run = relationship("TestRun", back_populates="steps")
