"""Saved evaluations, original results and append-only appeal decisions."""

from alembic import op

revision = "c002"
down_revision = "c001"
branch_labels = None
depends_on = None


def upgrade():
    # The definitions are version-local: later ORM changes cannot rewrite this migration.
    op.execute("""
CREATE TABLE evaluations (
 id VARCHAR PRIMARY KEY NOT NULL,
 conversation_id VARCHAR NOT NULL REFERENCES conversations(id),
 transcript_version_id VARCHAR NOT NULL,
 checklist_version_id VARCHAR NOT NULL REFERENCES checklist_versions(id),
 status VARCHAR NOT NULL CHECK(status IN ('queued','running','completed','failed')),
 revision INTEGER NOT NULL CHECK(revision >= 0), created_at VARCHAR NOT NULL,
 completed_at VARCHAR, original JSON, final JSON, provenance JSON, error JSON,
 review_required BOOLEAN NOT NULL, review_reasons JSON NOT NULL,
 FOREIGN KEY(conversation_id,transcript_version_id)
 REFERENCES transcript_versions(conversation_id,id),
 CHECK ((status IN ('queued','running') AND original IS NULL AND final IS NULL
         AND error IS NULL AND completed_at IS NULL AND revision = 0)
 OR (status = 'failed' AND original IS NULL AND final IS NULL
     AND error IS NOT NULL AND completed_at IS NOT NULL AND revision = 0)
 OR (status = 'completed' AND original IS NOT NULL AND final IS NOT NULL
     AND provenance IS NOT NULL AND completed_at IS NOT NULL AND error IS NULL))
)
""")
    op.execute("""
CREATE TABLE criterion_results (
 evaluation_id VARCHAR NOT NULL REFERENCES evaluations(id),
 criterion_id VARCHAR NOT NULL, result JSON NOT NULL,
 PRIMARY KEY(evaluation_id,criterion_id)
)
""")
    op.execute("""
CREATE TABLE appeals (
 id VARCHAR PRIMARY KEY NOT NULL, evaluation_id VARCHAR NOT NULL REFERENCES evaluations(id),
 criterion_id VARCHAR NOT NULL, comment VARCHAR NOT NULL,
 status VARCHAR NOT NULL CHECK(status IN ('open','resolved')),
 base_revision INTEGER NOT NULL CHECK(base_revision >= 0), created_at VARCHAR NOT NULL,
 FOREIGN KEY(evaluation_id,criterion_id) REFERENCES criterion_results(evaluation_id,criterion_id)
)
""")
    op.execute("""
CREATE TABLE appeal_decisions (
 id VARCHAR PRIMARY KEY NOT NULL, appeal_id VARCHAR NOT NULL UNIQUE REFERENCES appeals(id),
 action VARCHAR NOT NULL CHECK(action IN ('confirm','override')), reason VARCHAR NOT NULL,
 expected_revision INTEGER NOT NULL CHECK(expected_revision >= 0),
 created_at VARCHAR NOT NULL, result JSON NOT NULL
)
""")
    for name, table, columns in (
        ("ix_evaluations_status_created", "evaluations", "status,created_at"),
        ("ix_evaluations_conversation_created", "evaluations", "conversation_id,created_at"),
        ("ix_appeals_status_created", "appeals", "status,created_at"),
        ("ix_appeals_evaluation", "appeals", "evaluation_id,criterion_id"),
    ):
        op.execute(f"CREATE INDEX {name} ON {table}({columns})")
    op.execute(
        "CREATE UNIQUE INDEX ix_appeals_one_open ON appeals(evaluation_id,criterion_id) "
        "WHERE status='open'"
    )
    for table in ("criterion_results", "appeal_decisions"):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER immutable_{table}_{operation.lower()} "
                f"BEFORE {operation} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'immutable history'); END"
            )
    op.execute("""
CREATE TRIGGER immutable_evaluation_snapshot BEFORE UPDATE ON evaluations
WHEN NEW.id IS NOT OLD.id OR NEW.conversation_id IS NOT OLD.conversation_id
 OR NEW.transcript_version_id IS NOT OLD.transcript_version_id
 OR NEW.checklist_version_id IS NOT OLD.checklist_version_id
 OR NEW.created_at IS NOT OLD.created_at
 OR (OLD.status IN ('completed','failed') AND
   (NEW.status IS NOT OLD.status OR NEW.original IS NOT OLD.original
    OR NEW.provenance IS NOT OLD.provenance OR NEW.error IS NOT OLD.error
    OR NEW.completed_at IS NOT OLD.completed_at))
BEGIN SELECT RAISE(ABORT, 'immutable evaluation'); END
""")
    op.execute("""
CREATE TRIGGER immutable_appeal BEFORE UPDATE ON appeals
WHEN NEW.id IS NOT OLD.id OR NEW.evaluation_id IS NOT OLD.evaluation_id
 OR NEW.criterion_id IS NOT OLD.criterion_id OR NEW.comment IS NOT OLD.comment
 OR NEW.base_revision IS NOT OLD.base_revision OR NEW.created_at IS NOT OLD.created_at
 OR OLD.status = 'resolved' OR NEW.status != 'resolved'
BEGIN SELECT RAISE(ABORT, 'immutable appeal'); END
""")


def downgrade():
    raise RuntimeError("Destructive history downgrade is intentionally unsupported")
