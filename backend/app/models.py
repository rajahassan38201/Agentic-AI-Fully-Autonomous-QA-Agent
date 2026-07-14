"""Database models: TestRun, Finding, Step."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import deferred, relationship

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
    status = Column(String, nullable=False, default="pending")  # pending|running|completed|failed|stopped
    summary = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    steps_count = Column(Integer, nullable=False, default=0)
    findings_count = Column(Integer, nullable=False, default=0)
    config = Column(JSONB, nullable=True)

    # Token usage accumulated across every Claude API call in the run.
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cache_read_tokens = Column(Integer, nullable=False, default=0)
    cache_write_tokens = Column(Integer, nullable=False, default=0)

    # Full session recording (.webm). `has_video` is a cheap flag so list/detail
    # queries never pull the blob; `video` is deferred and loaded only when the
    # /video endpoint reads it.
    has_video = Column(Boolean, nullable=False, default=False)
    video = deferred(Column(LargeBinary, nullable=True))

    created_at = Column(DateTime(timezone=True), default=_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    findings = relationship("Finding", back_populates="run", cascade="all, delete-orphan")
    steps = relationship("Step", back_populates="run", cascade="all, delete-orphan")

    @property
    def total_tokens(self) -> int:
        return (
            (self.input_tokens or 0)
            + (self.output_tokens or 0)
            + (self.cache_read_tokens or 0)
            + (self.cache_write_tokens or 0)
        )

    @property
    def cost_usd(self) -> float:
        """Approximate USD cost of the run, from its token usage and model pricing."""
        from .config import estimate_cost

        model = (self.config or {}).get("model")
        return estimate_cost(
            model,
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_write_tokens,
        )


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
