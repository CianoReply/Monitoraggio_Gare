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

## 2026-10-15 – T0.5 Contratto API
- Fatto: `docs/API_CONTRACT.yaml` (OpenAPI 3.1, 11 endpoint, esempi, errori 404/409/422) unito su develop; `backend/tests/test_api_contract.py` lo valida e controlla che ogni esempio rispetti il proprio schema.
- Da fare: T3.1 (scheletro con dati di prova) in corso; T0.7 attende la protezione di `main`; T3.6 attende T0.3.
- Decisioni: `include_discarded` e `report_status` su `Tender` sono aggiunte al piano (ADR-012); `ai_label` iniziale "Contenuto generato con IA – da revisionare"; `relevance_score` sempre 1-5. Tutti gli errori (404, 409, 422 e anche i 422 di validazione di FastAPI) devono uscire come `{ "error", "message" }`: serve un exception handler dedicato (realizzato in `backend/api/errors.py` in T3.1).
- Impatto sugli altri dev: DEV-2 deve esporre `report_status` da `list_tenders`/`get_tender` e allineare `report_schema.json` (T2.5) a `ReportCreate`. Il contratto cambia solo con PR approvata da tutti.
