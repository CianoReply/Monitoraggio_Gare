# Monitoraggio_Gare – Radar Gare IT

Tool SaaS aziendale, realizzato in occasione del Competence Center AI 2026, finalizzato a mostrare un corretto
e ottimale utilizzo di Claude nel pieno delle sue potenzialità.

**Radar Gare IT** raccoglie ogni giorno da [TED](https://ted.europa.eu) le gare con ente appaltante italiano
e ambito IT (CPV 72\*, 48\*, 302\*, 324\*, 642\*), le filtra, assegna un punteggio di pertinenza da 1 a 5
con regole deterministiche e le espone via API REST a un frontend usato dal management.

Il progetto mostra anche come un team di 3 persone costruisce un prodotto complesso con Claude Code:
`CLAUDE.md`, subagent, slash command, hook, worktree, Skill, Plan mode. Il backend **non contiene agenti LLM**.

## Stato

Fase 0 – Fondamenta, in corso. Stato aggiornato di ogni task in [docs/TASKS.md](docs/TASKS.md).

## Stack

Python 3.12 · FastAPI · PostgreSQL (SQLite nei test) · SQLAlchemy 2 · Alembic · APScheduler · httpx · pytest · ruff · Docker Compose

## Avvio rapido

```bash
git clone https://github.com/CianoReply/Monitoraggio_Gare.git
cd Monitoraggio_Gare
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # compila i valori; .env non si versiona
pytest && ruff check .
claude                      # poi: /my-tasks DEV-n
```

L'avvio con Docker (`docker compose up`) arriverà con il task T0.7. Guida completa: [docs/ONBOARDING.md](docs/ONBOARDING.md).

## Struttura

| Percorso | Contenuto | Responsabile |
|---|---|---|
| `backend/ingestion/` | raccolta da TED, parser, deduplica, scheduler | DEV-1 |
| `backend/domain/` | database, filtri, punteggio, documenti, report | DEV-2 |
| `backend/api/` | API REST, revisione umana, qualità e CI | DEV-3 |
| `backend/tests/` | test pytest e fixture TED | tutti |
| `docs/` | documentazione di progetto | vedi [WORKFLOW.md](docs/WORKFLOW.md) |
| `.claude/` | configurazione condivisa di Claude Code: comandi, subagent, permessi, hook | DEV-1 |

## Documentazione

| Documento | A cosa serve |
|---|---|
| [CLAUDE.md](CLAUDE.md) | regole per Claude e per i dev, lette in ogni sessione |
| [docs/TASKS.md](docs/TASKS.md) | task, stati, dipendenze, criteri di completamento |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | flusso, moduli, modello dati |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | come collaboriamo |
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | primo giorno |
| [docs/DECISIONS.md](docs/DECISIONS.md) | decisioni architetturali |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | glossario |
| [docs/source/PIANO_BACKEND.md](docs/source/PIANO_BACKEND.md) | piano completo del backend |

## Comandi di Claude Code del team

| Comando | Cosa fa |
|---|---|
| `/my-tasks DEV-n` | task in corso, prossimo task libero, bloccati, note di handoff rilevanti |
| `/verify` | confronta il lavoro del branch con i criteri "Finito quando" |
| `/handoff` | aggiunge una nota di passaggio in `docs/handoff/DEV-n.md` |

## Team

DEV-1 Tech Lead & Ingestion · DEV-2 Dominio & Dati · DEV-3 API, Qualità & DevOps, poi Frontend · Giuseppe, esperto di dominio
