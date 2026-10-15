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

## 2026-10-15 – Stato del progetto dopo T0.4
- Fatto: PR #1 (`setup/init`) e PR #2 (`setup/architecture`) unite in `main`; T0.2, T0.4, T0.6 chiusi; T0.5 e T2.1 sono liberi.
- Da fare: (1) proteggere `main` → chiude T0.1 e sblocca T0.7; (2) chiudere T0.3: verifica locale del blocco di `.env` via Bash, hook `PreToolUse` (blocco `.env`) e `Stop` (test) → sblocca T1.1 e T3.6; (3) T0.5 e T2.1 in parallelo, anche con worktree.
- Decisioni: i ruoli DEV-1, DEV-2, DEV-3 sono coperti dalla stessa persona; approvazione = merge della PR. Da formalizzare con un ADR e in `WORKFLOW.md` (regola di revisione con un solo account). In attesa di approvazione le dipendenze `openapi-spec-validator` (T0.5), `pyyaml` (T2.2), `jsonschema` (T2.5).
- Impatto sugli altri dev: DEV-2 può iniziare T2.1 (con `schemas.py`, `run_date`, indice univoco su `reports.tender_id`); DEV-3 può iniziare T0.5.

## 2026-10-14 – T0.4 Modello dati e architettura
- Fatto: ARCHITECTURE.md approvato (versione 1.0) con decisioni D1–D7 e prima sintesi TED (Q1–Q11, solo documentazione); ADR-001…005 accettati, ADR-006…010 aggiunti; Fase 0 verificata (T0.2 e T0.6 chiusi).
- Da fare: T0.1 attende la protezione di `main`; T0.3 attende la verifica locale del blocco di `.env` via Bash e gli hook PreToolUse/Stop; T1.1 conferma Q1–Q11 con chiamate reali.
- Decisioni: `TenderCreate` in `backend/domain/schemas.py`; `cpv_codes` JSON; un report per gara; `ingestion_runs.run_date`; punteggio per ogni gara salvata.
- Impatto sugli altri dev: DEV-2 in T2.1 crea anche `schemas.py`, `run_date` e l'indice univoco su `reports.tender_id`; DEV-3 in T0.5 usa `409` per il secondo report e i valori `to_verify` / `verified`.
