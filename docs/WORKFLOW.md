# Workflow – come collaboriamo

> Si modifica solo con una PR approvata da DEV-1, DEV-2 e DEV-3.
> Fonte: [docs/source/PIANO_BACKEND.md](source/PIANO_BACKEND.md), Parte 3.

I tre dev usano **tre account Claude Pro separati**: nessun Claude vede le sessioni degli altri.
**Il repository Git è l'unica memoria comune** ([ADR-003](DECISIONS.md)). Ciò che non è scritto in un file versionato, per gli altri non esiste.

## 1. Giornata tipo

| # | Passo | Cosa fai | Cosa fa Claude |
|---|---|---|---|
| 1 | Aggiornamento | `git checkout main && git pull` | – |
| 2 | Orientamento | apri Claude Code e lancia `/my-tasks DEV-n` | legge [TASKS.md](TASKS.md) e le note in [handoff/](handoff/): task in corso, prossimo task libero, bloccati, note rilevanti |
| 3 | Avvio task | crei il branch indicato nel task (o un worktree, sezione 5) | – |
| 4 | Piano | chiedi un piano prima del codice (Plan mode per i task complessi) | propone il piano senza modificare file |
| 5 | Sviluppo | approvi il piano e segui il lavoro | implementa; l'hook esegue `ruff check` su ogni file `.py` modificato |
| 6 | Verifica | lanci `/verify` | confronta il lavoro con i criteri "Finito quando" e risponde con una tabella di evidenze |
| 7 | PR | aggiorni lo stato del task in `TASKS.md` **nella stessa PR** e apri la PR | – |
| 8 | Fine sessione | lanci `/handoff` | aggiunge in cima a `docs/handoff/DEV-n.md` cosa è fatto, cosa manca, decisioni, impatto sugli altri |

## 2. Convenzioni

### Branch
Il nome è scritto in ogni task di [TASKS.md](TASKS.md). Prefissi in uso nel piano:

| Prefisso | Uso | Esempio |
|---|---|---|
| `setup/` | fondamenta del progetto | `setup/init` |
| `feat/` | nuova funzionalità | `feat/ted-client` |
| `fix/` | correzione | `fix/skill-tuning` |
| `research/` | studio senza codice applicativo | `research/ted-api` |
| `test/` | test trasversali | `test/e2e` |
| `docs/` | solo documentazione | `docs/final-review` |

### Commit
Formato *Conventional Commits* con il codice del task come scope:

```
feat(T2.3): punteggio di pertinenza
fix(T1.3): data di scadenza senza fuso orario
test(T2.2): casi limite della soglia di importo
docs(T0.4): modello dati approvato
chore(T0.1): configurazione di ruff
```

### Pull request
- **Titolo:** codice e titolo del task, es. `T2.3 – Punteggio di pertinenza`.
- **Descrizione:** criteri "Finito quando" spuntati, copiati dalla tabella di `/verify`.
- **Contenuto:** codice, test e aggiornamento dello stato in `TASKS.md`.
- **Merge:** in `main` solo tramite PR con almeno 1 revisione; `main` è protetto (T0.1).

## 3. Revisione a rotazione

| Autore della PR | Revisore |
|---|---|
| DEV-1 | DEV-2 |
| DEV-2 | DEV-3 |
| DEV-3 | DEV-1 |

Il revisore usa `/review` e il subagent `code-reviewer`, che controlla il rispetto di `CLAUDE.md`, dei confini tra moduli e del contratto API.

## 4. File condivisi

| File | Chi lo modifica |
|---|---|
| `CLAUDE.md` (radice) | DEV-1, con PR approvata da tutti |
| [ARCHITECTURE.md](ARCHITECTURE.md) | PR approvata da tutti |
| `API_CONTRACT.yaml` (da T0.5) | PR approvata da tutti |
| `WORKFLOW.md` (questo file) | PR approvata da tutti |
| [DECISIONS.md](DECISIONS.md) | chi prende la decisione, con PR approvata da tutti |
| [TASKS.md](TASKS.md) | ognuno solo i propri task |
| [ONBOARDING.md](ONBOARDING.md) | DEV-1 |
| [GLOSSARY.md](GLOSSARY.md) | tutti |
| `handoff/DEV-n.md` | solo il proprietario del file |
| `backend/<modulo>/CLAUDE.md` | il responsabile del modulo |

"Approvata da tutti" significa: approvazione su GitHub di entrambi gli altri due dev prima del merge.

## 5. Worktree: più task in parallelo

Un *git worktree* è una seconda cartella dello stesso repository su un altro branch, con la propria sessione di Claude Code. Serve ad esempio a far scrivere i test a Claude mentre segui un altro task.

```bash
git worktree add ../Monitoraggio_Gare-<nome> -b <branch>   # crea la cartella sul nuovo branch
cd ../Monitoraggio_Gare-<nome> && claude                    # sessione separata
git worktree remove ../Monitoraggio_Gare-<nome>             # a lavoro unito
```

## 6. Uso efficiente dell'account Pro

| Regola | Perché |
|---|---|
| **Sonnet** come modello predefinito (`/model`) | buon equilibrio tra qualità e consumo dei limiti |
| **Opus** solo per la pianificazione (Fase 0, Plan mode sui task complessi) | è il modello che consuma di più |
| **Haiku** per i subagent di ricerca (`ted-api-researcher`) | le ricerche leggono molte pagine |
| `/clear` tra un task e l'altro | il contesto utile sta nei file, non nella chat |
| `/compact` quando una sessione diventa lunga | riduce il contesto mantenendo il filo |
| Subagent per le ricerche | lavorano in un contesto separato e restituiscono solo una sintesi |
| `CLAUDE.md` brevi, dettagli in `docs/` | i `CLAUDE.md` si caricano in ogni sessione |
| Solo dati pubblici (avvisi TED) e codice del progetto | gli account sono personali: niente dati aziendali riservati |
