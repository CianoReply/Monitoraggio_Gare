"""Modelli SQLAlchemy delle 5 tabelle (docs/ARCHITECTURE.md, sezione 4; aggiunte di ADR-016).

I tipi sono portabili tra PostgreSQL e SQLite: JSON generico, enum come stringhe
con vincolo CHECK (``native_enum=False``), nessun tipo specifico di un solo database.
"""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy import false as sa_false
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime, TypeDecorator

from backend.domain.timeutil import utcnow

# Convenzione di denominazione: vincoli e indici hanno nomi stabili (serve ad Alembic).
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UtcDateTime(TypeDecorator[datetime]):
    """Data e ora con fuso: scrive sempre in UTC e rilegge sempre con fuso UTC.

    SQLite non conserva il fuso (rilegge datetime senza fuso); PostgreSQL sì. Con questo tipo
    il codice vede lo stesso valore su entrambi. Non cambia lo schema (`TIMESTAMP WITH TIME
    ZONE`): nessuna migrazione. Un datetime senza fuso si considera già UTC.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:  # come faceva SQLite: un valore senza fuso si considera UTC
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    """Base dichiarativa condivisa da tutti i modelli."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class DocumentStatus(enum.StrEnum):
    DOWNLOADED = "downloaded"
    NOT_ACCESSIBLE = "not_accessible"
    PENDING = "pending"


class ReportStatus(enum.StrEnum):
    TO_REVIEW = "to_review"
    VERIFIED = "verified"


class VerificationStatus(enum.StrEnum):
    TO_VERIFY = "to_verify"
    VERIFIED = "verified"


class WatchStatus(enum.StrEnum):
    """Stato della gara nella lista "In osservazione" del frontend (migrazione 0002)."""

    NONE = "none"
    WATCHING = "watching"
    TO_DEEPEN = "to_deepen"
    CANDIDATE = "candidate"
    DISCARDED = "discarded"


class DecisionStatus(enum.StrEnum):
    """Decisione presa sulla gara dal frontend (migrazione 0002)."""

    DISCARDED = "discarded"
    MONITORED = "monitored"
    DEEPENED = "deepened"
    CANDIDATE = "candidate"


class FieldGroup(enum.StrEnum):
    """Gruppo di un campo del report: informazioni chiave o requisiti (migrazione 0002)."""

    KEY_INFO = "key_info"
    REQUIREMENTS = "requirements"


class RunStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


def _enum(enum_cls: type[enum.StrEnum], name: str) -> SAEnum:
    """Enum portabile: salvato come stringa, con vincolo CHECK, valori in minuscolo."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [m.value for m in e],
    )


class Tender(Base):
    """Una riga per gara (sezione 4.1)."""

    __tablename__ = "tenders"
    __table_args__ = (
        CheckConstraint(
            "relevance_score BETWEEN 1 AND 5",
            name="relevance_score_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    publication_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    buyer_name: Mapped[str] = mapped_column(String(500))
    buyer_city: Mapped[str | None] = mapped_column(String(200))
    cpv_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    notice_type: Mapped[str] = mapped_column(String(100))
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    publication_date: Mapped[date] = mapped_column(Date, index=True)
    submission_deadline: Mapped[datetime | None] = mapped_column(UtcDateTime(), index=True)
    ted_url: Mapped[str] = mapped_column(String(1000))
    documents_url: Mapped[str | None] = mapped_column(String(1000))
    # Calcolati da filtri (T2.2) e punteggio (T2.3): la gara si salva solo già valutata.
    relevance_score: Mapped[int] = mapped_column(Integer, index=True)
    is_relevant: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    discard_reason: Mapped[str | None] = mapped_column(String(500))
    parent_publication_number: Mapped[str | None] = mapped_column(String(50))
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, onupdate=utcnow)
    # Lavoro dell'utente sul frontend (migrazione 0002): osservazione e decisione.
    watch_status: Mapped[WatchStatus] = mapped_column(
        _enum(WatchStatus, "watch_status"), default=WatchStatus.NONE, server_default="none"
    )
    watched_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    decision_status: Mapped[DecisionStatus | None] = mapped_column(
        _enum(DecisionStatus, "decision_status")
    )
    decision_reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    decided_by: Mapped[str | None] = mapped_column(String(200))

    documents: Mapped[list[Document]] = relationship(
        back_populates="tender", cascade="all, delete-orphan", order_by="Document.id"
    )
    report: Mapped[Report | None] = relationship(
        back_populates="tender", cascade="all, delete-orphan", uselist=False
    )


class Document(Base):
    """Documento di gara (sezione 4.2)."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id"), index=True)
    name: Mapped[str] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[DocumentStatus] = mapped_column(
        _enum(DocumentStatus, "document_status"), default=DocumentStatus.PENDING
    )
    local_path: Mapped[str | None] = mapped_column(String(1000))
    downloaded_at: Mapped[datetime | None] = mapped_column(UtcDateTime())

    tender: Mapped[Tender] = relationship(back_populates="documents")


class Report(Base):
    """Report generato con la Skill; al massimo uno per gara (sezione 4.3, ADR-008)."""

    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("tender_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id"))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[ReportStatus] = mapped_column(
        _enum(ReportStatus, "report_status"), default=ReportStatus.TO_REVIEW
    )
    generated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    ai_label: Mapped[str] = mapped_column(String(500))

    tender: Mapped[Tender] = relationship(back_populates="report")
    fields: Mapped[list[ReportField]] = relationship(
        back_populates="report", cascade="all, delete-orphan", order_by="ReportField.id"
    )


class ReportField(Base):
    """Singolo campo di un report (sezione 4.4)."""

    __tablename__ = "report_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(Text)
    original_value: Mapped[str | None] = mapped_column(Text)
    source_doc: Mapped[str] = mapped_column(String(500))
    source_page: Mapped[int | None] = mapped_column(Integer)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    group: Mapped[FieldGroup] = mapped_column(
        _enum(FieldGroup, "field_group"), default=FieldGroup.KEY_INFO, server_default="key_info"
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        _enum(VerificationStatus, "verification_status"), default=VerificationStatus.TO_VERIFY
    )
    reviewer: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(UtcDateTime())

    report: Mapped[Report] = relationship(back_populates="fields")


class IngestionRun(Base):
    """Storico delle esecuzioni del job giornaliero (sezione 4.5, ADR-009)."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, index=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    status: Mapped[RunStatus] = mapped_column(
        _enum(RunStatus, "run_status"), default=RunStatus.RUNNING
    )
    fetched_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    new_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    relevant_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)
