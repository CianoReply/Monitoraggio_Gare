"""Stampa un campione di gare salvate con il loro voto e i criteri che lo spiegano.

Serve alla validazione del punteggio con Giuseppe (T2.3): mostra le gare in ordine di
voto, così si controlla che l'ordine sia sensato. Uso (con DATABASE_URL impostata):

    python -m backend.domain.scoring_sample --limit 20

Il campione include anche le gare scartate dai filtri (ADR-010), con il motivo.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import TextIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.config import ScoringConfig, load_scoring_config
from backend.domain.database import create_db_engine, create_session_factory
from backend.domain.models import Tender
from backend.domain.schemas import TenderCreate
from backend.domain.scoring import score_breakdown

DEFAULT_LIMIT = 20


def _to_create(tender: Tender) -> TenderCreate:
    data = {name: getattr(tender, name) for name in TenderCreate.model_fields}
    deadline = data["submission_deadline"]
    if deadline is not None and deadline.tzinfo is None:  # SQLite non conserva il fuso
        data["submission_deadline"] = deadline.replace(tzinfo=UTC)
    return TenderCreate(**data)


def print_sample(
    session: Session,
    config: ScoringConfig,
    *,
    limit: int = DEFAULT_LIMIT,
    now: datetime | None = None,
    out: TextIO | None = None,
) -> int:
    """Stampa le prime `limit` gare per voto salvato; restituisce quante ne ha stampate."""
    out = out or sys.stdout
    tenders = session.scalars(
        select(Tender)
        .order_by(Tender.relevance_score.desc(), Tender.submission_deadline.asc(), Tender.id)
        .limit(limit)
    ).all()
    for tender in tenders:
        breakdown = score_breakdown(_to_create(tender), config, now)
        status = "SCARTATA: " + tender.discard_reason if tender.discard_reason else "tenuta"
        print(f"[{tender.relevance_score}] {tender.publication_number} - {tender.title}", file=out)
        print(
            f"    ente: {tender.buyer_name} | CPV: {', '.join(tender.cpv_codes)} | "
            f"importo: {tender.estimated_value} {tender.currency or ''} | "
            f"scadenza: {tender.submission_deadline} | {status}",
            file=out,
        )
        reasons = "; ".join(f"{c.rule} {c.points:+d} ({c.detail})" for c in breakdown.components)
        print(f"    criteri: {reasons or 'nessuno'} | totale {breakdown.total}", file=out)
        if breakdown.score != tender.relevance_score:
            print(
                f"    ATTENZIONE: ricalcolato {breakdown.score}, salvato {tender.relevance_score}",
                file=out,
            )
    return len(tenders)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="numero di gare")
    args = parser.parse_args(argv)
    engine = create_db_engine()
    with create_session_factory(engine)() as session:
        count = print_sample(session, load_scoring_config(), limit=args.limit)
    print(f"\n{count} gare stampate.")


if __name__ == "__main__":
    main()
