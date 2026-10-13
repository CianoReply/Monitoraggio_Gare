# PIANO BACKEND – Radar Gare IT (repository `Monitoraggio_Gare`)

> **Stato del documento:** versione 1.0 – fonte autorevole per l'inizializzazione del repository.
> **Uso:** questo file è il riferimento da cui vengono generati `CLAUDE.md`, `docs/TASKS.md`, `docs/ARCHITECTURE.md` e gli altri file di coordinamento. In caso di dubbio, vale quanto scritto qui.
> **Percorso nel repository:** `docs/source/PIANO_BACKEND.md`

---

## Come leggere questo documento

Il documento è diviso in **6 parti**, da leggere in ordine:

| Parte | Contenuto | Domanda a cui risponde |
|---|---|---|
| **1** | Cosa fa il backend | *Che cosa stiamo costruendo?* |
| **2** | Ruoli dei 3 sviluppatori | *Chi fa cosa?* |
| **3** | Regole di lavoro con i file condivisi | *Come ci coordiniamo senza account Team?* |
| **4** | Task del backend, uno per uno | *Che cosa devo fare, in che ordine, e quando ho finito?* |
| **5** | Calendario | *Quando si fa ogni task?* |
| **6** | Passaggio al frontend | *Cosa serve per partire con Claude Design?* |

Ogni task della Parte 4 segue sempre lo **stesso schema**:

- **Scheda:** responsabile, dipendenze, branch, durata stimata.
- **Obiettivo:** perché esiste il task, in una frase.
- **Cosa fare:** passi numerati, in ordine.
- **Come usare Claude:** funzionalità da usare ed esempio di richiesta.
- **Risultato atteso:** file o componenti prodotti.
- **Il task è finito quando:** criteri verificabili (*Definition of Done*).

---

## Parte 1 – Cosa fa il backend

### 1.1 Il flusso in 6 passi

Ogni mattina il backend esegue automaticamente questa sequenza:

| Passo | Nome | Cosa fa |
|---|---|---|
| ① | **Raccolta** | Chiede a TED le gare pubblicate il giorno precedente |
| ② | **Lettura** | Trasforma i dati TED nel nostro modello dati |
| ③ | **Pulizia** | Elimina i duplicati e collega le rettifiche alla gara originale |
| ④ | **Filtro** | Tiene solo le gare italiane, IT, ancora aperte e sopra la soglia di importo |
| ⑤ | **Punteggio** | Assegna a ogni gara un voto di pertinenza da 1 a 5 |
| ⑥ | **Esposizione** | Rende i dati disponibili al frontend tramite API REST |

In parallelo, per le gare con punteggio alto:
1. il backend **recupera i link ai documenti di gara** (disciplinare, capitolato) e li scarica quando possibile;
2. un dev esegue in Claude Code la **Skill `analisi-gara`** (costruita con i prompt di Giuseppe) sui documenti e **carica il report** nel database;
3. un revisore umano **conferma o corregge** i campi critici del report tramite l'API.

> 📌 **Il backend non contiene agenti LLM.** Tutta la logica automatica (raccolta, filtri, punteggio) è codice tradizionale. Claude si usa **per costruire** il backend e, manualmente, **per analizzare** i documenti di gara.

### 1.2 I tre moduli e i loro responsabili

| Modulo | Cartella | Passi del flusso | Responsabile |
|---|---|---|---|
| **Ingestion** (raccolta dati) | `backend/ingestion/` | ①②③ e scheduler | **DEV-1** |
| **Domain** (regole e dati) | `backend/domain/` | ④⑤, documenti e report | **DEV-2** |
| **API** (esposizione) | `backend/api/` | ⑥, revisione umana, qualità e CI | **DEV-3** |

I moduli comunicano attraverso **due accordi scritti**, definiti nella Fase 0:
1. il **modello dati** (`docs/ARCHITECTURE.md`): com'è fatta una gara nel database;
2. il **contratto API** (`docs/API_CONTRACT.yaml`): cosa espone il backend al frontend.

Una volta fissati questi due accordi, i tre dev possono lavorare **in parallelo** senza aspettarsi a vicenda.

### 1.3 Tecnologie

| Componente | Scelta | Motivo |
|---|---|---|
| Linguaggio | Python 3.12 | Diffuso, ottimo per il parsing di XML/JSON |
| Framework API | FastAPI | Genera automaticamente la documentazione OpenAPI |
| Database | PostgreSQL (SQLite per i test) | Robusto e gratuito |
| Accesso al DB | SQLAlchemy 2 + Alembic | ORM standard e migrazioni versionate |
| Scheduler | APScheduler | Esecuzione giornaliera dentro l'applicazione |
| Client HTTP | httpx | Supporta timeout e retry |
| Test | pytest | Standard Python |
| Lint | ruff | Veloce, unico strumento per lint e formattazione |
| Ambiente | Docker Compose | Stesso ambiente per i 3 dev |

---

## Parte 2 – Ruoli dei 3 sviluppatori

### DEV-1 – Tech Lead e Ingestion
**In sintesi:** prepara le fondamenta del progetto e porta i dati da TED al database.
- Crea il repository, la struttura e la configurazione di Claude (Fase 0).
- Guida la definizione del modello dati e del contratto API.
- Sviluppa client TED, parser, deduplica e scheduler.
- **Funzionalità di Claude da mostrare:** `/init`, *Plan mode*, subagent di ricerca, `CLAUDE.md`.

### DEV-2 – Dominio e Dati
**In sintesi:** decide quali gare contano, quanto contano, e conserva documenti e report.
- Sviluppa schema del database, filtri, punteggio, gestione documenti e report.
- Lavora con Giuseppe per trasformare i suoi prompt nella Skill `analisi-gara`.
- **Funzionalità di Claude da mostrare:** worktree, subagent `test-writer` in background, Skill, `/verify`.

### DEV-3 – API, Qualità e DevOps (poi Frontend)
**In sintesi:** rende i dati utilizzabili e garantisce che tutto funzioni e sia sicuro.
- Sviluppa l'API REST, il flusso di revisione umana, i test di integrazione e la CI.
- Configura gli hook di qualità e l'ambiente Docker.
- A backend completato, realizza il frontend con Claude Design e Claude Code.
- **Funzionalità di Claude da mostrare:** hook, `/review`, `/security-review`, GitHub Actions con `@claude`.

### Giuseppe – Esperto di dominio
- Fornisce i prompt e l'elenco delle informazioni da estrarre dai documenti di gara.
- Valida il punteggio di pertinenza e i report prodotti dalla Skill.

---

## Parte 3 – Regole di lavoro con i file condivisi

I tre dev usano **tre account Claude Pro separati**: Claude non condivide memoria né progetti tra loro. **Il repository Git è l'unica memoria comune.** Ogni Claude sa cosa fare perché legge gli stessi file.

### 3.1 I file di coordinamento

| File | Contenuto | Chi lo modifica |
|---|---|---|
| `CLAUDE.md` (radice) | Regole valide per tutti e istruzione di leggere `docs/TASKS.md` | DEV-1, con PR approvata da tutti |
| `docs/TASKS.md` | Elenco dei task con responsabile, stato, dipendenze, branch | Ognuno **solo i propri task** |
| `docs/ARCHITECTURE.md` | Flusso, moduli e modello dati | Con PR approvata da tutti |
| `docs/API_CONTRACT.yaml` | Contratto API (creato in T0.5) | Con PR approvata da tutti |
| `docs/WORKFLOW.md` | Regole operative di collaborazione | Con PR approvata da tutti |
| `docs/ONBOARDING.md` | Guida al primo giorno | DEV-1 |
| `docs/DECISIONS.md` | Registro delle decisioni architetturali (ADR) | Chi prende la decisione, con PR approvata da tutti |
| `docs/GLOSSARY.md` | Termini di dominio e tecnici | Tutti |
| `docs/handoff/DEV-n.md` | Note di passaggio, **un file per dev** | Solo il dev proprietario del file |
| `backend/<modulo>/CLAUDE.md` | Regole specifiche del modulo | Il responsabile del modulo |

