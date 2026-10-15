# Modulo domain – regole e dati

- **Responsabile:** DEV-2
- **Scopo:** passi ④ Filtro e ⑤ Punteggio, schema del database, documenti di gara e report.

## Cosa espone agli altri moduli
- `models.py`, `schemas.py` (`TenderCreate`, `TenderEvaluation`), `repository.py` (gare, esecuzioni; solo `flush`, il `commit` è di chi chiama)
- `filters.apply_filters` (T2.2) · `scoring.evaluate_tender` (T2.3) · `documents.process_tender_documents` (T2.4) · `reports.py` e `report_schema.json` (T2.5)
- Firme complete, configurazione, fusi orari e limiti noti: [NOTES.md](NOTES.md)

## Task del modulo
T2.1 schema e migrazioni · T2.2 filtri · T2.3 punteggio · T2.4 documenti · T2.5 report · T5.1–T5.3 Skill `analisi-gara`

## Regole specifiche
- Unico modulo che accede direttamente al database; non importa `ingestion` né `api`.
- I modelli seguono `docs/ARCHITECTURE.md`; per cambiarli serve una PR approvata da tutti.
- Soglie, CPV, parole chiave e pesi stanno in `backend/domain/config.toml`, mai nel codice.
- Ogni gara scartata salva il motivo in `discard_reason`; il punteggio è deterministico (nessun LLM).
- Date e ore: sempre con fuso, salvate in UTC (`UtcDateTime`); giorni e date delle etichette in Europe/Rome.
- Download solo per gare con `is_relevant = true`, max 50 MB per file, solo host pubblici, nessun login.
- I campi critici di un report nascono "Da verificare"; il report è `verified` solo con tutti confermati.
- Migrazioni: `alembic -c backend/domain/alembic.ini upgrade head`; dati fittizi: `python -m backend.domain.seed`.
- Per i test usa il subagent `test-writer`; i test non usano la rete (SQLite; PostgreSQL solo con `TEST_POSTGRES_URL`).

## Da completare
- Taratura del punteggio con Giuseppe (T2.3, IN ATTESA UMANA); test PostgreSQL mai eseguiti (DA VERIFICARE).
