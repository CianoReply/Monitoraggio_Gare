# Modulo domain – regole e dati

- **Responsabile:** DEV-2
- **Scopo:** passi ④ Filtro e ⑤ Punteggio, schema del database, documenti di gara e report.

## Cosa espone agli altri moduli
- `models.py`: modelli SQLAlchemy delle 5 tabelle; `schemas.py`: `TenderCreate` (T2.1, ADR-006)
- `repository.py`: `upsert_tender`, `list_tenders` (filtri e paginazione), `get_tender` (T2.1)
- `filters.py`: una funzione per regola, esito "tenuta" o "scartata con motivo" (T2.2)
- `scoring.compute_score(tender) -> int` (T2.3)
- gestione documenti (T2.4) e `report_schema.json` con le regole di verifica (T2.5)

## Task del modulo
T2.1 schema e migrazioni · T2.2 filtri · T2.3 punteggio · T2.4 documenti · T2.5 report · T5.1–T5.3 Skill `analisi-gara`

## Regole specifiche
- Unico modulo che accede direttamente al database; non importa `ingestion` né `api`.
- I modelli seguono esattamente `docs/ARCHITECTURE.md`; per cambiarli serve una PR approvata da tutti.
- Soglie, CPV, parole chiave e pesi stanno in `config.yaml`, mai nel codice.
- Ogni gara scartata salva il motivo in `discard_reason`.
- Il punteggio è deterministico: nessuna chiamata a LLM.
- Download solo per gare con `is_relevant = true`, massimo 50 MB per file, nessun login automatico.
- I campi critici di un report nascono "Da verificare"; il report è `verified` solo con tutti confermati.
- Per i test usa il subagent `test-writer`, anche in background o in un worktree.

## Da completare
- Regole di punteggio tarate con Giuseppe (T2.3).
- Comandi Alembic e uso di `seed.py` (T2.1).
- Classificazione dei link ai documenti (T2.4).
