"""Persistent global conservative AI accounting, never a provider invoice."""

from alembic import op

revision = "c004"
down_revision = "c003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE ai_budget_accounts (
 id VARCHAR PRIMARY KEY NOT NULL CHECK(id = 'global'),
 limit_micros INTEGER NOT NULL CHECK(limit_micros BETWEEN 0 AND 9223372036854775807),
 committed_micros INTEGER NOT NULL CHECK(committed_micros BETWEEN 0 AND 9223372036854775807),
 reserved_micros INTEGER NOT NULL CHECK(reserved_micros BETWEEN 0 AND 9223372036854775807),
 accounting_started_at VARCHAR NOT NULL
)
""")
    op.execute("""
CREATE TABLE ai_budget_reservations (
 id VARCHAR PRIMARY KEY NOT NULL,
 account_id VARCHAR NOT NULL REFERENCES ai_budget_accounts(id),
 evaluation_id VARCHAR NOT NULL REFERENCES evaluations(id),
 attempt INTEGER NOT NULL CHECK(attempt > 0),
 quote JSON NOT NULL,
 reserved_micros INTEGER NOT NULL CHECK(reserved_micros BETWEEN 1 AND 9223372036854775807),
 charged_micros INTEGER,
 state VARCHAR NOT NULL CHECK(state IN ('reserved','settled','unknown')),
 created_at VARCHAR NOT NULL,
 settled_at VARCHAR,
 UNIQUE(evaluation_id,attempt),
 CHECK((state = 'settled' AND charged_micros IS NOT NULL
    AND charged_micros BETWEEN 0 AND reserved_micros)
    OR (state != 'settled' AND charged_micros IS NULL))
)
""")
    for table in ("ai_budget_accounts", "ai_budget_reservations"):
        op.execute(
            f"CREATE TRIGGER immutable_{table}_delete BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'immutable budget history'); END"
        )
    op.execute("""
CREATE TRIGGER immutable_budget_reservation_update BEFORE UPDATE ON ai_budget_reservations
WHEN OLD.state != 'reserved' OR NEW.state NOT IN ('settled','unknown')
 OR NEW.id IS NOT OLD.id OR NEW.account_id IS NOT OLD.account_id
 OR NEW.evaluation_id IS NOT OLD.evaluation_id OR NEW.attempt IS NOT OLD.attempt
 OR NEW.quote IS NOT OLD.quote OR NEW.reserved_micros IS NOT OLD.reserved_micros
 OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'immutable budget permission'); END
""")
    op.execute("""
CREATE TRIGGER immutable_budget_account_identity BEFORE UPDATE ON ai_budget_accounts
WHEN NEW.id IS NOT OLD.id OR NEW.accounting_started_at IS NOT OLD.accounting_started_at
BEGIN SELECT RAISE(ABORT, 'immutable accounting boundary'); END
""")


def downgrade():
    raise RuntimeError("Destructive history downgrade is intentionally unsupported")
