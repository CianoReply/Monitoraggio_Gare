# Note di passaggio – DEV-1

> Questo file lo scrive **solo DEV-1** (di solito con `/handoff`); tutti gli altri lo leggono.
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

## 2026-10-14 – T0.4 Modello dati e architettura
- Fatto: ARCHITECTURE.md approvato (versione 1.0) con decisioni D1–D7 e prima sintesi TED (Q1–Q11, solo documentazione); ADR-001…005 accettati, ADR-006…010 aggiunti; Fase 0 verificata (T0.2 e T0.6 chiusi).
- Da fare: T0.1 attende la protezione di `main`; T0.3 attende la verifica locale del blocco di `.env` via Bash e gli hook PreToolUse/Stop; T1.1 conferma Q1–Q11 con chiamate reali.
- Decisioni: `TenderCreate` in `backend/domain/schemas.py`; `cpv_codes` JSON; un report per gara; `ingestion_runs.run_date`; punteggio per ogni gara salvata.
- Impatto sugli altri dev: DEV-2 in T2.1 crea anche `schemas.py`, `run_date` e l'indice univoco su `reports.tender_id`; DEV-3 in T0.5 usa `409` per il secondo report e i valori `to_verify` / `verified`.