> ℹ️ **Perché un file di handoff per dev:** se tre persone scrivono nello stesso file, nascono conflitti di merge. Con un file per dev ognuno scrive solo nel proprio, e tutti possono leggere quelli degli altri.

### 3.2 La giornata tipo di ogni dev

1. **Inizio sessione:** `git pull`, poi si apre Claude Code e si lancia `/my-tasks DEV-n`.
   Claude legge `docs/TASKS.md` e risponde con: task in corso, prossimo task libero, dipendenze ancora bloccate, ultime note di handoff dei dev da cui si dipende.
2. **Avvio task:** si crea il branch indicato nel task (o un worktree, vedi 3.3) e si chiede a Claude un piano prima di scrivere codice.
3. **Sviluppo:** Claude implementa; gli hook eseguono lint e test dopo le modifiche.
4. **Verifica:** si lancia `/verify`, che confronta il lavoro con i criteri "Il task è finito quando".
5. **Chiusura:** si aggiorna lo stato in `docs/TASKS.md` **nella stessa PR del codice**, poi si apre la PR.
6. **Fine sessione:** `/handoff` aggiunge in cima a `docs/handoff/DEV-n.md` una nota con cosa è fatto, cosa manca, decisioni prese e impatto sugli altri dev.
7. **Revisione:** la PR viene rivista da un altro dev, a rotazione (DEV-1 → DEV-2 → DEV-3 → DEV-1), usando `/review` e il subagent `code-reviewer`.

### 3.3 Worktree: lavorare su più task senza conflitti
Un *git worktree* è una seconda cartella dello stesso repository su un altro branch. Serve quando un dev vuole far lavorare Claude su un task (ad esempio i test) mentre lui ne segue un altro. Ogni worktree ha la propria sessione di Claude Code.

### 3.4 Convenzioni
- **Branch:** `setup/<nome>`, `feat/<nome>`, `fix/<nome>`, `research/<nome>`, come indicato in ogni task.
- **Commit:** formato *Conventional Commits* (`feat:`, `fix:`, `chore:`, `docs:`, `test:`) con il codice del task, ad esempio `feat(T2.3): punteggio di pertinenza`.
- **PR:** titolo con codice del task; descrizione con criteri "finito quando" spuntati.
- **Codice:** nomi in inglese, type hint obbligatori, test per ogni funzione pubblica.
- **Documentazione:** in italiano.

### 3.5 Uso efficiente dell'account Pro
- **Modello predefinito: Sonnet.** Opus solo per la pianificazione (Fase 0), Haiku per i subagent di ricerca.
- **`/clear` tra un task e l'altro:** il contesto utile sta nei file, non nella chat.
- **`/compact`** quando una sessione diventa lunga.
- **Subagent per le ricerche:** lavorano in un contesto separato e restituiscono solo una sintesi.
- **`CLAUDE.md` brevi:** vengono letti in ogni sessione; i dettagli stanno nei documenti in `docs/`.
- **Dati:** su Claude vanno solo dati pubblici (avvisi TED) e codice del progetto, mai dati aziendali riservati.

---

## Parte 4 – Task del backend

### Panoramica

| Fase | Task | Responsabile |
|---|---|---|
| **0 – Fondamenta** | T0.1 → T0.7 | DEV-1 (con DEV-2 e DEV-3) |
| **1A – Ingestion** | T1.1 → T1.6 | DEV-1 |
| **1B – Dominio** | T2.1 → T2.5 | DEV-2 |
| **1C – API e qualità** | T3.1 → T3.6 | DEV-3 |
| **2 – Integrazione** | T4.1 → T4.3 | Tutti |
| **3 – Report con Skill** | T5.1 → T5.3 | DEV-2 + Giuseppe |

### Dipendenze critiche
Se uno di questi task ritarda, ritardano anche gli altri:
- **T0.4 e T0.5** bloccano tutto lo sviluppo parallelo.
- **T2.1** (schema DB) blocca T1.4 di DEV-1 e T3.2 di DEV-3.
- **T2.2 e T2.3** (filtri e punteggio) bloccano T1.5 (job giornaliero).

---

### FASE 0 – Fondamenta *(settimana 1)*

> **Perché è la fase più importante:** qui si definiscono gli accordi (modello dati e contratto API) che permettono ai tre dev di lavorare in parallelo. Un errore qui si ripercuote su tutto il progetto.

#### T0.1 – Creazione del repository e della struttura

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-1 | – | `setup/init` | 0,5 giorni |

**Obiettivo:** dare a tutti la stessa struttura di partenza.

**Cosa fare:**
1. Usare il repository esistente `Monitoraggio_Gare` (privato) e invitare DEV-2 e DEV-3.
2. Creare la struttura delle cartelle:
   ```
   Monitoraggio_Gare/
   ├── backend/
   │   ├── ingestion/
   │   ├── domain/
   │   ├── api/
   │   └── tests/
   │       └── fixtures/
   ├── docs/
   │   ├── source/
   │   └── handoff/
   ├── .claude/
   │   ├── agents/
   │   ├── commands/
   │   └── skills/
   ├── pyproject.toml
   ├── .gitignore
   └── .env.example
   ```
3. Configurare `pyproject.toml` con le dipendenze della Parte 1.3 e gli strumenti di qualità (`ruff`, `pytest`).
4. `.gitignore` deve includere almeno: `.env`, `/data/`, cache Python, ambienti virtuali.
5. `.env.example` elenca le variabili necessarie **senza valori reali**.
6. Proteggere il branch `main`: si modifica solo tramite PR con almeno 1 revisione.

**Come usare Claude:**
> *"Crea la struttura di un progetto Python 3.12 con FastAPI, SQLAlchemy 2, Alembic, APScheduler, httpx e pytest, organizzato nei moduli ingestion, domain e api. Configura ruff e pytest in pyproject.toml. Non scrivere ancora logica applicativa."*

**Risultato atteso:** repository con struttura vuota ma funzionante.

**Il task è finito quando:**
- [ ] i 3 dev hanno clonato il repository;
- [ ] `pytest` e `ruff check` si eseguono senza errori (anche senza test);
- [ ] `main` è protetto.

---

#### T0.2 – Scrittura di `CLAUDE.md`

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-1 (rivedono DEV-2 e DEV-3) | T0.1 | `setup/init` | 0,5 giorni |

**Obiettivo:** fare in modo che i tre Claude seguano le stesse regole.

**Cosa fare:**
1. Lanciare `/init` in Claude Code: Claude analizza il repository e genera un primo `CLAUDE.md`.
2. Rifinirlo a mano. **Massimo 80 righe**, solo queste sezioni:
   - **Progetto:** due righe che descrivono Radar Gare IT.
   - **Prima di iniziare:** leggi `docs/TASKS.md`, lavora solo sui task del dev indicato, leggi il `CLAUDE.md` del modulo su cui lavori.
   - **Comandi:** come avviare l'app, i test, il lint, le migrazioni.
   - **Convenzioni:** nomi in inglese nel codice, type hint obbligatori, test per ogni funzione pubblica.
   - **Vincoli** (ognuno con la motivazione): modifica `docs/ARCHITECTURE.md` e `docs/API_CONTRACT.yaml` solo su richiesta esplicita; non leggere né scrivere `.env`; chiedi prima di aggiungere dipendenze.
   - **Dove trovare i dettagli:** link ai documenti in `docs/`.
