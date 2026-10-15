"""Dati di prova, ricavati dagli esempi di `docs/API_CONTRACT.yaml` (valori fittizi).

Usati da T3.1 finché i router non leggono il repository di `backend/domain` (T3.2 e seguenti).
"""

from datetime import UTC, date, datetime, timedelta, timezone

from backend.api.schemas import (
    Deadline,
    Document,
    Report,
    ReportField,
    Run,
    Stats,
    Tender,
)

_ROME_SUMMER = timezone(timedelta(hours=2))
_ROME_WINTER = timezone(timedelta(hours=1))

AI_LABEL_DEFAULT = "Contenuto generato con IA – da revisionare"

TENDERS: list[Tender] = [
    Tender(
        id=101,
        publication_number="228503-2026",
        title="Servizi di sviluppo e manutenzione evolutiva del sistema informativo regionale",
        description=(
            "Accordo quadro triennale per sviluppo software, manutenzione evolutiva "
            "e supporto applicativo."
        ),
        buyer_name="Regione Lombardia - ARIA S.p.A.",
        buyer_city="Milano",
        cpv_codes=["72200000", "72262000"],
        notice_type="cn-standard",
        estimated_value=2400000.00,
        currency="EUR",
        publication_date=date(2026, 10, 12),
        submission_deadline=datetime(2026, 11, 20, 12, 0, tzinfo=_ROME_WINTER),
        ted_url="https://ted.europa.eu/it/notice/-/detail/228503-2026",
        documents_url="https://www.ariaspa.it/gare/228503-2026",
        relevance_score=5,
        is_relevant=True,
        discard_reason=None,
        parent_publication_number=None,
        report_status="to_review",
        created_at=datetime(2026, 10, 12, 6, 30, tzinfo=UTC),
        updated_at=datetime(2026, 10, 12, 6, 30, tzinfo=UTC),
    ),
    Tender(
        id=102,
        publication_number="231877-2026",
        title="Fornitura di servizi cloud e migrazione dei sistemi dell'ente",
        description=(
            "Servizi di migrazione verso cloud qualificato ACN e gestione dei sistemi per 36 mesi."
        ),
        buyer_name="Comune di Bologna",
        buyer_city="Bologna",
        cpv_codes=["72500000", "72310000"],
        notice_type="cn-standard",
        estimated_value=890000.00,
        currency="EUR",
        publication_date=date(2026, 10, 13),
        submission_deadline=datetime(2026, 10, 21, 13, 0, tzinfo=_ROME_SUMMER),
        ted_url="https://ted.europa.eu/it/notice/-/detail/231877-2026",
        documents_url=None,
        relevance_score=4,
        is_relevant=True,
        discard_reason=None,
        parent_publication_number=None,
        report_status="none",
        created_at=datetime(2026, 10, 13, 6, 30, tzinfo=UTC),
        updated_at=datetime(2026, 10, 14, 6, 30, tzinfo=UTC),
    ),
]

DOCUMENTS: list[Document] = [
    Document(
        id=11,
        tender_id=101,
        name="Disciplinare.pdf",
        url="https://www.ariaspa.it/gare/228503-2026/Disciplinare.pdf",
        status="downloaded",
        local_path="/data/documents/228503-2026/Disciplinare.pdf",
        downloaded_at=datetime(2026, 10, 12, 6, 41, tzinfo=UTC),
    ),
    Document(
        id=12,
        tender_id=101,
        name="Capitolato tecnico.pdf",
        url="https://www.ariaspa.it/gare/228503-2026/Capitolato.pdf",
        status="not_accessible",
        local_path=None,
        downloaded_at=None,
    ),
]

REPORT_101 = Report(
    id=7,
    tender_id=101,
    summary=(
        "Accordo quadro triennale per sviluppo e manutenzione evolutiva del sistema "
        "informativo regionale. Importo a base di gara 2,4 milioni di euro. Requisiti di "
        "fatturato specifico e certificazione ISO 27001."
    ),
    status="to_review",
    generated_at=datetime(2026, 10, 14, 9, 15, tzinfo=UTC),
    ai_label=AI_LABEL_DEFAULT,
    fields=[
        ReportField(
            id=71,
            report_id=7,
            label="Importo a base di gara",
            value="2.400.000 EUR",
            original_value=None,
            source_doc="Disciplinare.pdf",
            source_page=3,
            is_critical=True,
            verification_status="to_verify",
            reviewer=None,
            reviewed_at=None,
        ),
        ReportField(
            id=72,
            report_id=7,
            label="Scadenza offerte",
            value="20/11/2026 ore 12:00",
            original_value=None,
            source_doc="Disciplinare.pdf",
            source_page=1,
            is_critical=False,
            verification_status="to_verify",
            reviewer=None,
            reviewed_at=None,
        ),
    ],
)

REPORT_CREATED = Report(
    id=8,
    tender_id=102,
    summary="Migrazione cloud e gestione sistemi per 36 mesi.",
    status="to_review",
    generated_at=datetime(2026, 10, 14, 9, 15, tzinfo=UTC),
    ai_label=AI_LABEL_DEFAULT,
    fields=[
        ReportField(
            id=81,
            report_id=8,
            label="Importo a base di gara",
            value="890.000 EUR",
            original_value=None,
            source_doc="Disciplinare.pdf",
            source_page=2,
            is_critical=True,
            verification_status="to_verify",
            reviewer=None,
            reviewed_at=None,
        )
    ],
)

DEADLINES: list[Deadline] = [
    Deadline(
        tender_id=102,
        publication_number="231877-2026",
        title="Fornitura di servizi cloud e migrazione dei sistemi dell'ente",
        buyer_name="Comune di Bologna",
        submission_deadline=datetime(2026, 10, 21, 13, 0, tzinfo=_ROME_SUMMER),
        relevance_score=4,
        days_left=6,
        urgency="medium",
    )
]

STATS = Stats(
    new_tenders_today=14,
    relevant_tenders=37,
    deadlines_next_7_days=5,
    reports_to_verify=3,
)

RUNS: list[Run] = [
    Run(
        id=31,
        run_date=date(2026, 10, 14),
        started_at=datetime(2026, 10, 15, 6, 0, 2, tzinfo=UTC),
        finished_at=datetime(2026, 10, 15, 6, 3, 41, tzinfo=UTC),
        status="success",
        fetched_count=212,
        new_count=14,
        updated_count=2,
        relevant_count=9,
        error_message=None,
    )
]

NEW_RUN_ID = 32
