"""Popola il database con 20 gare IT fittizie (dati inventati, non reali) per sviluppo e demo.

Uso (dalla radice del progetto, con DATABASE_URL impostata e le migrazioni applicate):
    python -m backend.domain.seed

È idempotente: le gare già presenti (stesso `publication_number`) non vengono duplicate.
Le date sono relative a oggi, così scadenze e calendario hanno sempre dati futuri.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.database import create_db_engine, create_session_factory
from backend.domain.models import (
    Document,
    DocumentStatus,
    IngestionRun,
    Report,
    ReportField,
    ReportStatus,
    RunStatus,
    Tender,
    VerificationStatus,
)
from backend.domain.repository import upsert_tender
from backend.domain.schemas import TenderCreate, TenderEvaluation

# (titolo, ente, città, CPV, importo, giorni a scadenza (None = nessuna), punteggio, scarto)
_ROWS: list[tuple[str, str, str, list[str], str | None, int | None, int, str | None]] = [
    (
        "Sviluppo e manutenzione evolutiva del sistema informativo regionale",
        "Regione Lombardia",
        "Milano",
        ["72200000", "72262000"],
        "2400000.00",
        28,
        5,
        None,
    ),
    (
        "Servizi cloud IaaS e PaaS per la pubblica amministrazione",
        "Consip S.p.A.",
        "Roma",
        ["72500000", "48000000"],
        "18000000.00",
        35,
        5,
        None,
    ),
    (
        "Piattaforma di gestione documentale e conservazione digitale",
        "Comune di Bologna",
        "Bologna",
        ["72212000", "48310000"],
        "650000.00",
        21,
        4,
        None,
    ),
    (
        "Servizi di cybersecurity e Security Operations Center",
        "ASL Roma 1",
        "Roma",
        ["72700000", "48730000"],
        "1200000.00",
        30,
        4,
        None,
    ),
    (
        "Realizzazione app mobile per i servizi al cittadino",
        "Comune di Torino",
        "Torino",
        ["72212200", "72413000"],
        "320000.00",
        18,
        4,
        None,
    ),
    (
        "Data center e migrazione al cloud qualificato ACN",
        "INPS",
        "Roma",
        ["72300000", "72500000"],
        "9500000.00",
        42,
        5,
        None,
    ),
    (
        "Assistenza tecnica e help desk informatico di secondo livello",
        "Università degli Studi di Padova",
        "Padova",
        ["72253000"],
        "480000.00",
        14,
        3,
        None,
    ),
    (
        "Sviluppo portale web istituzionale e CMS",
        "Città Metropolitana di Napoli",
        "Napoli",
        ["72413000", "72212224"],
        "210000.00",
        25,
        3,
        None,
    ),
    (
        "Sistema di business intelligence e data warehouse sanitario",
        "Azienda Zero Veneto",
        "Padova",
        ["72316000", "48600000"],
        "870000.00",
        33,
        4,
        None,
    ),
    (
        "Fornitura di personal computer e monitor",
        "Comune di Firenze",
        "Firenze",
        ["30213000", "30231300"],
        "150000.00",
        10,
        2,
        None,
    ),
    (
        "Licenze software di produttività e collaborazione",
        "Regione Emilia-Romagna",
        "Bologna",
        ["48000000", "72267000"],
        "760000.00",
        27,
        3,
        None,
    ),
    (
        "Interventi di rete: cablaggio strutturato e Wi-Fi scuole",
        "Provincia di Bergamo",
        "Bergamo",
        ["32400000", "72700000"],
        "540000.00",
        20,
        2,
        None,
    ),
    (
        "Intelligenza artificiale per l'analisi delle pratiche edilizie",
        "Comune di Milano",
        "Milano",
        ["72200000", "72310000"],
        "390000.00",
        38,
        4,
        None,
    ),
    (
        "Sistema di gestione dei servizi sociali e anagrafe assistiti",
        "Comune di Genova",
        "Genova",
        ["72212000", "85320000"],
        None,
        24,
        3,
        None,
    ),
    (
        "Servizi di conduzione applicativa e gestione sistemi",
        "Agenzia delle Entrate-Riscossione",
        "Roma",
        ["72250000", "72267000"],
        "3100000.00",
        45,
        4,
        None,
    ),
    (
        "Lavori di ristrutturazione edificio sede comunale",
        "Comune di Verona",
        "Verona",
        ["45454000"],
        "1800000.00",
        16,
        1,
        "CPV non pertinente (non IT)",
    ),
    (
        "Fornitura di arredi per uffici",
        "Comune di Perugia",
        "Perugia",
        ["39130000"],
        "95000.00",
        12,
        1,
        "CPV non pertinente (non IT)",
    ),
    (
        "Servizi di sviluppo software per il fascicolo sanitario",
        "Regione Toscana",
        "Firenze",
        ["72210000", "72212000"],
        "1650000.00",
        None,
        4,
        None,
    ),
    (
        "Manutenzione hardware e software dei sistemi dell'ente",
        "Comune di Pescara",
        "Pescara",
        ["50320000", "72267000"],
        "60000.00",
        8,
        2,
        "Importo sotto la soglia minima",
    ),
    (
        "Piattaforma di e-procurement e gestione albo fornitori",
        "CINECA",
        "Bologna",
        ["72212000", "48000000"],
        "1050000.00",
        31,
        5,
        None,
    ),
]

_LABEL_TO_REVIEW = "Contenuto generato con IA – da revisionare"
_LABEL_VERIFIED = "Contenuto generato con IA – revisionato da Mario Rossi, {d}"


def _build(index: int, row: tuple[Any, ...], today: date) -> TenderCreate:
    title, buyer, city, cpv, value, days, _score, _discard = row
    deadline = (
        datetime.combine(today + timedelta(days=days), time(12, 0), tzinfo=UTC)
        if days is not None
        else None
    )
    number = f"9{index + 1:05d}-2026"
    return TenderCreate(
        publication_number=number,
        title=title,
        description=f"Gara fittizia di esempio: {title.lower()}.",
        buyer_name=buyer,
        buyer_city=city,
        cpv_codes=cpv,
        notice_type="bando di gara",
        estimated_value=Decimal(value) if value else None,
        currency="EUR" if value else None,
        publication_date=today - timedelta(days=index % 7),
        submission_deadline=deadline,
        ted_url=f"https://example.invalid/ted/{number}",
        documents_url=f"https://example.invalid/documenti/{number}" if index % 2 == 0 else None,
        raw_data={"seed": True, "index": index},
    )


def seed(session: Session, today: date | None = None) -> int:
    """Inserisce le gare fittizie mancanti e alcuni documenti, report e esecuzioni di esempio.

    Restituisce il numero di gare create. Non fa commit.
    """
    today = today or date.today()
    created = 0
    for index, row in enumerate(_ROWS):
        score, discard = row[6], row[7]
        evaluation = TenderEvaluation(score, discard is None and score >= 3, discard)
        tender, is_new = upsert_tender(session, _build(index, row, today), evaluation)
        if not is_new:
            continue
        created += 1
        if tender.is_relevant:
            session.add(
                Document(
                    tender=tender,
                    name="Disciplinare.pdf",
                    url=(
                        "https://example.invalid/documenti/"
                        f"{tender.publication_number}/disciplinare.pdf"
                    ),
                    status=DocumentStatus.PENDING,
                )
            )
    session.flush()
    _seed_reports(session, today)
    _seed_runs(session, today)
    session.flush()
    return created


def _seed_reports(session: Session, today: date) -> None:
    """Due report di esempio: uno `to_review` e uno `verified` (solo se non esistono già)."""
    for number, status in (
        ("900001-2026", ReportStatus.TO_REVIEW),
        ("900002-2026", ReportStatus.VERIFIED),
    ):
        tender = session.scalar(select(Tender).where(Tender.publication_number == number))
        if tender is None or tender.report is not None:
            continue
        verified = (
            VerificationStatus.VERIFIED
            if status is ReportStatus.VERIFIED
            else VerificationStatus.TO_VERIFY
        )
        report = Report(
            tender=tender,
            summary="Report fittizio di esempio: sintesi dell'oggetto e dei requisiti.",
            status=status,
            ai_label=_LABEL_VERIFIED.format(d=today.isoformat())
            if status is ReportStatus.VERIFIED
            else _LABEL_TO_REVIEW,
        )
        report.fields = [
            ReportField(
                label="Scadenza offerte",
                value=str(tender.submission_deadline.date())
                if tender.submission_deadline
                else "n.d.",
                source_doc="Disciplinare.pdf",
                source_page=3,
                is_critical=True,
                verification_status=verified,
            ),
            ReportField(
                label="Fatturato minimo richiesto",
                value="1.000.000 EUR",
                source_doc="Disciplinare.pdf",
                source_page=7,
                is_critical=True,
                verification_status=verified,
            ),
            ReportField(
                label="Criterio di aggiudicazione",
                value="Offerta economicamente più vantaggiosa",
                source_doc="Bando.pdf",
                source_page=1,
                is_critical=False,
                verification_status=VerificationStatus.TO_VERIFY,
            ),
        ]
        session.add(report)


def _seed_runs(session: Session, today: date) -> None:
    if session.scalar(select(IngestionRun.id).limit(1)) is not None:
        return
    now = datetime.now(UTC)
    session.add_all(
        [
            IngestionRun(
                run_date=today - timedelta(days=2),
                started_at=now - timedelta(days=1, hours=1),
                finished_at=now - timedelta(days=1, hours=1) + timedelta(minutes=4),
                status=RunStatus.SUCCESS,
                fetched_count=120,
                new_count=18,
                updated_count=2,
                relevant_count=11,
            ),
            IngestionRun(
                run_date=today - timedelta(days=1),
                started_at=now - timedelta(hours=1),
                finished_at=now - timedelta(hours=1) + timedelta(seconds=30),
                status=RunStatus.FAILED,
                error_message="Servizio TED non raggiungibile (dato di esempio)",
            ),
        ]
    )


def main() -> None:
    engine = create_db_engine()
    with create_session_factory(engine)() as session:
        created = seed(session)
        session.commit()
    print(f"Seed completato: {created} gare create.")


if __name__ == "__main__":
    main()
