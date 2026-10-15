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
- Soglie, CPV, parole chiave e pesi stanno in `backend/domain/config.toml` (TOML, letto con `config.py`; pyyaml non è tra le dipendenze), mai nel codice.
- Ogni gara scartata salva il motivo in `discard_reason`.
- Il punteggio è deterministico: nessuna chiamata a LLM.
- Download solo per gare con `is_relevant = true`, massimo 50 MB per file, nessun login automatico.
- I campi critici di un report nascono "Da verificare"; il report è `verified` solo con tutti confermati.
- Per i test usa il subagent `test-writer`, anche in background o in un worktree.

## Da completare
- Regole di punteggio tarate con Giuseppe (T2.3).
- Classificazione dei link ai documenti (T2.4).

## Database, migrazioni e seed (T2.1)
- `DATABASE_URL` dall'ambiente (vedi `.env.example`); i test usano SQLite, produzione PostgreSQL.
- Configurazione Alembic in `backend/domain/alembic.ini`, migrazioni in `backend/domain/migrations/versions/`.
- Applica: `alembic -c backend/domain/alembic.ini upgrade head` · annulla: `... downgrade base`.
- Nuova migrazione: `alembic -c backend/domain/alembic.ini revision --autogenerate -m "descrizione"`, poi controlla il file (i CHECK degli enum non vanno duplicati).
- Dati fittizi: `python -m backend.domain.seed` (20 gare, 2 report, 2 esecuzioni; idempotente).
- Il repository fa solo `flush`: il `commit` spetta a chi possiede la transazione.
- `upsert_tender(session, TenderCreate, TenderEvaluation)`: la gara si salva solo già valutata (punteggio 1-5 obbligatorio, ADR-010); il job calcola filtri e punteggio prima, nella stessa transazione.
- `list_tenders` segue `GET /tenders` del contratto (sort `relevance|deadline|published`, `include_discarded`, `report_status` derivato incluso negli item, intervalli di scadenza in giorni Europe/Rome). `is_relevant`, `publication_from/to` sono solo per uso interno (`/deadlines`, `/stats`).
- DA VERIFICARE: il filtro `cpv` (CAST della colonna JSON a testo + LIKE) è testato solo su SQLite. Su PostgreSQL esiste `test_cpv_prefix_filter_on_postgres`, saltato senza `TEST_POSTGRES_URL` (es. `postgresql+psycopg://user:pwd@localhost/test`; il test ricrea e poi cancella le tabelle: usare un database di prova).

## Filtri (T2.2)
- Carica la configurazione una volta: `config = load_filters_config()` (da `config.toml`, sezione `[filters]`), poi `filters.apply_filters(tender, buyer_country=..., config=config, now=None) -> FilterResult(kept, reason)`; `reason` va in `discard_reason`. Una funzione per regola: `filter_country`, `filter_cpv`, `filter_notice_type`, `filter_deadline`, `filter_min_value`.
- `buyer_country` è obbligatorio (lo passa il chiamante: `TenderCreate` non ha il paese): codice ISO a 3 lettere o lista di codici come li dà TED (es. `["ITA"]`). `None` = non noto, la gara è tenuta (la query TED già filtra).
- Tipo di avviso: confronto esatto sui codici eForms `notice-type` (ammessi `cn-standard`, `cn-social`, `cn-desg`); `can-*` e `pin-*` scartati. Le rettifiche (`parent_publication_number` valorizzato) passano.
- `currency=None` con importo = euro. Importi in altre valute non si confrontano con la soglia.
- `now` deve avere il fuso orario (altrimenti `ValueError`).
- DA VERIFICARE: i codici `notice-type` degli avvisi pre-eForms.
