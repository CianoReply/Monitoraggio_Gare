# CLAUDE.md – Radar Gare IT

## Progetto
Backend Python che ogni giorno raccoglie da TED le gare IT con ente appaltante italiano,
le filtra, assegna un punteggio di pertinenza da 1 a 5 con regole deterministiche e le espone via API REST.

## Prima di iniziare
1. Leggi [docs/TASKS.md](docs/TASKS.md): stato, dipendenze e criteri "Finito quando" di ogni task.
2. Lavora solo sui task del dev indicato dall'utente (DEV-1, DEV-2 o DEV-3); se non è chiaro, chiedilo.
3. Leggi il `CLAUDE.md` del modulo su cui lavori:
   [ingestion](backend/ingestion/CLAUDE.md) · [domain](backend/domain/CLAUDE.md) · [api](backend/api/CLAUDE.md).
4. Prima di scrivere codice proponi un piano e attendi l'approvazione dell'utente.

## Comandi
| Azione | Comando |
|---|---|
| Installazione (ambiente virtuale attivo) | `pip install -e ".[dev]"` |
| Test | `pytest` |
| Lint | `ruff check .` |
| Formattazione | `ruff format .` |
| Avvio ambiente completo | da completare in T0.7 (DEV-3, `docker compose up`) |
| Avvio API | da completare in T3.1 (DEV-3) |
| Migrazioni | da completare in T2.1 (DEV-2, Alembic) |

## Convenzioni
- Codice, identificatori, tabelle e campi in inglese; documentazione e commenti di progetto in italiano.
- Type hint obbligatori su ogni funzione.
- Un test pytest per ogni funzione pubblica; i test non usano la rete (fixture in `backend/tests/fixtures/`).
- Branch come indicato nel task; commit in Conventional Commits con il codice del task,
  es. `feat(T2.3): punteggio di pertinenza`. Dettagli in [docs/WORKFLOW.md](docs/WORKFLOW.md).
- Aggiorna lo stato dei tuoi task in `docs/TASKS.md` nella stessa PR del codice.

## Vincoli
- Modifica `docs/ARCHITECTURE.md` e `docs/API_CONTRACT.yaml` solo su richiesta esplicita dell'utente.
  Motivo: sono gli accordi tra i moduli; si cambiano solo con PR approvata da tutti e tre i dev.
- Modifica questo `CLAUDE.md` solo su richiesta esplicita dell'utente.
  Motivo: è caricato in ogni sessione di tutti i dev; va tenuto sotto le 80 righe.
- Lavora solo nella cartella del tuo modulo; per toccare un altro modulo chiedi all'utente.
  Motivo: ogni modulo ha un solo responsabile ed evitiamo conflitti di merge.
- Non leggere né scrivere `.env` o altri file con segreti; usa `.env.example` per conoscere le variabili.
  Motivo: i segreti non devono entrare nel contesto di Claude.
- Chiedi all'utente prima di aggiungere una dipendenza in `pyproject.toml`.
  Motivo: lo stack è concordato e condiviso dai tre dev.
- Usa solo dati pubblici (avvisi TED) e codice del progetto, mai dati aziendali riservati.
  Motivo: i tre account Claude Pro sono personali.
- Scrivi "DA VERIFICARE" quando un'informazione dipende da fonti esterne non verificate (API TED, Claude Code).
  Motivo: un dato inventato diventa un errore in tutti e tre i moduli.
- Scrivi le note di passaggio solo nel tuo file `docs/handoff/DEV-n.md`.
  Motivo: un file per dev evita i conflitti di merge.

## Dove trovare i dettagli
| Documento | Contenuto |
|---|---|
| [docs/TASKS.md](docs/TASKS.md) | Tutti i task, stati e dipendenze |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Flusso, moduli, confini, modello dati, domande aperte |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | Giornata tipo, branch, PR, revisioni, uso dell'account Pro |
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | Primo giorno per i nuovi dev |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Decisioni architetturali (ADR) |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | Termini di dominio e tecnici |
| [docs/handoff/](docs/handoff/) | Note di passaggio, un file per dev |
| [docs/source/PIANO_BACKEND.md](docs/source/PIANO_BACKEND.md) | Piano completo: fonte autorevole |
| `docs/API_CONTRACT.yaml` | Contratto API (creato in T0.5) |
| `docs/TED_API_NOTES.md` | Note sull'API TED (create in T1.1) |
| Comandi `/my-tasks DEV-n`, `/verify`, `/handoff` | In `.claude/commands/` |