2. Creare un `CLAUDE.md` in ciascun modulo (`backend/ingestion/`, `backend/domain/`, `backend/api/`), **massimo 30 righe**, con responsabile, scopo, cosa espone agli altri moduli, task del modulo, regole specifiche e una sezione "Da completare".

**Come usare Claude:** `/init`, poi:
> *"Riduci questo CLAUDE.md alle sole sezioni Progetto, Prima di iniziare, Comandi, Convenzioni, Vincoli e Dove trovare i dettagli. Massimo 80 righe."*

**Risultato atteso:** `CLAUDE.md` in radice + 3 `CLAUDE.md` di modulo.

**Il task è finito quando:**
- [ ] DEV-2 e DEV-3 hanno approvato la PR;
- [ ] in una nuova sessione, alla domanda *"quali sono le regole del progetto?"*, Claude risponde correttamente.

> 💡 **Perché deve essere breve:** `CLAUDE.md` viene letto in ogni sessione e consuma contesto e limiti dell'account Pro ogni volta.

---

#### T0.3 – Configurazione condivisa di Claude (`.claude/`)

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-1 (hook preparati con DEV-3) | T0.2 | `setup/init` | 1 giorno |

**Obiettivo:** dare a tutti gli stessi permessi, hook, subagent e comandi.

**Cosa fare:**

**1. Permessi** in `.claude/settings.json`:
- *consentiti senza conferma:* `pytest`, `ruff`, `alembic`, `git status`, `git diff`, `git log`;
- *vietati:* lettura e scrittura di `.env` e di file con segreti, `git push --force`.

**2. Hook** in `.claude/settings.json`:

| Hook | Quando scatta | Cosa fa |
|---|---|---|
| `PreToolUse` | Prima che Claude modifichi un file | Blocca le modifiche a `.env`, `docs/API_CONTRACT.yaml`, `docs/ARCHITECTURE.md` |
| `PostToolUse` | Dopo ogni modifica a un file `.py` | Esegue `ruff check` sul file modificato |
| `Stop` | Quando Claude termina la risposta | Esegue i test del modulo e segnala eventuali errori |

> ⚠️ La sintassi di permessi e hook va verificata nella documentazione ufficiale di Claude Code prima di scrivere il file. Se non è verificabile, si configurano solo i permessi e gli hook restano come attività aperta di T0.3.

**3. Subagent** in `.claude/agents/` (un file `.md` per agent, con frontmatter: `name`, `description`, `tools`, `model`):

| Subagent | Modello | Strumenti | Compito |
|---|---|---|---|
| `ted-api-researcher` | Haiku | Solo lettura e ricerca web | Studia la documentazione TED e restituisce una sintesi con fonti; marca "DA VERIFICARE" ciò che non è certo |
| `test-writer` | Sonnet | Lettura e scrittura nei test | Scrive test pytest che non usano la rete (usa `backend/tests/fixtures/`) |
| `code-reviewer` | Sonnet | Solo lettura | Rivede il codice rispetto a `CLAUDE.md`, ai confini tra moduli e al contratto API |

**4. Comandi di team** in `.claude/commands/`:

| Comando | Cosa chiede a Claude |
|---|---|
| `/my-tasks DEV-n` | Leggi `docs/TASKS.md` e mostrami: task in corso, prossimo task con dipendenze soddisfatte, task bloccati con il motivo, ultima nota in `docs/handoff/` dei dev da cui dipendono i miei task |
| `/verify` | Individua il task corrente dal branch, confronta il lavoro con i criteri "finito quando" e restituisci una tabella: criterio, verificato sì/no, evidenza. Ciò che non è verificabile va dichiarato, non presunto |
| `/handoff` | Aggiungi in cima a `docs/handoff/<dev>.md` una nota con data, task, cosa è fatto, cosa manca, decisioni prese, impatto sugli altri dev |

**Come usare Claude:**
> *"Crea in .claude/commands/ il comando my-tasks che riceve come argomento il codice del dev (es. DEV-2), legge docs/TASKS.md e restituisce: task in corso, prossimo task con dipendenze soddisfatte, task bloccati e perché, ultime note di handoff rilevanti."*

**Risultato atteso:** cartella `.claude/` completa e versionata.

**Il task è finito quando:**
- [ ] ognuno dei tre dev ha provato `/my-tasks` e ottiene i propri task;
- [ ] una modifica a `.env` tramite Claude viene bloccata;
- [ ] un errore di lint introdotto di proposito viene segnalato dall'hook.

---

#### T0.4 – Modello dati e architettura

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-1 guida, **tutti partecipano** | T0.1 | `setup/architecture` | 1 giorno |

**Obiettivo:** concordare com'è fatta una gara nel nostro sistema. È il primo accordo tra i moduli.

**Cosa fare:**
1. Lanciare il subagent `ted-api-researcher` per una prima sintesi dei dati restituiti da TED (il dettaglio è in T1.1).
2. Entrare in **Plan mode** e chiedere a Claude di proporre architettura e modello dati. In Plan mode Claude ragiona e propone **senza modificare file**.
3. Discutere la proposta in una riunione di 1 ora tra i tre dev.
4. Scrivere il risultato in `docs/ARCHITECTURE.md`, con un diagramma Mermaid del flusso, la tabella dei moduli e il modello dati.
5. Registrare in `docs/DECISIONS.md` le decisioni prese.

**Modello dati di partenza** (da validare nella riunione):

| Tabella | Contenuto | Campi principali |
|---|---|---|
| `tenders` | Una riga per gara | `id`, `publication_number` (univoco), `title`, `description`, `buyer_name`, `buyer_city`, `cpv_codes` (lista), `notice_type`, `estimated_value`, `currency`, `publication_date`, `submission_deadline`, `ted_url`, `documents_url`, `relevance_score`, `is_relevant`, `discard_reason`, `parent_publication_number` (per le rettifiche), `raw_data` (dato originale TED), `created_at`, `updated_at` |
| `documents` | Documenti di una gara | `id`, `tender_id`, `name`, `url`, `status` (`downloaded` / `not_accessible` / `pending`), `local_path`, `downloaded_at` |
| `reports` | Report generato con la Skill | `id`, `tender_id`, `summary`, `status` (`to_review` / `verified`), `generated_at`, `ai_label` |
| `report_fields` | Singolo campo del report | `id`, `report_id`, `label`, `value`, `original_value`, `source_doc`, `source_page`, `is_critical`, `verification_status`, `reviewer`, `reviewed_at` |
| `ingestion_runs` | Storico delle esecuzioni giornaliere | `id`, `started_at`, `finished_at`, `status` (`running` / `success` / `failed`), `fetched_count`, `new_count`, `updated_count`, `relevant_count`, `error_message` |

> ⚠️ Nomi dei campi TED e sintassi delle query **non vanno dedotti**: i punti che dipendono da TED vanno marcati "DA VERIFICARE in T1.1".

