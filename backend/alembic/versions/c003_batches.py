"""Append-only evaluation batches over existing evaluation jobs."""

from alembic import op

revision = "c003"
down_revision = "c002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE evaluation_batches (
 id VARCHAR PRIMARY KEY NOT NULL,
 request_id VARCHAR NOT NULL UNIQUE,
 source_batch_id VARCHAR UNIQUE REFERENCES evaluation_batches(id),
 checklist_version_id VARCHAR NOT NULL REFERENCES checklist_versions(id),
 created_at VARCHAR NOT NULL
)
""")
    op.execute("""
CREATE TABLE evaluation_batch_items (
 batch_id VARCHAR NOT NULL REFERENCES evaluation_batches(id),
 evaluation_id VARCHAR NOT NULL REFERENCES evaluations(id),
 position INTEGER NOT NULL CHECK(position > 0),
 PRIMARY KEY(batch_id,position), UNIQUE(batch_id,evaluation_id)
)
""")
    for table in ("evaluation_batches", "evaluation_batch_items"):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER immutable_{table}_{operation.lower()} "
                f"BEFORE {operation} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'immutable batch'); END"
            )


def downgrade():
    raise RuntimeError("Destructive history downgrade is intentionally unsupported")
