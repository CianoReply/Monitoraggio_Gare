# Onboarding – il primo giorno

Guida per DEV-2 e DEV-3. Tempo stimato: 30 minuti. Se un passo non funziona, scrivilo nel tuo file in [handoff/](handoff/) e avvisa DEV-1.

## 1. Checklist del primo giorno

| # | Passo | Comando o azione |
|---|---|---|
| 1 | Clona il repository | `git clone https://github.com/CianoReply/Monitoraggio_Gare.git && cd Monitoraggio_Gare` |
| 2 | Crea un ambiente virtuale Python 3.12 | `python3.12 -m venv .venv` poi `source .venv/bin/activate` (Windows: `.venv\Scripts\activate`) |
| 3 | Installa le dipendenze | `pip install -e ".[dev]"` |
| 4 | Verifica l'installazione | `pytest` e `ruff check .` devono terminare senza errori |
| 5 | Configura le variabili | `cp .env.example .env` e compila i valori; **`.env` non si versiona e non si apre con Claude** |
| 6 | Installa e apri Claude Code nella radice del repository | installazione: vedi la [documentazione ufficiale](https://code.claude.com/docs); avvio: `claude` |
| 7 | Imposta il modello predefinito | `/model` → Sonnet (vedi [WORKFLOW.md](WORKFLOW.md), sezione 6) |
| 8 | Scopri i tuoi task | `/my-tasks DEV-2` oppure `/my-tasks DEV-3` |
| 9 | Leggi le regole | [CLAUDE.md](../CLAUDE.md) radice, poi il `CLAUDE.md` del tuo modulo |
| 10 | Prendi il primo task | vedi la sezione del tuo ruolo qui sotto |

### Ambiente Docker (T0.7)

Per avere PostgreSQL e API con un solo comando serve Docker con Compose v2 (DA VERIFICARE sui computer dei dev: il compose non è stato provato).

| Azione | Comando |
|---|---|
| Avvio (database, migrazioni, API) | `docker compose up --build` |
| Verifica | `curl http://localhost:8000/health` risponde `{"status":"ok"}`; documentazione su `http://localhost:8000/docs` |
| Dati fittizi | `docker compose exec api python -m backend.domain.seed` |
| Stop | `docker compose down` (con `-v` cancella anche il database e i documenti) |

- Il compose legge le variabili dal file `.env` (passo 5); se manca o i valori sono vuoti valgono i predefiniti di sviluppo, quindi `docker compose up` funziona anche subito dopo il clone. Variabili: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`, `API_PORT`, `CORS_ORIGINS`, `INGESTION_SCHEDULE`, `TED_API_URL`, `TED_CPV_PREFIXES`. Nel compose l'API avvia anche lo scheduler del job giornaliero (`ENABLE_SCHEDULER=true`, un solo worker).
- Le migrazioni (`alembic -c backend/domain/alembic.ini upgrade head`) si applicano a ogni avvio dell'API.
- Database e API sono raggiungibili solo da `localhost`. Il database ha dati persistenti nel volume `db_data`.
- Senza Docker si lavora con l'ambiente virtuale e `uvicorn backend.api.main:app --reload`, con `DATABASE_URL` impostata (es. `sqlite:///radar.db`).

## 2. Cosa leggere, in ordine

1. [CLAUDE.md](../CLAUDE.md) – regole valide per tutti (2 minuti).
2. [TASKS.md](TASKS.md) – i tuoi task e le dipendenze critiche.
3. [ARCHITECTURE.md](ARCHITECTURE.md) – flusso, moduli, modello dati, domande aperte.
4. [WORKFLOW.md](WORKFLOW.md) – giornata tipo, branch, PR, revisioni.
5. [GLOSSARY.md](GLOSSARY.md) – quando incontri un termine nuovo.
6. [source/PIANO_BACKEND.md](source/PIANO_BACKEND.md) – il piano completo, per i dettagli dei tuoi task.

## 3. Prima azione comune: revisione della PR `setup/init`

Tutti i task partono da T0.1–T0.6, che restano `[~]` finché DEV-2 e DEV-3 non approvano la PR `setup/init`.

1. Leggi i file della PR e prova `/my-tasks` con il tuo codice.
2. Verifica che una richiesta a Claude di leggere `.env` venga bloccata.
3. Approva o commenta la PR su GitHub.
4. Partecipa alla riunione di T0.4 (1 ora) per approvare [ARCHITECTURE.md](ARCHITECTURE.md).

## 4. DEV-2 – Dominio e Dati

| Voce | Dettaglio |
|---|---|
| Responsabilità | schema del database, filtri, punteggio, documenti e report; Skill `analisi-gara` con Giuseppe |
| Modulo | [backend/domain/](../backend/domain/CLAUDE.md) |
| Primo task | **T2.1 – Schema del database e migrazioni** (branch `feat/db-schema`), dopo l'approvazione di T0.4 |
| Perché è urgente | T2.1 blocca T1.4 di DEV-1 e T3.2 di DEV-3 |
| Funzionalità di Claude da mostrare nella demo | worktree, subagent `test-writer` in background, Skill, `/verify` |

## 5. DEV-3 – API, Qualità e DevOps (poi Frontend)

| Voce | Dettaglio |
|---|---|
| Responsabilità | API REST, revisione umana, test di integrazione, CI, hook di qualità, Docker; poi il frontend |
| Modulo | [backend/api/](../backend/api/CLAUDE.md) |
| Primo task | **T0.7 – Ambiente locale con Docker** (branch `setup/docker`), appena T0.1 è chiuso; poi **T0.5 – Contratto API** dopo T0.4 |
| Perché è urgente | T0.5 blocca tutto lo sviluppo parallelo e T3.1 |
| Attività aperta in T0.3 | preparare con DEV-1 gli hook `PreToolUse` e `Stop` (vedi nota in [TASKS.md](TASKS.md)) |
| Funzionalità di Claude da mostrare nella demo | hook, `/review`, `/security-review`, GitHub Actions con `@claude` |