**Come usare Claude** (Plan mode, Opus):
> *"Siamo 3 dev. Dobbiamo costruire un backend che ogni giorno scarica da TED le gare italiane IT, le filtra, assegna un punteggio e le espone via API REST. Proponi l'architettura in 3 moduli (ingestion, domain, api) e il modello dati. Per ogni tabella indica campi, tipi e motivazione. Segnala i punti in cui hai dubbi su come TED fornisce i dati."*

**Risultato atteso:** `docs/ARCHITECTURE.md` approvato e decisioni in `docs/DECISIONS.md`.

**Il task è finito quando:**
- [ ] tutti e tre i dev hanno approvato la PR;
- [ ] ogni campo ha tipo e significato chiari;
- [ ] i dubbi aperti sono elencati come domande da chiudere in T1.1.

---

#### T0.5 – Contratto API

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-3 scrive, DEV-1 e DEV-2 approvano | T0.4 | `setup/api-contract` | 1 giorno |

**Obiettivo:** definire *prima del codice* cosa esporrà il backend. È il secondo accordo tra i moduli e permette di progettare il frontend in anticipo.

**Cosa fare:**
1. Scrivere `docs/API_CONTRACT.yaml` in formato OpenAPI 3 con questi endpoint:

| Metodo e percorso | A cosa serve | Parametri principali |
|---|---|---|
| `GET /tenders` | Elenco gare | `min_score`, `cpv`, `deadline_from`, `deadline_to`, `min_value`, `max_value`, `report_status`, `q` (ricerca testo), `sort`, `page`, `page_size` |
| `GET /tenders/{id}` | Dettaglio di una gara | – |
| `GET /tenders/{id}/documents` | Documenti della gara | – |
| `GET /tenders/{id}/report` | Report della gara | – |
| `POST /tenders/{id}/report` | Caricamento del report prodotto dalla Skill | corpo JSON del report |
| `PATCH /reports/{id}/fields/{field_id}` | Conferma o correzione di un campo da parte del revisore | `action` (`confirm` / `correct`), `value`, `reviewer` |
| `GET /deadlines` | Scadenze per il calendario | `from`, `to` |
| `GET /stats` | Indicatori della dashboard | – |
| `GET /runs` | Storico delle esecuzioni | `limit` |
| `POST /runs` | Avvio manuale del monitoraggio | – |
| `GET /health` | Verifica che il servizio sia attivo | – |

2. Per ogni endpoint definire: risposta di successo, errori (`404`, `409`, `422`) e **un esempio di risposta** con dati fittizi realistici.
3. Usare un formato unico per gli errori: `{ "error": "codice", "message": "descrizione" }`.

**Come usare Claude:**
> *"Partendo dal modello dati in docs/ARCHITECTURE.md, scrivi docs/API_CONTRACT.yaml in OpenAPI 3 con gli endpoint elencati. Per ognuno inserisci parametri, schema della risposta, codici di errore e un esempio realistico con dati di gare IT italiane fittizie."*

**Risultato atteso:** contratto API completo con esempi.

**Il task è finito quando:**
- [ ] il file supera la validazione OpenAPI (ad esempio con `openapi-spec-validator`);
- [ ] tutti e tre i dev hanno approvato;
- [ ] da questo momento il file si modifica **solo** con una PR approvata da tutti.

---

#### T0.6 – Compilazione di `docs/TASKS.md` e dei file di coordinamento

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-1 | T0.1, T0.2 | `setup/init` | 0,5 giorni |

**Obiettivo:** creare il file di riferimento da cui ogni dev e ogni Claude sa cosa fare, più i documenti di supporto.

**Cosa fare:**
1. Riportare in `docs/TASKS.md` tutti i task di questa Parte 4 (T0.1–T5.3), raggruppati per fase e responsabile.
2. Per ognuno indicare: codice, titolo, responsabile, stato, dipendenze, branch, durata, obiettivo e criteri "finito quando".
3. In cima a `docs/TASKS.md`: legenda degli stati, regola di aggiornamento ("ognuno aggiorna solo i propri task, nella stessa PR del codice") ed elenco delle dipendenze critiche.
4. Creare `docs/WORKFLOW.md`, `docs/ONBOARDING.md`, `docs/DECISIONS.md`, `docs/GLOSSARY.md`, `docs/handoff/DEV-1.md`, `DEV-2.md`, `DEV-3.md` e `README.md`.

**Legenda degli stati:** `[ ]` da fare · `[~]` in corso · `[x]` fatto · `[!]` bloccato

**Formato di ogni task in `docs/TASKS.md`:**
```markdown
### T2.3 – Punteggio di pertinenza
- Responsabile: DEV-2
- Stato: [ ] da fare
- Dipende da: T2.1, T2.2
- Branch: feat/relevance-score
- Durata stimata: 2 giorni
- Obiettivo: ordinare le gare per interesse con un voto da 1 a 5 calcolato con regole trasparenti.
- Finito quando:
  - [ ] ogni gara salvata ha un punteggio da 1 a 5
  - [ ] 10 gare di esempio danno il punteggio atteso
  - [ ] Giuseppe ha validato l'ordine su un campione di 20 gare reali
```

**Formato di una nota in `docs/handoff/DEV-n.md`:**
```markdown
## 2026-10-14 – T1.3 Parser eForms
- Fatto: mappatura di titolo, ente, CPV, scadenza; test sulle 3 fixture.
- Da fare: gestione del multilingua per le descrizioni.
- Decisioni: estimated_value è null quando TED non lo fornisce.
- Impatto sugli altri dev: DEV-2 deve gestire estimated_value null nei filtri.
```

**Il task è finito quando:**
- [ ] `/my-tasks DEV-1`, `/my-tasks DEV-2` e `/my-tasks DEV-3` restituiscono i task corretti;
- [ ] tutti i link relativi tra i documenti puntano a file esistenti.

---

#### T0.7 – Ambiente locale con Docker

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-3 | T0.1 | `setup/docker` | 0,5 giorni |

**Obiettivo:** dare a tutti lo stesso ambiente con un solo comando.

**Cosa fare:**
1. Scrivere `docker-compose.yml` con due servizi: `db` (PostgreSQL) e `api` (applicazione).
2. Completare `.env.example` con le variabili dei servizi, senza valori reali.
3. Documentare il comando di avvio (`docker compose up`) in `CLAUDE.md` e in `docs/ONBOARDING.md`.

**Il task è finito quando:**
- [ ] i 3 dev avviano l'ambiente con `docker compose up` sul proprio computer;
- [ ] `GET /health` risponde `200`.

---

### FASE 1A – Ingestion *(DEV-1, settimane 2–3)*

> **Scopo della fase:** portare ogni giorno nel database le gare pubblicate su TED, senza duplicati.

#### T1.1 – Studio dell'API di TED

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-1 | T0.3 | `research/ted-api` | 1 giorno |

**Obiettivo:** capire con precisione come interrogare TED **prima** di scrivere il client.

**Perché l'API e non la pagina web:** la pagina di ricerca di TED è pensata per le persone e può cambiare spesso. L'API di ricerca restituisce dati strutturati ed è più stabile.

**Cosa fare:** con il subagent `ted-api-researcher`, rispondere a queste domande in `docs/TED_API_NOTES.md`:
1. Qual è l'endpoint di ricerca e serve una chiave API?
2. Come si filtra per **Paese dell'ente = Italia**?
3. Come si filtra per **codici CPV**, anche per prefisso (72\*, 48\*, 302\*, 324\*, 642\*)?
4. Come si filtra per **data di pubblicazione**?
5. Come si distinguono i **tipi di avviso** (bando, rettifica, aggiudicazione)?
6. Come funziona la **paginazione** e quanti risultati restituisce al massimo ogni pagina?
7. Ci sono **limiti di richieste** (rate limit)?
8. In quali campi si trovano titolo, ente, importo stimato, scadenza offerte e link ai documenti di gara?
9. Come si riconosce che un avviso è la **rettifica** di un altro?

