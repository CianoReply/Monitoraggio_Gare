"""osservazione, decisioni e gruppo dei campi del report (ADR-016)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


def upgrade() -> None:
    # batch_alter_table ricrea la tabella su SQLite, che non sa aggiungere vincoli CHECK.
    with op.batch_alter_table("tenders") as batch:
        batch.add_column(
            sa.Column(
                "watch_status",
                _enum("watch_status", "none", "watching", "to_deepen", "candidate", "discarded"),
                server_default="none",
                nullable=False,
            )
        )
        batch.add_column(sa.Column("watched_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column(
                "decision_status",
                _enum("decision_status", "discarded", "monitored", "deepened", "candidate"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("decision_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("decided_by", sa.String(length=200), nullable=True))
    with op.batch_alter_table("report_fields") as batch:
        batch.add_column(
            sa.Column(
                "group",
                _enum("field_group", "key_info", "requirements"),
                server_default="key_info",
                nullable=False,
            )
        )
    # I campi critici dei report già salvati sono requisiti (stessa regola di create_report).
    op.execute(
        sa.text(
            "UPDATE report_fields SET \"group\" = 'requirements' WHERE is_critical = :critical"
        ).bindparams(critical=True)
    )


def downgrade() -> None:
    # I vincoli CHECK degli enum vanno tolti prima delle colonne (SQLite ricrea la tabella).
    with op.batch_alter_table("report_fields") as batch:
        batch.drop_constraint("field_group", type_="check")
        batch.drop_column("group")
    with op.batch_alter_table("tenders") as batch:
        batch.drop_constraint("decision_status", type_="check")
        batch.drop_constraint("watch_status", type_="check")
        batch.drop_column("decided_by")
        batch.drop_column("decided_at")
        batch.drop_column("decision_reason")
        batch.drop_column("decision_status")
        batch.drop_column("watched_at")
        batch.drop_column("watch_status")
