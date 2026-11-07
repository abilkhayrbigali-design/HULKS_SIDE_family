"""Append-only batch membership reuses the persisted evaluation queue."""

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.data import Base, now, uuid


class EvaluationBatch(Base):
    __tablename__ = "evaluation_batches"

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid)
    request_id: Mapped[str] = mapped_column(unique=True)
    source_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_batches.id"), unique=True
    )
    checklist_version_id: Mapped[str] = mapped_column(ForeignKey("checklist_versions.id"))
    created_at: Mapped[str] = mapped_column(default=now)


class EvaluationBatchItem(Base):
    __tablename__ = "evaluation_batch_items"
    __table_args__ = (CheckConstraint("position > 0"),)

    batch_id: Mapped[str] = mapped_column(ForeignKey("evaluation_batches.id"), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id"), unique=True)
    position: Mapped[int] = mapped_column(primary_key=True)