**Come usare Claude:**
> *"Usa il subagent ted-api-researcher. Studia la documentazione ufficiale dell'API di ricerca di TED e rispondi alle 9 domande in docs/TED_API_NOTES.md. Per ogni risposta indica la fonte. Se un'informazione non è chiara, scrivi 'DA VERIFICARE' invece di dedurla."*

**Risultato atteso:** `docs/TED_API_NOTES.md` con le risposte e **2–3 risposte reali di TED** salvate in `backend/tests/fixtures/`.

**Il task è finito quando:**
- [ ] tutte e 9 le domande hanno risposta o sono marcate "DA VERIFICARE";
- [ ] una richiesta reale di prova restituisce gare italiane IT;
- [ ] i dubbi aperti di T0.4 sono chiusi o riportati.

---

#### T1.2 – Client API di TED

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-1 | T1.1 | `feat/ted-client` | 2 giorni |

**Obiettivo:** avere una funzione che, data una data, restituisce tutte le gare italiane IT pubblicate in quel giorno.

**Cosa fare:**
1. Creare `backend/ingestion/ted_client.py` con la funzione `fetch_notices(publication_date) -> list[dict]`.
2. Costruire la query con i filtri: Paese Italia, CPV IT, data di pubblicazione.
3. Gestire la **paginazione**: richiedere tutte le pagine fino all'ultima.
4. Gestire gli **errori**:
   - timeout di 30 secondi per richiesta;
   - fino a 3 tentativi con attesa crescente (1 s, 2 s, 4 s) in caso di errore 5xx o di rete;
   - rispetto del rate limit (pausa tra le richieste se necessario).
5. Rendere configurabili in `.env` l'URL dell'API e la lista dei CPV.

**Come usare Claude:**
> *"Leggi docs/TED_API_NOTES.md. Implementa in backend/ingestion/ted_client.py la funzione fetch_notices(publication_date) con httpx, paginazione completa, timeout 30 s, 3 retry con backoff esponenziale e CPV configurabili. Poi usa il subagent test-writer per scrivere i test usando le risposte salvate in tests/fixtures, senza chiamare TED davvero."*

**Il task è finito quando:**
- [ ] i test passano senza connessione a internet (usano le fixture);
- [ ] un test simula un errore 500 e verifica i 3 tentativi;
- [ ] un'esecuzione reale su un giorno recente restituisce gare.

---

#### T1.3 – Parser: dal formato TED al nostro modello

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-1 | T1.2, T0.4 | `feat/ted-parser` | 2 giorni |

**Obiettivo:** trasformare ogni avviso TED in un oggetto `Tender` conforme al modello dati.

**Cosa fare:**
1. Creare `backend/ingestion/parser.py` con la funzione `parse_notice(raw: dict) -> TenderCreate`.
2. Fare la **mappatura campo per campo** (campo TED → campo `tenders`) e documentarla in tabella in `backend/ingestion/CLAUDE.md`.
3. Gestire i **campi mancanti**: se importo o scadenza mancano, il valore è `null`. Il parser **non deve mai bloccarsi**.
4. Normalizzare i formati:
   - date in formato ISO con fuso orario;
   - importi come numero decimale, con valuta separata;
   - codici CPV sempre di 8 cifre.
5. Gestire il **multilingua**: preferire il testo in italiano, altrimenti in inglese.
6. Salvare sempre il dato originale in `raw_data`, per poterlo rielaborare in futuro.

**Come usare Claude:**
> *"Implementa parse_notice in backend/ingestion/parser.py seguendo il modello di docs/ARCHITECTURE.md e i campi in docs/TED_API_NOTES.md. Se un campo manca, imposta null e registra un warning; non sollevare eccezioni. Scrivi in backend/ingestion/CLAUDE.md la tabella di mappatura dei campi."*

**Il task è finito quando:**
- [ ] tutte le fixture vengono convertite senza errori;
- [ ] un avviso privo di importo e scadenza restituisce `null` per quei campi;
- [ ] la tabella di mappatura è documentata.

---

#### T1.4 – Deduplica e gestione delle rettifiche

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-1 | T1.3, T2.1 | `feat/dedup` | 1,5 giorni |

**Obiettivo:** evitare che la stessa gara compaia due volte e collegare le rettifiche alla gara originale.

**Cosa fare:**
1. **Deduplica:** prima di salvare, verificare se `publication_number` esiste già.
   - Se esiste, aggiornare i campi e `updated_at`.
   - Se non esiste, inserire una nuova riga.
2. **Rettifiche:** se l'avviso è una rettifica, cercare la gara originale e:
   - aggiornare la gara originale con i nuovi valori (ad esempio la nuova scadenza);
   - salvare il collegamento in `parent_publication_number`;
   - se esisteva già un report, riportarlo in stato `to_review`, perché i dati potrebbero essere cambiati.
3. Se la gara originale non è nel database, salvare la rettifica come gara a sé e registrare un warning.

**Il task è finito quando:**
- [ ] importare due volte lo stesso giorno non crea duplicati;
- [ ] una rettifica aggiorna la scadenza della gara originale;
- [ ] un report esistente torna `to_review` dopo una rettifica.

---

#### T1.5 – Job giornaliero

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-1 | T1.4, T2.2, T2.3 | `feat/scheduler` | 1 giorno |

**Obiettivo:** eseguire tutto il flusso automaticamente ogni mattina.

**Cosa fare:**
1. Creare `backend/ingestion/pipeline.py` con la funzione `run_daily_ingestion(date)`, che esegue in ordine:
   1. raccolta (T1.2);
   2. lettura (T1.3);
   3. salvataggio con deduplica (T1.4);
   4. filtri (T2.2, di DEV-2);
   5. punteggio (T2.3, di DEV-2);
   6. estrazione dei link ai documenti per le gare rilevanti (T2.4, di DEV-2).
2. Programmare l'esecuzione con APScheduler **ogni giorno alle 06:00** (fuso Europe/Rome), sulle gare del giorno precedente.
3. Impedire due esecuzioni contemporanee: se una è già `running`, la seconda non parte.
4. Prevedere il **recupero**: se un'esecuzione fallisce, quella successiva riprende anche i giorni mancanti.
5. Rendere la pipeline avviabile anche manualmente (endpoint `POST /runs`, di DEV-3).

**Il task è finito quando:**
- [ ] il job parte all'orario configurato (testabile impostando un orario vicino);
- [ ] una seconda esecuzione contemporanea viene rifiutata;
- [ ] simulando un giorno fallito, il giorno dopo vengono recuperati entrambi.

---

#### T1.6 – Registro delle esecuzioni e log

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-1 | T1.5 | `feat/run-logging` | 0,5 giorni |

**Obiettivo:** sapere sempre se il monitoraggio ha funzionato e cosa ha prodotto.

**Cosa fare:**
1. All'inizio di ogni esecuzione creare una riga in `ingestion_runs` con stato `running`.
2. Alla fine aggiornarla con stato (`success` / `failed`), conteggi (raccolte, nuove, aggiornate, rilevanti) ed eventuale messaggio di errore.
3. Scrivere i log in formato JSON (livello, momento, modulo, messaggio).

