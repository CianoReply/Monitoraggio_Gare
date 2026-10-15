# Note di passaggio – DEV-3

> Questo file lo scrive **solo DEV-3** (di solito con `/handoff`); tutti gli altri lo leggono.
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

## 2026-10-15 – T3.6 Qualità, sicurezza e CI (file pronti, esecuzione su GitHub DA VERIFICARE)
- Fatto: `.github/workflows/ci.yml` (lint con `ruff check` e `ruff format --check`; test con prima la conformità al contratto API e poi l'intera suite; job con servizio PostgreSQL 16 e `TEST_POSTGRES_URL` così il test CPV su PostgreSQL gira; build Docker saltata finché non esiste un `Dockerfile`, T0.7) e `.github/workflows/claude.yml` (`@claude` con `anthropics/claude-code-action@v1`). `backend/tests/test_ci_workflows.py` controlla la struttura dei due file. Nessun accesso a GitHub: i workflow non sono mai stati eseguiti.
- Passi umani, tutti IN ATTESA UMANA: (1) caricare il repository su GitHub e attivare Actions; (2) in Settings > Rules (protezione di `main`, T0.1) richiedere i controlli `Lint (ruff)`, `Test (pytest, SQLite)` e `Test (pytest, PostgreSQL)` e la PR prima del merge; poi aprire una PR con un test volutamente fallito e verificare che il merge sia bloccato; (3) per `@claude`: installare la GitHub App di Claude e creare il secret `ANTHROPIC_API_KEY` oppure `CLAUDE_CODE_OAUTH_TOKEN` (quale sia disponibile con gli account Pro è DA VERIFICARE; il file contiene entrambe le righe, una commentata), controllare versione e input di `claude-code-action`, poi scrivere `@claude` in una PR di prova; (4) `/security-review` resta un comando manuale su ogni PR che tocca input esterni.
- Decisioni: PyYAML (dipendenza transitiva di `openapi-spec-validator`) è usato solo in `test_ci_workflows.py`, senza nuove dipendenze in `pyproject.toml`; permessi del workflow CI in sola lettura; `concurrency` annulla le esecuzioni superate.
- Impatto sugli altri dev: dopo l'attivazione, ogni PR dovrà passare ruff (anche `format --check`), pytest e il test di conformità al contratto.

## 2026-10-15 – T3.2 Elenco delle gare
- Fatto: `GET /tenders` legge dal repository di DEV-2 (`deps.get_session`, `DATABASE_URL`); i `ValueError` del repository sono 422 `validation_error`; scadenza mostrata in Europe/Rome, `created_at`/`updated_at` in UTC. Test con SQLite in memoria e `seed.py` (`backend/tests/api_db.py`), compresi fuso, ricerca letterale di `%` e `_`, prefissi CPV.
- Da fare: T3.3 attende T2.4 e T2.5; T3.4 dopo T3.3; T3.5 dopo T1.6; T0.7 attende la protezione di `main`.
- Decisioni: nessuna logica di filtro nell'API; `min_value`/`max_value` rifiutano `inf` e `nan`.
- Impatto sugli altri dev: nessuno; il repository non è stato modificato.

## 2026-10-15 – T3.1 Struttura dell'API con dati di prova
- Fatto: app FastAPI in `backend/api/` (router per gruppo, schemi Pydantic uguali al contratto, CORS da `CORS_ORIGINS`, handler `{error, message}` per 404/409/422/405/500, dati di prova in `sample_data.py`). I test confrontano `/openapi.json` con il contratto (parametri, corpi, risposte 2xx) e validano le risposte contro gli schemi del contratto.
- Da fare: T3.2 `GET /tenders` dal repository (in corso); poi T3.3-T3.5; T3.6 CI; T0.7 Docker attende la protezione di `main`. Righe da applicare ai file condivisi: `CORS_ORIGINS=http://localhost:3000,http://localhost:5173` in `.env.example`; avvio API `uvicorn backend.api.main:app --reload` nel `CLAUDE.md` radice.
- Decisioni: errori solo con `ApiError(status, codice, messaggio)`; id di percorso `>= 1` (0 è 422, non 404); unica differenza nota tra `/docs` e contratto: l'if/then di `FieldReview` (imposto da un validatore). `ReportCreate.generated_at` accetta assenza ma non `null`.
- Impatto sugli altri dev: nessuno. Il contratto non è cambiato.

## 2026-10-15 – T0.5 Contratto API
- Fatto: `docs/API_CONTRACT.yaml` (OpenAPI 3.1, 11 endpoint, esempi, errori 404/409/422) unito su develop; `backend/tests/test_api_contract.py` lo valida e controlla che ogni esempio rispetti il proprio schema.
- Da fare: T3.1 (scheletro con dati di prova) in corso; T0.7 attende la protezione di `main`; T3.6 attende T0.3.
- Decisioni: `include_discarded` e `report_status` su `Tender` sono aggiunte al piano (ADR-012); `ai_label` iniziale "Contenuto generato con IA – da revisionare"; `relevance_score` sempre 1-5. Tutti gli errori (404, 409, 422 e anche i 422 di validazione di FastAPI) devono uscire come `{ "error", "message" }`: serve un exception handler dedicato (realizzato in `backend/api/errors.py` in T3.1).
- Impatto sugli altri dev: DEV-2 deve esporre `report_status` da `list_tenders`/`get_tender` e allineare `report_schema.json` (T2.5) a `ReportCreate`. Il contratto cambia solo con PR approvata da tutti.
