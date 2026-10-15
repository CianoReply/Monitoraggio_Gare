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
- Fatto: `.github/workflows/ci.yml` (job `lint`: `ruff check` e `ruff format --check`; job `test`: prima `pytest -m contract` cioè la conformità al contratto, poi l'intera suite; job `test-postgres`: servizio PostgreSQL 16 con `TEST_POSTGRES_URL`, solo `-k postgres`; job `docker-build`, saltato finché non esiste un `Dockerfile`, T0.7; timeout di 15 minuti; permessi in sola lettura) e `.github/workflows/claude.yml` (`@claude` con `anthropics/claude-code-action`). Il marker `contract` è registrato in `backend/tests/conftest.py` (non in `pyproject.toml`, file condiviso) e applicato a `test_api_contract.py`, `test_api_skeleton.py` e al test di conformità di `test_api_tenders.py`. `backend/tests/test_ci_workflows.py` controlla la struttura dei due file. Nessun accesso a GitHub: i workflow non sono mai stati eseguiti.
- Sequenza operativa, tutti passi IN ATTESA UMANA:
  1. Caricare il repository su GitHub e attivare Actions; `claude.yml` deve stare sul branch predefinito perché i trigger `issue_comment` e `issues` funzionino (DA VERIFICARE).
  2. Aprire prima una PR di prova (anche con un test volutamente fallito) per far girare `ci.yml`: i nomi dei controlli (`Lint (ruff)`, `Test (pytest, SQLite)`, `Test (pytest, PostgreSQL)`) compaiono tra i controlli selezionabili solo dopo la prima esecuzione.
  3. Poi creare la regola di protezione di `main` (T0.1): PR obbligatoria e quei tre controlli obbligatori. `Build immagine Docker` NON va reso obbligatorio finché non esiste il `Dockerfile` (il job viene saltato). Verificare che la PR con il test fallito non sia unibile.
  4. Per `@claude`: installare la GitHub App di Claude; fissare lo SHA di `anthropics/claude-code-action` al posto del tag `@v1` prima di attivarlo; creare il secret e la variabile `CLAUDE_ENABLED=true` (Settings > Secrets and variables > Actions); poi scrivere `@claude` in una PR di prova.
- Autenticazione `claude.yml` (DA VERIFICARE): attivo `claude_code_oauth_token` con il secret `CLAUDE_CODE_OAUTH_TOKEN` (token dell'abbonamento, il più coerente con gli account Pro; verificare con un account Pro che il token sia ammesso per la CI). Alternativa: `anthropic_api_key` con il secret `ANTHROPIC_API_KEY` (chiave API a pagamento, non inclusa nell'abbonamento). `id-token: write` NON è concesso; se il metodo scelto lo richiede (DA VERIFICARE) va aggiunto.
- Permessi di `claude.yml`: `contents: read` (solo revisione; per far correggere il codice a Claude servirebbe `contents: write`, scelta da fare consapevolmente), `pull-requests: write` e `issues: write` solo per pubblicare i commenti. Il job gira solo con `vars.CLAUDE_ENABLED == 'true'` e solo se l'autore è OWNER, MEMBER o COLLABORATOR.
- Politica delle versioni delle action: dove non è stato possibile verificare gli SHA (nessuna rete verso GitHub) restano i tag maggiori (`actions/checkout@v4`, `actions/setup-python@v5`, `anthropics/claude-code-action@v1`). Prima dell'attivazione fissare lo SHA almeno di `claude-code-action` (riceve un segreto); per le altre action valutare lo stesso con un aggiornamento periodico.
- Decisioni: PyYAML (dipendenza transitiva di `openapi-spec-validator`) è usato solo in `test_ci_workflows.py`, senza nuove dipendenze in `pyproject.toml`; `concurrency` annulla le esecuzioni superate; `/security-review` resta un comando manuale su ogni PR che tocca input esterni.
- Impatto sugli altri dev: dopo l'attivazione, ogni PR dovrà passare ruff (anche `format --check`), pytest e il test di conformità al contratto. I nuovi test di conformità si marcano con `@pytest.mark.contract`.

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