**Il task è finito quando:**
- [ ] ogni esecuzione, riuscita o fallita, lascia una riga completa in `ingestion_runs`;
- [ ] un errore simulato produce stato `failed` con messaggio leggibile.

---

### FASE 1B – Dominio e Dati *(DEV-2, settimane 1–3)*

> **Scopo della fase:** decidere quali gare sono interessanti e conservare documenti e report.

#### T2.1 – Schema del database e migrazioni

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-2 | T0.4 | `feat/db-schema` | 1,5 giorni |

**Obiettivo:** creare nel database le tabelle concordate in T0.4.

**Cosa fare:**
1. Definire i modelli SQLAlchemy in `backend/domain/models.py` per le 5 tabelle.
2. Creare la prima migrazione Alembic.
3. Aggiungere gli **indici** sui campi usati nei filtri: `publication_number` (univoco), `submission_deadline`, `relevance_score`, `publication_date`.
4. Creare `backend/domain/repository.py` con le funzioni usate dagli altri moduli (ad esempio `upsert_tender`, `list_tenders`, `get_tender`).
5. Preparare lo script `seed.py` con 20 gare fittizie, utile a DEV-3 e al frontend.

**Come usare Claude:**
> *"Implementa i modelli SQLAlchemy 2 in backend/domain/models.py esattamente come in docs/ARCHITECTURE.md, la migrazione Alembic iniziale, gli indici indicati e il repository con upsert_tender, list_tenders (con filtri e paginazione) e get_tender. Poi crea seed.py con 20 gare IT italiane fittizie e realistiche."*

**Il task è finito quando:**
- [ ] `alembic upgrade head` crea tutte le tabelle su un database vuoto;
- [ ] `alembic downgrade base` le rimuove senza errori;
- [ ] `seed.py` popola il database;
- [ ] i test del repository passano.

---

#### T2.2 – Filtri automatici

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-2 | T2.1 | `feat/filters` | 1,5 giorni |

**Obiettivo:** scartare con regole semplici le gare non utili, prima di assegnare il punteggio.

**Cosa fare:** creare `backend/domain/filters.py` con una funzione per ogni regola. Ogni funzione restituisce *tenuta* oppure *scartata con motivo*.

| Regola | Criterio | Esito se non rispettata |
|---|---|---|
| **Paese** | Ente appaltante in Italia | Scartata |
| **Categoria IT** | Almeno un CPV che inizia con 72, 48, 302, 324 o 642 | Scartata |
| **Tipo di avviso** | Bando o avviso di preinformazione (non aggiudicazione) | Scartata |
| **Scadenza** | Scadenza offerte futura (o assente) | Scartata |
| **Importo minimo** | Importo ≥ soglia configurabile (es. 50.000 €), oppure importo assente | Scartata |

1. Rendere **configurabili** in `backend/domain/config.yaml` la soglia di importo e la lista dei CPV, così si possono cambiare senza toccare il codice.
2. Salvare il **motivo dello scarto** in `discard_reason`, per capire perché una gara non compare.

> ℹ️ I filtri su Paese e CPV sono già nella query a TED (T1.2). Si ripetono qui come **controllo di sicurezza**, perché un avviso può contenere più lotti e più codici.

**Il task è finito quando:**
- [ ] ogni regola ha almeno 2 test (un caso tenuto e uno scartato);
- [ ] cambiando la soglia nel file di configurazione cambia il risultato, senza modifiche al codice.

---

#### T2.3 – Punteggio di pertinenza

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-2 | T2.2 | `feat/relevance-score` | 2 giorni |

**Obiettivo:** ordinare le gare per interesse con un voto da 1 a 5 calcolato **con regole trasparenti**, senza LLM.

**Cosa fare:**
1. Creare `backend/domain/scoring.py` con la funzione `compute_score(tender) -> int`.
2. Applicare questa logica di partenza, da tarare con Giuseppe:

| Criterio | Punti |
|---|---|
| CPV "core" (es. 72200000 sviluppo software, 72500000 servizi informatici) | +2 |
| Altro CPV IT | +1 |
| Parole chiave nel titolo o nella descrizione (es. *cloud, cybersecurity, sviluppo applicativo, data, AI*) | +1 ogni 2 parole trovate, massimo +2 |
| Importo ≥ 1.000.000 € | +1 |
| Scadenza tra 10 e 60 giorni (tempo sufficiente per partecipare) | +1 |
| Scadenza < 5 giorni | −1 |

3. Convertire il totale in un voto da 1 a 5: 0–1 → 1, 2 → 2, 3 → 3, 4 → 4, ≥ 5 → 5.
4. Impostare `is_relevant = true` quando il voto è ≥ 3 (soglia configurabile).
5. Salvare parole chiave, CPV core e pesi in `config.yaml`.
6. Documentare le regole in `backend/domain/CLAUDE.md`.

**Come usare Claude:**
> *"Implementa compute_score in backend/domain/scoring.py con le regole descritte in backend/domain/CLAUDE.md, leggendo pesi e parole chiave da config.yaml. Usa il subagent test-writer in background per scrivere test su almeno 10 gare di esempio con il punteggio atteso."*

**Il task è finito quando:**
- [ ] ogni gara salvata ha un punteggio da 1 a 5;
- [ ] 10 gare di esempio danno il punteggio atteso;
- [ ] Giuseppe ha visto un campione di 20 gare reali con il loro punteggio e ha confermato che l'ordine è sensato.

---

#### T2.4 – Documenti di gara

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-2 | T2.1, T1.3 | `feat/documents` | 2 giorni |

**Obiettivo:** per ogni gara rilevante, sapere dove sono i documenti e scaricarli quando possibile.

**Cosa fare:**
1. Leggere dal campo `documents_url` il link ai documenti indicato nell'avviso TED.
2. Classificare il link:
   - **link diretto a un file** (PDF, ZIP) → scaricarlo;
   - **link a una piattaforma di e-procurement** (es. piattaforme regionali o MEPA) → non scaricare, salvare il link con stato `not_accessible`;
   - **nessun link** → stato `not_accessible`.
3. Salvare i file scaricati in una cartella configurabile (`/data/documents/<publication_number>/`).
4. Limitare i download: massimo 50 MB per file e solo per gare con `is_relevant = true`.
5. Registrare ogni documento nella tabella `documents`.

> ℹ️ Molti enti italiani pubblicano i documenti su piattaforme che richiedono registrazione. In questa prima versione **il login non viene automatizzato**: i documenti si scaricano a mano dal link salvato.

**Il task è finito quando:**
- [ ] per ogni gara rilevante esiste almeno una riga in `documents` (anche solo `not_accessible`);
- [ ] un link diretto a un PDF viene scaricato e salvato;
- [ ] un file oltre i 50 MB viene rifiutato con messaggio chiaro.

---

#### T2.5 – Archiviazione dei report

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-2 | T2.1 | `feat/reports` | 1,5 giorni |

**Obiettivo:** salvare i report prodotti dalla Skill e gestirne lo stato di verifica.

**Cosa fare:**
1. Definire lo **schema JSON del report** in `backend/domain/report_schema.json`. È lo stesso formato che produrrà la Skill nella Fase 3:
   ```json
   {
     "summary": "Sintesi esecutiva di 3-5 righe",
     "fields": [
       {
         "label": "Scadenza offerte",
         "value": "2026-11-20 12:00",
         "source_doc": "Disciplinare.pdf",
         "source_page": 4,
         "is_critical": true
       }
     ]
   }
   ```
