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
