"""Stampa un campione di gare salvate con il loro voto e i criteri che lo spiegano.

Serve alla validazione del punteggio con Giuseppe (T2.3): mostra le gare con il voto e i
criteri applicati, così si controlla che l'ordine sia sensato. Uso (con DATABASE_URL impostata):

    python -m backend.domain.scoring_sample --limit 20       # le 20 gare con il voto più alto
    python -m backend.domain.scoring_sample --per-score 4    # 4 gare per ogni voto, da 5 a 1

Il campione include anche le gare scartate dai filtri (ADR-010), con il motivo.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import TextIO

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.config import ScoringConfig, load_scoring_config
from backend.domain.database import create_db_engine, create_session_factory
from backend.domain.models import Tender
from backend.domain.schemas import TenderCreate
from backend.domain.scoring import score_breakdown

DEFAULT_LIMIT = 20
SCORES_DESC = (5, 4, 3, 2, 1)


def _to_create(tender: Tender) -> TenderCreate:
    data = {name: getattr(tender, name) for name in TenderCreate.model_fields}
    deadline = data["submission_deadline"]
    if deadline is not None and deadline.tzinfo is None:  # SQLite non conserva il fuso
        data["submission_deadline"] = deadline.replace(tzinfo=UTC)
    return TenderCreate(**data)


def _order() -> tuple:
    """Voto decrescente, poi scadenza crescente con le gare senza scadenza in fondo."""
    return (
        Tender.relevance_score.desc(),
        Tender.submission_deadline.is_(None),
        Tender.submission_deadline.asc(),
        Tender.id.asc(),
    )


def select_sample(
    session: Session, *, limit: int = DEFAULT_LIMIT, per_score: int | None = None
) -> list[Tender]:
    """Gare del campione: le prime `limit` per voto, oppure `per_score` gare per ogni voto."""
    if per_score is None:
        return list(session.scalars(select(Tender).order_by(*_order()).limit(limit)))
    sample: list[Tender] = []
    for score in SCORES_DESC:
        query = (
            select(Tender)
            .where(Tender.relevance_score == score)
            .order_by(*_order())
            .limit(per_score)
        )
        sample.extend(session.scalars(query))
    return sample


def print_sample(
    session: Session,
    config: ScoringConfig,
    *,
    limit: int = DEFAULT_LIMIT,
    per_score: int | None = None,
    now: datetime | None = None,
    out: TextIO | None = None,
) -> int:
    """Stampa il campione; restituisce quante gare ha stampato."""
    out = out or sys.stdout
    tenders = select_sample(session, limit=limit, per_score=per_score)
    for tender in tenders:
        status = "SCARTATA: " + tender.discard_reason if tender.discard_reason else "tenuta"
        print(f"[{tender.relevance_score}] {tender.publication_number} - {tender.title}", file=out)
        print(
            f"    ente: {tender.buyer_name} | CPV: {', '.join(tender.cpv_codes)} | "
            f"importo: {tender.estimated_value} {tender.currency or ''} | "
            f"scadenza: {tender.submission_deadline} | {status}",
            file=out,
        )
        try:
            breakdown = score_breakdown(_to_create(tender), config, now)
        except ValidationError as exc:  # dati salvati che oggi non passerebbero la validazione
            first = exc.errors()[0]
            print(
                f"    ATTENZIONE: dati non validi, punteggio non ricalcolabile "
                f"({'.'.join(str(p) for p in first['loc'])}: {first['msg']})",
                file=out,
            )
            continue
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
    parser.add_argument(
        "--per-score", type=int, default=None, help="campione stratificato: N gare per ogni voto"
    )
    args = parser.parse_args(argv)
    if args.limit < 1 or (args.per_score is not None and args.per_score < 1):
        parser.error("--limit e --per-score devono essere >= 1")
    engine = create_db_engine()
    with create_session_factory(engine)() as session:
        count = print_sample(
            session, load_scoring_config(), limit=args.limit, per_score=args.per_score
        )
    print(f"\n{count} gare stampate.")


if __name__ == "__main__":
    main()