2. Validare ogni report contro lo schema prima di salvarlo.
3. Regola di revisione:
   - i campi con `is_critical = true` (importi, fatturati, riferimenti normativi, requisiti legali o contrattuali) nascono **"Da verificare"**;
   - il report passa a `verified` **solo quando tutti i campi critici** sono confermati.
4. Salvare in ogni report l'etichetta `ai_label`: *"Contenuto generato con IA – revisionato da [nome], [data]"* (trasparenza AI Act).

**Il task è finito quando:**
- [ ] un report non conforme allo schema viene rifiutato con errore chiaro;
- [ ] un report diventa `verified` solo dopo la conferma di tutti i campi critici;
- [ ] l'etichetta AI si aggiorna con nome del revisore e data.

---

### FASE 1C – API e Qualità *(DEV-3, settimane 1–3)*

> **Scopo della fase:** esporre i dati al frontend e garantire qualità e sicurezza del codice di tutti.

#### T3.1 – Struttura dell'API con dati di prova

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-3 | T0.5 | `feat/api-skeleton` | 1,5 giorni |

**Obiettivo:** avere subito un'API funzionante che restituisce **dati di prova**, così da non aspettare DEV-1 e DEV-2.

**Cosa fare:**
1. Creare l'applicazione FastAPI in `backend/api/main.py`.
2. Creare un file per gruppo di endpoint (`tenders.py`, `reports.py`, `runs.py`, `stats.py`).
3. Definire gli schemi di risposta (Pydantic) **esattamente** come in `docs/API_CONTRACT.yaml`.
4. Far restituire a ogni endpoint i dati di esempio del contratto.
5. Abilitare CORS per l'indirizzo del futuro frontend.

**Il task è finito quando:**
- [ ] tutti gli endpoint del contratto rispondono con dati di prova;
- [ ] la documentazione generata da FastAPI (`/docs`) coincide con il contratto.

---

#### T3.2 – Elenco delle gare (`GET /tenders`)

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-3 | T3.1, T2.1 | `feat/api-tenders-list` | 1,5 giorni |

**Obiettivo:** restituire l'elenco delle gare dal database reale, con filtri, ordinamento e paginazione.

**Cosa fare:**
1. Sostituire i dati di prova con la chiamata a `list_tenders` (repository di DEV-2).
2. Implementare tutti i filtri del contratto.
3. Ordinamento predefinito: punteggio decrescente, poi scadenza crescente.
4. Paginazione: `page_size` predefinito 20, massimo 100.
5. Validare i parametri: valori non validi restituiscono `422` con messaggio chiaro.

**Il task è finito quando:**
- [ ] ogni filtro ha un test;
- [ ] con i dati di `seed.py` la risposta è conforme al contratto.

---

#### T3.3 – Dettaglio, documenti e report

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-3 | T3.2, T2.4, T2.5 | `feat/api-tender-detail` | 1,5 giorni |

**Obiettivo:** restituire tutte le informazioni di una singola gara.

**Cosa fare:**
1. `GET /tenders/{id}`: dettaglio della gara, `404` se non esiste.
2. `GET /tenders/{id}/documents`: elenco dei documenti con stato e link.
3. `GET /tenders/{id}/report`: report con tutti i campi, fonti e stato di verifica; `404` se il report non esiste.
4. `POST /tenders/{id}/report`: caricamento di un report (usato nella Fase 3), validato con lo schema di T2.5.

**Il task è finito quando:**
- [ ] i 4 endpoint rispondono come da contratto;
- [ ] un report non valido inviato con `POST` restituisce `422`.

---

#### T3.4 – Revisione umana dei campi

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-3 | T3.3 | `feat/api-review` | 1 giorno |

**Obiettivo:** permettere al revisore di confermare o correggere i campi critici del report.

**Cosa fare:**
1. Implementare `PATCH /reports/{id}/fields/{field_id}`, che accetta:
   - `action: "confirm"` → il campo diventa "Verificato";
   - `action: "correct"` con il nuovo `value` → il valore viene sostituito e il campo diventa "Verificato".
2. Salvare in entrambi i casi nome del revisore e data.
3. In caso di correzione, conservare il **valore originale** in `original_value`.
4. Dopo ogni modifica, ricalcolare lo stato del report (regola di T2.5).

> ℹ️ In questa versione il nome del revisore arriva nella richiesta. L'autenticazione vera (ad esempio con l'SSO aziendale) va pianificata prima del rilascio al management.

**Il task è finito quando:**
- [ ] confermando tutti i campi critici, il report diventa `verified`;
- [ ] una correzione conserva il valore originale.

---

#### T3.5 – Scadenze, statistiche ed esecuzioni

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-3 | T3.2, T1.6 | `feat/api-dashboard` | 1,5 giorni |

**Obiettivo:** fornire i dati per dashboard e calendario.

**Cosa fare:**
1. `GET /deadlines?from=&to=`: gare rilevanti con scadenza nell'intervallo, con i campi `days_left` e `urgency` (`high` ≤ 3 giorni, `medium` ≤ 7, `low` oltre).
2. `GET /stats`: 4 indicatori:
   - nuove gare oggi;
   - gare rilevanti (punteggio ≥ 3);
   - scadenze nei prossimi 7 giorni;
   - report da verificare.
3. `GET /runs`: ultime esecuzioni da `ingestion_runs`.
4. `POST /runs`: avvia `run_daily_ingestion` (di DEV-1) in background. Restituisce `202` con l'id dell'esecuzione, oppure `409` se un'esecuzione è già in corso.

**Il task è finito quando:**
- [ ] gli indicatori di `/stats` coincidono con un conteggio manuale sui dati di `seed.py`;
- [ ] con due `POST /runs` consecutivi, il primo restituisce `202` e il secondo `409`.

---

#### T3.6 – Qualità, sicurezza e CI

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-3 | T0.3 | `setup/ci` | 1,5 giorni (poi continuativo) |

**Obiettivo:** controllare automaticamente ogni modifica di tutti e tre i dev.

**Cosa fare:**
1. Creare una pipeline GitHub Actions che a ogni PR esegue: lint (`ruff`), test (`pytest`), validazione del contratto e build dell'immagine Docker.
2. Configurare **Claude in GitHub Actions**, così da poter scrivere `@claude` in una PR o in una issue per chiedere una revisione o una correzione.
3. Lanciare `/security-review` su ogni PR che tocca input esterni (client TED, download dei documenti, endpoint API).
4. Aggiungere un **test di conformità al contratto**, che confronta automaticamente le risposte reali con `docs/API_CONTRACT.yaml`.

> ⚠️ Claude in GitHub Actions richiede una configurazione di autenticazione: va verificato quali opzioni sono disponibili con gli account Pro.

**Il task è finito quando:**
- [ ] una PR con un test fallito non si può unire a `main`;
- [ ] `@claude` risponde in una PR di prova;
- [ ] il test di conformità al contratto è attivo.

---

### FASE 2 – Integrazione *(tutti, settimana 4)*

#### T4.1 – Collegamento dei moduli

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| Tutti (coordina DEV-1) | Fasi 1A, 1B, 1C | `feat/integration` | 2 giorni |

**Cosa fare:**
1. Unire tutti i branch in `main`.
2. Avviare l'ambiente completo con Docker.
3. Eseguire `POST /runs` su un giorno reale e seguire il flusso: TED → database → filtri → punteggio → API.
4. Registrare ogni problema come nuovo task in `docs/TASKS.md`, assegnato al responsabile del modulo.

