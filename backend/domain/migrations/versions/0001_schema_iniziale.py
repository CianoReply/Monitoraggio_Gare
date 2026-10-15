"""schema iniziale

Revision ID: 0001
Revises:
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "success",
                "failed",
                name="run_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("fetched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("new_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("relevant_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
    )
    op.create_index(
        op.f("ix_ingestion_runs_run_date"), "ingestion_runs", ["run_date"], unique=False
    )
    op.create_table(
        "tenders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("publication_number", sa.String(length=50), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("buyer_name", sa.String(length=500), nullable=False),
        sa.Column("buyer_city", sa.String(length=200), nullable=True),
        sa.Column("cpv_codes", sa.JSON(), nullable=False),
        sa.Column("notice_type", sa.String(length=100), nullable=False),
        sa.Column("estimated_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=False),
        sa.Column("submission_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ted_url", sa.String(length=1000), nullable=False),
        sa.Column("documents_url", sa.String(length=1000), nullable=True),
        sa.Column("relevance_score", sa.Integer(), nullable=True),
        sa.Column("is_relevant", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("discard_reason", sa.String(length=500), nullable=True),
        sa.Column("parent_publication_number", sa.String(length=50), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "relevance_score IS NULL OR (relevance_score BETWEEN 1 AND 5)",
            name=op.f("ck_tenders_relevance_score_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenders")),
    )
    op.create_index(
        op.f("ix_tenders_publication_date"), "tenders", ["publication_date"], unique=False
    )
    op.create_index(
        op.f("ix_tenders_publication_number"), "tenders", ["publication_number"], unique=True
    )
    op.create_index(
        op.f("ix_tenders_relevance_score"), "tenders", ["relevance_score"], unique=False
    )
    op.create_index(
        op.f("ix_tenders_submission_deadline"), "tenders", ["submission_deadline"], unique=False
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "downloaded",
                "not_accessible",
                "pending",
                name="document_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("local_path", sa.String(length=1000), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tender_id"], ["tenders.id"], name=op.f("fk_documents_tender_id_tenders")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_tender_id"), "documents", ["tender_id"], unique=False)
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "to_review",
                "verified",
                name="report_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ai_label", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(
            ["tender_id"], ["tenders.id"], name=op.f("fk_reports_tender_id_tenders")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
        sa.UniqueConstraint("tender_id", name=op.f("uq_reports_tender_id")),
    )
    op.create_table(
        "report_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("original_value", sa.Text(), nullable=True),
        sa.Column("source_doc", sa.String(length=500), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("is_critical", sa.Boolean(), server_default="0", nullable=False),
        sa.Column(
            "verification_status",
            sa.Enum(
                "to_verify",
                "verified",
                name="verification_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("reviewer", sa.String(length=200), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_id"], ["reports.id"], name=op.f("fk_report_fields_report_id_reports")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_fields")),
    )
    op.create_index(
        op.f("ix_report_fields_report_id"), "report_fields", ["report_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_report_fields_report_id"), table_name="report_fields")
    op.drop_table("report_fields")
    op.drop_table("reports")
    op.drop_index(op.f("ix_documents_tender_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_tenders_submission_deadline"), table_name="tenders")
    op.drop_index(op.f("ix_tenders_relevance_score"), table_name="tenders")
    op.drop_index(op.f("ix_tenders_publication_number"), table_name="tenders")
    op.drop_index(op.f("ix_tenders_publication_date"), table_name="tenders")
    op.drop_table("tenders")
    op.drop_index(op.f("ix_ingestion_runs_run_date"), table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
