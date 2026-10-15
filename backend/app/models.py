from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, JSON, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


JsonType = JSON().with_variant(JSONB(), "postgresql")


class StoryVersion(Base):
    __tablename__ = "story_versions"
    __table_args__ = (
        UniqueConstraint("story_id", "story_version", name="uq_story_version_identity"),
        CheckConstraint("approval_status IN ('draft','approved')", name="ck_story_approval_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    story_id: Mapped[str] = mapped_column(String(36), nullable=False)
    story_version: Mapped[str] = mapped_column(String(30), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(30), nullable=False)
    definition: Mapped[dict] = mapped_column(JsonType, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class StoryPresentation(Base):
    __tablename__ = "story_presentations"
    __table_args__ = (CheckConstraint("narration_protocol = 'approved-feedback-1'",
                                     name="ck_narration_protocol"),)

    story_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("story_versions.id"), primary_key=True)
    narration_protocol: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class StorySession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    story_version_id: Mapped[str | None] = mapped_column(ForeignKey("story_versions.id", name="fk_session_story_version"), nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider: Mapped[str] = mapped_column(String(20), default="demo", nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), default="demo", nullable=False)
    requires_assets: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("nodes.id"), nullable=True, index=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    story_version_id: Mapped[str | None] = mapped_column(ForeignKey("story_versions.id", name="fk_node_story_version"), nullable=True)
    scene_id: Mapped[str] = mapped_column(String(64), nullable=False)
    state_snapshot: Mapped[dict] = mapped_column(JsonType, nullable=False)
    rendered_scene: Mapped[dict] = mapped_column(JsonType, nullable=False)
    canon_version: Mapped[str] = mapped_column(String(30), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(30), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    investigation_options: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class TurnEvent(Base):
    __tablename__ = "turn_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("session_id", "idempotency_key", name="uq_run_idempotency"),
        Index("ix_run_session_status", "session_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    parent_node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[dict] = mapped_column(JsonType, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    node_id: Mapped[str | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trace_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_event_seq"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class LLMCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (CheckConstraint("num_nonnulls(run_id, creation_task_id, image_task_id) = 1", name="ck_call_task"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    creation_task_id: Mapped[str | None] = mapped_column(ForeignKey("story_tasks.id"), nullable=True)
    image_task_id: Mapped[str | None] = mapped_column(ForeignKey("image_tasks.id"), nullable=True)
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    span_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    call_status: Mapped[str] = mapped_column(String(30), default="completed", nullable=False)
    usage_status: Mapped[str] = mapped_column(String(30), default="known", nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_cny = mapped_column(Numeric(12, 6), nullable=True)
    price_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class StoryTask(Base):
    __tablename__ = "story_tasks"
    __table_args__ = (UniqueConstraint("session_id", "idempotency_key", name="uq_creation_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False, index=True)
    story_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_task_id: Mapped[str | None] = mapped_column(ForeignKey("story_tasks.id"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    request: Mapped[dict] = mapped_column(JsonType, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    stage: Mapped[str] = mapped_column(String(30), default="generate", nullable=False)
    checkpoint: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    repair_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    candidate_version_id: Mapped[str | None] = mapped_column(ForeignKey("story_versions.id"), nullable=True)
    root_node_id: Mapped[str | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trace_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class StoryTaskEvent(Base):
    __tablename__ = "story_task_events"
    __table_args__ = (UniqueConstraint("task_id", "seq", name="uq_creation_event_seq"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("story_tasks.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JsonType, nullable=False)


class ExecutionTrace(Base):
    __tablename__ = "execution_traces"
    __table_args__ = (
        UniqueConstraint("trace_id", "seq", name="uq_trace_seq"),
        CheckConstraint("num_nonnulls(run_id, creation_task_id, image_task_id) = 1", name="ck_trace_task"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    span_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    creation_task_id: Mapped[str | None] = mapped_column(ForeignKey("story_tasks.id"), nullable=True)
    image_task_id: Mapped[str | None] = mapped_column(ForeignKey("image_tasks.id"), nullable=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    node_id: Mapped[str | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    llm_call_id: Mapped[str | None] = mapped_column(ForeignKey("llm_calls.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payload: Mapped[dict] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class ImageTask(Base):
    __tablename__ = "image_tasks"
    __table_args__ = (UniqueConstraint('session_id', 'idempotency_key', name='uq_image_key'),
                     UniqueConstraint('session_id', 'story_version_id', name='uq_image_story'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey('sessions.id'), nullable=False)
    story_version_id: Mapped[str] = mapped_column(ForeignKey('story_versions.id'), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    recovery_keys: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default='queued', nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trace_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class StoryAsset(Base):
    __tablename__ = "story_assets"
    __table_args__ = (UniqueConstraint('story_version_id', 'kind', 'entity_id', name='uq_asset_slot'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey('image_tasks.id'), nullable=False)
    story_version_id: Mapped[str] = mapped_column(ForeignKey('story_versions.id'), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default='pending', nullable=False)
    prompt: Mapped[str] = mapped_column(String(12000), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[str] = mapped_column(String(20), nullable=False)
    download_url: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class BudgetAccount(Base):
    __tablename__ = 'budget_accounts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class CostReservation(Base):
    __tablename__ = 'cost_reservations'
    attempt_id: Mapped[str] = mapped_column(ForeignKey('execution_traces.id', ondelete='CASCADE'), primary_key=True)
    amount_cny = mapped_column(Numeric(12, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    price_version: Mapped[str] = mapped_column(String(40), nullable=False)
    chargeable: Mapped[bool] = mapped_column(Boolean,default=True,nullable=False)
    call_id: Mapped[str | None] = mapped_column(ForeignKey('llm_calls.id'), nullable=True)