**Il task è finito quando:**
- [ ] un'esecuzione reale completa porta gare visibili in `GET /tenders`.

---

#### T4.2 – Test end-to-end

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-3 (con DEV-1 e DEV-2) | T4.1 | `test/e2e` | 1,5 giorni |

**Cosa fare:** scrivere test automatici per 4 scenari:
1. **Giorno normale:** gare nuove raccolte, filtrate, con punteggio e visibili in API.
2. **Doppia esecuzione:** nessun duplicato.
3. **Rettifica:** la scadenza della gara originale si aggiorna.
4. **TED non raggiungibile:** esecuzione `failed`, messaggio chiaro, recupero il giorno dopo.

**Il task è finito quando:**
- [ ] i 4 scenari passano in CI.

---

#### T4.3 – Revisione incrociata finale

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| Tutti | T4.2 | `docs/final-review` | 1 giorno |

**Cosa fare:**
1. Ogni dev rivede il modulo di un altro con il subagent `code-reviewer` e `/review`.
2. `/security-review` sull'intero backend.
3. Aggiornare `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` e i `CLAUDE.md` di modulo con quanto imparato.

**Il task è finito quando:**
- [ ] non restano segnalazioni critiche aperte.

---

### FASE 3 – Report di gara con la Skill *(DEV-2 + Giuseppe, settimane 4–5)*

#### T5.1 – Creazione della Skill `analisi-gara`

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-2 + Giuseppe | T2.5 | `feat/skill-analisi-gara` | 2 giorni |

**Obiettivo:** trasformare i prompt di Giuseppe in una procedura riutilizzabile, con sempre lo stesso metodo e lo stesso formato.

**Cosa fare:**
1. Raccogliere i prompt di Giuseppe e l'elenco delle informazioni richieste (certificazioni, scadenze, importi, requisiti, ecc.).
2. Creare `.claude/skills/analisi-gara/SKILL.md` con:
   - **contesto e ruolo:** analista gare che scrive per il management;
   - **informazioni da estrarre:** elenco dei campi, indicando quali sono critici;
   - **formato di uscita:** JSON conforme a `report_schema.json` (T2.5);
   - **un esempio** di report compilato;
   - **regola sulle fonti:** ogni campo indica documento e pagina; se l'informazione non c'è si scrive "Non presente nei documenti", senza dedurre;
   - **chain of verification:** dopo l'estrazione Claude rilegge ogni campo, lo confronta con la fonte e segnala ciò che non ha potuto confermare.
3. Copiare `report_schema.json` nella cartella della Skill come riferimento.

**Il task è finito quando:**
- [ ] Giuseppe ha validato la Skill su almeno 3 gare.

---

#### T5.2 – Esecuzione della Skill sui documenti

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| DEV-2 | T5.1, T3.3 | `feat/skill-run` | 1,5 giorni |

**Cosa fare:**
1. Scegliere le gare rilevanti con documenti scaricati.
2. Eseguire la Skill in Claude Code sui documenti di ogni gara:
   - **in modo interattivo**, per la demo;
   - **in modalità headless** (`claude -p`), con un piccolo script che salva il JSON. Mostra come il processo *potrebbe* essere automatizzato in futuro.
3. Caricare ogni report con `POST /tenders/{id}/report`.

> 💡 **Limiti dell'account Pro:** i documenti di gara sono lunghi. Conviene dare alla Skill **solo disciplinare e capitolato**, non tutti gli allegati, e procedere a piccoli gruppi di gare.

**Il task è finito quando:**
- [ ] almeno 10 gare hanno un report caricato e visibile in API.

---

#### T5.3 – Validazione dei report

| Responsabile | Dipende da | Branch | Durata |
|---|---|---|---|
| Giuseppe (con DEV-2) | T5.2 | `fix/skill-tuning` | 1 giorno |

**Cosa fare:**
1. Giuseppe confronta 5 report con l'analisi che il suo team farebbe a mano.
2. Per ogni campo segna: corretto, errato o mancante.
3. Gli errori ricorrenti diventano correzioni alla Skill (nuova versione tramite PR).

**Il task è finito quando:**
- [ ] i campi critici sono corretti in almeno il 90% dei casi del campione, oppure le cause degli errori sono documentate e corrette nella Skill.

---

## Parte 5 – Calendario

| Settimana | DEV-1 | DEV-2 | DEV-3 |
|---|---|---|---|
| **1** | T0.1, T0.2, T0.3, T0.4, T0.6 | Partecipa a T0.4, poi **T2.1** | Partecipa a T0.4, **T0.5**, **T0.7**, **T3.1** |
| **2** | T1.1, T1.2, T1.3 | T2.2, T2.3 | T3.6, T3.2, T3.3 |
| **3** | T1.4, T1.5, T1.6 | T2.4, T2.5 | T3.4, T3.5 |
| **4** | T4.1, T4.3 | T4.1, **T5.1** | T4.1, T4.2, T4.3 |
| **5** | Supporto e correzioni | T5.2, T5.3 | **Prototipo frontend con Claude Design** |
| **6** | Revisione finale | Correzioni della Skill | Implementazione del frontend con Claude Code |

---

## Parte 6 – Passaggio al frontend

Il frontend parte a **backend completato e integrato** (fine settimana 4). Prima di aprire Claude Design, DEV-3 verifica che siano pronti:

1. **`docs/API_CONTRACT.yaml` definitivo**, con esempi di risposta reali.
2. **Database popolato** con dati realistici (`seed.py` o gare reali con report).
3. **Endpoint funzionanti** per tutte le schermate:

| Schermata | Endpoint |
|---|---|
| Dashboard | `GET /stats`, `GET /runs`, `POST /runs` |
| Elenco gare | `GET /tenders` |
| Dettaglio gara | `GET /tenders/{id}`, `GET /tenders/{id}/documents`, `GET /tenders/{id}/report` |
| Revisione dei campi | `PATCH /reports/{id}/fields/{field_id}` |
| Calendario scadenze | `GET /deadlines` |

Il prototipo si realizza con il prompt per Claude Design già definito. In coda al prompt si aggiungono gli esempi di risposta presi da `docs/API_CONTRACT.yaml`, così il prototipo usa esattamente gli stessi nomi dei campi. Il prototipo validato passa poi a Claude Code per l'implementazione collegata agli endpoint reali.

---

## Appendice – File creati in fase di inizializzazione e file rimandati ai task

| File | Quando viene creato | Da chi |
|---|---|---|
| `CLAUDE.md`, `backend/*/CLAUDE.md` | Inizializzazione (T0.2) | DEV-1 |
| `.claude/settings.json`, `.claude/agents/*`, `.claude/commands/*` | Inizializzazione (T0.3) | DEV-1 |
| `docs/TASKS.md`, `docs/WORKFLOW.md`, `docs/ONBOARDING.md`, `docs/DECISIONS.md`, `docs/GLOSSARY.md`, `docs/handoff/*`, `README.md` | Inizializzazione (T0.6) | DEV-1 |
| `docs/ARCHITECTURE.md` (bozza) | Inizializzazione, approvato in T0.4 | DEV-1 con tutti |
| `docs/API_CONTRACT.yaml` | T0.5 | DEV-3 |
| `docker-compose.yml` | T0.7 | DEV-3 |
| `docs/TED_API_NOTES.md` | T1.1 | DEV-1 |
| `.claude/skills/analisi-gara/` | T5.1 | DEV-2 + Giuseppe |
