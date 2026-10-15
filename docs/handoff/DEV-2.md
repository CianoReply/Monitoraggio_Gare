# Note di passaggio – DEV-2

> Questo file lo scrive **solo DEV-2** (di solito con `/handoff`); tutti gli altri lo leggono.
> Le note nuove vanno **in cima**, subito sotto il marcatore `<!-- Note -->` (la nota più recente è sempre la prima). Una nota per sessione o per task.
> Regole complete in [WORKFLOW.md](../WORKFLOW.md).

## Formato di riferimento

```markdown
## AAAA-MM-GG – Tn.n Titolo del task
- Fatto: cosa è stato completato.
- Da fare: cosa manca.
- Decisioni: scelte prese e perché.
- Impatto sugli altri dev: chi deve fare o sapere cosa.
```

---

<!-- Note -->

## 2026-10-15 – T2.1 Schema del database e migrazioni
- Fatto: modelli (5 tabelle), migrazione `0001`, `TenderCreate` e `TenderEvaluation` in `schemas.py`, repository (`upsert_tender`, `get_tender`, `list_tenders`), `seed.py` (20 gare), test su SQLite. Mergiato su develop (e23e9d9).
- Da fare: verificare il filtro `cpv` su PostgreSQL (`TEST_POSTGRES_URL`); `tzdata` per `zoneinfo` su Windows (dipendenza da decidere con l'utente).
- Decisioni: Alembic dentro `backend/domain/` (`alembic -c backend/domain/alembic.ini upgrade head`); `relevance_score` NOT NULL, la gara si salva già valutata (`upsert_tender(session, data, TenderEvaluation)`); `list_tenders` segue `GET /tenders` del contratto; il repository fa solo `flush`.
- Impatto sugli altri dev: DEV-1 calcola filtri e punteggio prima dell'upsert e fornisce datetime con fuso; DEV-3 riceve `TenderRow` con `report_status` e mappa i `ValueError` a 422.
