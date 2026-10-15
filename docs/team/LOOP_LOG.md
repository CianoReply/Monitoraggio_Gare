# Diario del loop – agent team backend

> Lo scrive solo DEV-1 (lead/orchestratore). Serve a riprendere il lavoro dopo un'interruzione:
> stato = `docs/TASKS.md` + questo file + `docs/handoff/` + branch esistenti.

## Avvio – 2026-10-15

### Composizione del team
| Agente | Ruolo | Modulo | Task | Cartella di lavoro |
|---|---|---|---|---|
| DEV-1 | Tech Lead e orchestratore (sessione principale, Opus) | `backend/ingestion/` | T0.1–T0.4, T0.6, T1.1–T1.6, coordinamento T4.1 e T4.3 | `../wt-dev1` |
| DEV-2 | Dominio & Dati (subagent in background, Sonnet) | `backend/domain/` | T2.1–T2.5, poi T5.x | `../wt-dev2` |
| DEV-3 | API, Qualità & DevOps (subagent in background, Sonnet) | `backend/api/` | T0.5, T0.7, T3.1–T3.6, T4.2 | `../wt-dev3` |

I teammate sono subagent in background e non un "agent team" nativo: la funzione sperimentale non è attiva
in questa sessione (scelta dell'utente del 2026-10-15). I messaggi del protocollo (INIZIO, PRONTO PER MERGE,
MERGED…) coincidono con la fine di un turno del subagent; il lead risponde riprendendolo con un messaggio.

### Parametri
- BRANCH_INTEGRAZIONE = `develop` (creato il 2026-10-15 da `main` @ d0ba2bb)
- CARTELLA_INTEGRAZIONE = `Monitoraggio_Gare_BE` (radice del repository)
- WORKTREE_DEV1/2/3 = `../wt-dev1`, `../wt-dev2`, `../wt-dev3` (branch di appoggio `wip/dev1..3`)
- MAX_GIRI_REVISIONE = 3 · MAX_TENTATIVI_CORREZIONE_TEST = 3 · CHECKPOINT_UMANO_FINE_FASE_0 = sì
- Ambiente: venv condiviso `Monitoraggio_Gare_BE/.venv` (Python 3.14) con le sole dipendenze, senza installare
  il progetto: ogni worktree esegue `pytest` sul proprio codice (il pacchetto `backend` ha `__init__.py`).

### Decisioni dell'utente all'avvio (2026-10-15)
- `develop` creato in locale da `main`.
- Teammate come subagent in background.
- Dipendenza autorizzata: `openapi-spec-validator` (dev, per T0.5). **Non** autorizzate per ora: `pyyaml` (T2.2),
  `jsonschema` (T2.5): chi ne ha bisogno usa la libreria standard o chiede di nuovo all'utente.
- Nessun accesso al remote GitHub (niente fetch né push): tutto resta in locale e lo pubblica l'utente.

### Contraddizioni tra il prompt del loop e i documenti del repository
Per le regole di coordinamento prevale il prompt del loop; per il contenuto tecnico prevale il piano.
1. `docs/TASKS.md` regola 2: dipendenza soddisfatta quando la PR è in `main`. Nel loop: quando il task è unito in `develop`.
2. `docs/WORKFLOW.md`: merge solo tramite PR con revisione su GitHub. Nel loop: merge locale `--no-ff` in `develop`
   dopo l'approvazione del lead (revisione con il subagent code-reviewer); la PR `develop → main` resta all'utente.
3. Formato dei commit: `CLAUDE.md` indica `feat(T2.3): …`, il loop indica `<tipo>(<modulo>): <descrizione> [<task>]`.
   Si usa il formato del loop.
