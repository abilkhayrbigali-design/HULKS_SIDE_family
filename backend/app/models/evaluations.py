"""Saved evaluation runs and immutable appeal decisions."""

from sqlalchemy import JSON, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.data import Base, now, uuid


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "transcript_version_id"],
            ["transcript_versions.conversation_id", "transcript_versions.id"],
        ),
        CheckConstraint("status IN ('queued', 'running', 'completed', 'failed')"),
        CheckConstraint("revision >= 0"),
        Index("ix_evaluations_status_created", "status", "created_at"),
        Index("ix_evaluations_conversation_created", "conversation_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(primary_key=True, default=uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    transcript_version_id: Mapped[str]
    checklist_version_id: Mapped[str] = mapped_column(ForeignKey("checklist_versions.id"))
    status: Mapped[str] = mapped_column(default="queued")
    revision: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[str] = mapped_column(default=now)
    completed_at: Mapped[str | None]
    original: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    final: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    provenance: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    error: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    review_required: Mapped[bool] = mapped_column(default=False)
    review_reasons: Mapped[list] = mapped_column(JSON, default=list)


class CriterionResult(Base):
    __tablename__ = "criterion_results"
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id"), primary_key=True)
    criterion_id: Mapped[str] = mapped_column(primary_key=True)
    result: Mapped[dict] = mapped_column(JSON)


class Appeal(Base):
    __tablename__ = "appeals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["evaluation_id", "criterion_id"],
            ["criterion_results.evaluation_id", "criterion_results.criterion_id"],
        ),
        CheckConstraint("status IN ('open', 'resolved')"),
        CheckConstraint("base_revision >= 0"),
        Index(
            "ix_appeals_one_open",
            "evaluation_id",
            "criterion_id",
            unique=True,
            sqlite_where=text("status = 'open'"),
        ),
        Index("ix_appeals_status_created", "status", "created_at"),
        Index("ix_appeals_evaluation", "evaluation_id", "criterion_id"),
    )
    id: Mapped[str] = mapped_column(primary_key=True, default=uuid)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id"))
    criterion_id: Mapped[str]
    comment: Mapped[str]
    status: Mapped[str] = mapped_column(default="open")
    base_revision: Mapped[int]
    created_at: Mapped[str] = mapped_column(default=now)


class AppealDecision(Base):
    __tablename__ = "appeal_decisions"
    __table_args__ = (
        CheckConstraint("action IN ('confirm', 'override')"),
        CheckConstraint("expected_revision >= 0"),
    )
    id: Mapped[str] = mapped_column(primary_key=True, default=uuid)
    appeal_id: Mapped[str] = mapped_column(ForeignKey("appeals.id"), unique=True)
    action: Mapped[str]
    reason: Mapped[str]
    expected_revision: Mapped[int]
    created_at: Mapped[str] = mapped_column(default=now)
    result: Mapped[dict] = mapped_column(JSON)
