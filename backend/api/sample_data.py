"""Dati di prova, ricavati dagli esempi di `docs/API_CONTRACT.yaml` (valori fittizi).

Restano solo quelli degli endpoint non ancora collegati al dominio (T3.4, T3.5).
"""

from datetime import UTC, date, datetime, timedelta, timezone

from backend.api.schemas import (
    Deadline,
    Report,
    ReportField,
    Run,
    Stats,
)

_ROME_SUMMER = timezone(timedelta(hours=2))

AI_LABEL_DEFAULT = "Contenuto generato con IA – da revisionare"

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