4. `docs/TASKS.md` regola 1: ognuno aggiorna i propri task. Nel loop solo il lead aggiorna `TASKS.md`, su `develop`.
5. T0.4 è già unito (PR #2): il checkpoint umano di fine Fase 0 scatta al merge di T0.5.

### Punti in attesa umana all'avvio
- T0.1: protezione di `main` su GitHub (impostazione del repository). Blocca T0.7.
- T0.3: verifica in locale del blocco di scritture su `.env` via Bash; hook `PreToolUse`/`Stop` (modifica di `.claude/`,
  file condiviso). Blocca T1.1 e T3.6.
- T5.x: `docs/source/prompt_giuseppe/` non esiste → bloccati in attesa dei prompt di Giuseppe.

### Piano di esecuzione
| Ordine | Task | Resp. | Dipende da | Note |
|---|---|---|---|---|
| 1 | T0.5 Contratto API | DEV-3 | T0.4 ✔ | precedenza nei turni di merge |
| 1 | T2.1 Schema DB e migrazioni | DEV-2 | T0.4 ✔ | precedenza nei turni di merge |
| 1 | T0.3 chiusura (hook, verifica `.env`) | DEV-1 | T0.2 ✔ | richiede consenso su `.claude/` |
| ⏸ | Checkpoint umano: modello dati + endpoint | utente | T0.4, T0.5 | il team si ferma |
| 2 | T2.2 Filtri → T2.3 Punteggio | DEV-2 | T2.1 | |
| 2 | T2.5 Report | DEV-2 | T2.1 | senza `jsonschema` |
| 2 | T3.1 API con dati di prova → T3.2 Elenco gare | DEV-3 | T0.5, T2.1 | |
| 2 | T1.1 Studio API TED → T1.2 Client | DEV-1 | T0.3 | unico task con rete verso TED |
| 3 | T1.3 Parser → T1.4 Deduplica | DEV-1 | T1.2, T2.1 | |
| 3 | T2.4 Documenti | DEV-2 | T2.1, T1.3 | |
| 3 | T3.3 Dettaglio → T3.4 Revisione | DEV-3 | T3.2, T2.4, T2.5 | |
| 4 | T1.5 Job → T1.6 Registro esecuzioni | DEV-1 | T1.4, T2.2, T2.3, T2.4 | |
| 4 | T3.5 Scadenze, statistiche | DEV-3 | T3.2, T1.6 | |
| 4 | T3.6 Qualità e CI | DEV-3 | T0.3 | CI GitHub: parti DA VERIFICARE |
| 5 | T0.7 Docker | DEV-3 | T0.1 | in attesa della protezione di `main` |
| 6 | T4.1 → T4.2 → T4.3 | tutti | fasi 1A–1C | |
| – | T5.1–T5.3 | DEV-2 | – | `[!]` in attesa dei prompt di Giuseppe |

## Eventi
| Data | Evento |
|---|---|
| 2026-10-15 | Avvio del loop; creati `develop` e i worktree `wip/dev1..3`; pytest 3/3, ruff OK. |
| 2026-10-15 | Assegnati T2.1 a DEV-2 e T0.5 a DEV-3 (stato [~]); avviati i teammate. |
| 2026-10-15 | DEV-3: PRONTO PER MERGE T0.5 (ee1ff63, 8/8 test). Revisione code-reviewer: MODIFICHE RICHIESTE giro 1 (esempi incoerenti, test degli esempi contro gli schemi, regole di validazione, ai_label, DA VERIFICARE TED). Aggiunte include_discarded e report_status accettate (ADR-012 a cura del lead). |
| 2026-10-15 | DEV-1: T0.3 hook PreToolUse (.env bloccato anche via Bash; ask su API_CONTRACT/ARCHITECTURE), Stop (test), fallback ruff nel venv, ADR-011 proposta, su setup/claude-hooks (51f9b2c, d5bca24). Merge dopo T0.5 per non interferire con DEV-3; serve OK di DEV-2 e DEV-3 su .claude/. |
| 2026-10-15 | MERGED T0.5 – ab2f877 – develop 12/12 (2 giri di revisione). ADR-012 proposta. DEV-3 OK sugli hook di T0.3 (osservazioni non bloccanti: durata dello Stop, python3 su Windows). |
| 2026-10-15 | DEV-2: PRONTO PER MERGE T2.1 (01d30df, 34/34). Revisione avviata. |
| 2026-10-15 | CHECKPOINT UMANO fine Fase 0: team fermo, nessun turno di merge concesso fino all'approvazione dell'utente. |
| 2026-10-15 | Revisione T2.1: MODIFICHE RICHIESTE giro 1 (list_tenders non allineato al contratto; test di database.py; seed). |
| 2026-10-15 | CHECKPOINT APPROVATO dall'utente: modello dati e contratto; ADR-012 accettata; relevance_score NOT NULL con gara salvata già valutata (stessa transazione); ai_label iniziale approvato; pydantic>=2 da dichiarare in pyproject (in T2.1). T0.5 [x]. Ripresa del loop. |
| 2026-10-15 | SBLOCCATO T3.1 (DEV-3). |
| 2026-10-15 | MERGED T2.1 – e23e9d9 – develop 69 + 1 saltato (2 giri). SBLOCCATI T2.2 e T2.5 (DEV-2). Revisione T3.1: MODIFICHE RICHIESTE giro 1. OK di DEV-2 e DEV-3 sugli hook T0.3. tzdata (zoneinfo su Windows) da chiedere all'utente. |
| 2026-10-15 | MERGED T0.3 – 38991d7 – develop 96 + 1 saltato. Blocco via Bash dei file di segreti verificato in locale. T0.3 [x]: SBLOCCATI T1.1 (DEV-1, in corso) e T3.6 (DEV-3, dopo T3.1). |
| 2026-10-15 | MERGED T3.1 – 1cd7ba0 – develop 144 + 1 saltato (2 giri). SBLOCCATI T3.2 (in corso) e T3.6 (DEV-3). Revisione T2.2: MODIFICHE RICHIESTE giro 1. ADR-013 (TOML). T1.1: fixture reali TED raccolte (avvisi IT del 2026-10-14 e change notice). |
| 2026-10-15 | MERGED T1.1 – 58008a5 – develop 151 + 1 saltato. T1.2 in corso (DEV-1). DEV-2: PRONTO T2.2 giro 2. DEV-3: PRONTO T3.2 (revisione avviata). |
| 2026-10-15 | MERGED T2.2 – 10513aa – develop 222 + 1 saltato (2 giri). SBLOCCATO T2.3 (DEV-2, in corso). Revisione T3.2: MODIFICHE RICHIESTE giro 1 (test del fuso, deps, q, cpv). DEV-1: T1.2 pronto (e47f50c), revisione avviata. |
| 2026-10-15 | MERGED T3.2 – a453b32 (DEV-3) e T1.2 – 8e30217 (DEV-1); develop 316 + 1 saltato. In corso: T2.3 (DEV-2), T3.6 (DEV-3), T1.3 (DEV-1). |
| 2026-10-15 | MERGED T1.3 – 206ef37 – develop 385 + 1 saltato. Contraddizione piano/vincoli: tabella di mappatura in MAPPING.md invece che nel CLAUDE.md del modulo (limite 30 righe). SBLOCCATO T2.4 (DEV-2, dopo T2.3). T1.4 in corso (DEV-1). Revisioni: T2.3 e T3.6 MODIFICHE RICHIESTE giro 1. Nota per l'utente: firma di compute_score (con config) diversa da ARCHITECTURE §2. |
| 2026-10-15 | MERGED T3.6 – 31fc6e1 (2 giri). T0.1 segnato fatto con la protezione di `main` IN ATTESA UMANA (regola del loop: i criteri umani non bloccano): SBLOCCATO T0.7 (DEV-3). Docker non installato su questa macchina: `docker compose up` DA VERIFICARE da una persona. DEV-1: T1.4 in attesa di `repository.reset_report_to_review` (chiesto a DEV-2). |
| 2026-10-15 | MERGED T2.3 – fabe2b7 (2 giri) con `reset_report_to_review` per T1.4; develop 496 + 1 saltato. SBLOCCATO T2.4 (DEV-2, prima di T2.5 perché blocca T1.5). Validazione di Giuseppe IN ATTESA UMANA. |
