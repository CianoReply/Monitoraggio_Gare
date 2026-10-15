# Task – Radar Gare IT

File di riferimento per tutti i dev e per il comando `/my-tasks`.
Fonte: [docs/source/PIANO_BACKEND.md](source/PIANO_BACKEND.md), Parte 4. Dettagli dei passi ("Cosa fare", "Come usare Claude") nel piano.

## Regole

**Legenda degli stati:** `[ ]` da fare · `[~]` in corso · `[x]` fatto · `[!]` bloccato

1. **Ognuno aggiorna solo i propri task, nella stessa PR del codice.**
2. Una dipendenza è **soddisfatta** solo quando il task da cui si dipende è `[x]` (PR unita in `main`).
3. Un task passa a `[x]` solo quando tutti i criteri "Finito quando" sono spuntati (verificali con `/verify`).
4. Un task `[!]` riporta sotto lo stato una riga `- Bloccato da:` con il motivo.
5. I task di Fase 0 sono divisi tra più responsabili: cerca il tuo codice dev in ogni sezione.
6. I problemi trovati in T4.1 diventano nuovi task, assegnati al responsabile del modulo.

## Dipendenze critiche

Se uno di questi task ritarda, ritardano anche gli altri:

| Task | Blocca |
|---|---|
| T0.4 – Modello dati e architettura | tutto lo sviluppo parallelo |
| T0.5 – Contratto API | tutto lo sviluppo parallelo |
| T2.1 – Schema del database | T1.3 e T1.4 di DEV-1, T3.2 di DEV-3 |
| T2.2 – Filtri automatici | T1.5 (job giornaliero) |
| T2.3 – Punteggio di pertinenza | T1.5 (job giornaliero) |

---

## Fase 0 – Fondamenta (settimana 1)

### T0.1 – Creazione del repository e della struttura
- Responsabile: DEV-1
- Stato: [x] fatto (2026-10-15) – protezione di `main` IN ATTESA UMANA
- Dipende da: –
- Branch: setup/init
- Durata stimata: 0,5 giorni
- Obiettivo: dare a tutti la stessa struttura di partenza.
- Finito quando:
  - [x] i 3 dev hanno clonato il repository
  - [x] `pytest` e `ruff check` si eseguono senza errori (anche senza test)
  - [ ] `main` è protetto — IN ATTESA UMANA: "Require a pull request" senza approvazioni obbligatorie (un solo account) e, dopo la prima esecuzione della CI, i controlli obbligatori di T3.6
- Note: struttura, `pyproject.toml`, `.gitignore`, `.env.example` creati in `setup/init`. La protezione di `main` si attiva nelle impostazioni GitHub del repository.

### T0.2 – Scrittura di `CLAUDE.md`
- Responsabile: DEV-1 (rivedono DEV-2 e DEV-3)
- Stato: [x] fatto
- Dipende da: T0.1
- Branch: setup/init
- Durata stimata: 0,5 giorni
- Obiettivo: fare in modo che i tre Claude seguano le stesse regole.
- Finito quando:
  - [x] DEV-2 e DEV-3 hanno approvato la PR
  - [x] in una nuova sessione, alla domanda "quali sono le regole del progetto?", Claude risponde correttamente
- Note: PR #1 unita il 2026-10-14; regole verificate con un subagent a contesto nuovo. `CLAUDE.md` radice e i 3 di modulo scritti senza `/init`; DEV-1 mostra `/init` nella demo confrontandolo con il file versionato.

### T0.3 – Configurazione condivisa di Claude (`.claude/`)
- Responsabile: DEV-1 (hook preparati con DEV-3)
- Stato: [x] fatto (2026-10-15, merge 38991d7)
- Dipende da: T0.2
- Branch: setup/init
- Durata stimata: 1 giorno
- Obiettivo: dare a tutti gli stessi permessi, hook, subagent e comandi.
- Finito quando:
  - [x] ognuno dei tre dev ha provato `/my-tasks` e ottiene i propri task
  - [x] una modifica a `.env` tramite Claude viene bloccata
    (2026-10-15, in locale su Windows: `echo prova > .env.hooktest` da Bash bloccato dall'hook `PreToolUse`, file non creato; Read/Edit bloccati dai permessi)
  - [x] un errore di lint introdotto di proposito viene segnalato dall'hook
- Note: creati permessi, hook `PostToolUse` (ruff, script `.claude/hooks/ruff_check.py`), 3 subagent e 3 comandi; sintassi verificata sulla documentazione ufficiale di Claude Code il 2026-10-13.
  DA VERIFICARE: hook e comandi su Windows (usano `python3` e `date`).
  **Hook da configurare (con DEV-3):** `PreToolUse` che blocca le modifiche a `.env`, `docs/API_CONTRACT.yaml`, `docs/ARCHITECTURE.md` (da decidere come conciliarlo con le modifiche richieste esplicitamente) e `Stop` che esegue i test del modulo.
- Esito (2026-10-15): hook `PreToolUse` `.claude/hooks/protect_files.py` (blocca `.env` anche via Bash, compresi i comandi che lo nominano soltanto; chiede conferma per `docs/API_CONTRACT.yaml` e `docs/ARCHITECTURE.md`), hook `Stop` `.claude/hooks/run_tests.py` (test dei moduli toccati, venv anche nei worktree), fallback a ruff del venv; OK di DEV-2 e DEV-3; ADR-011. Hook verificati su Windows con `python3` = Python 3.14.

### T0.4 – Modello dati e architettura
- Responsabile: DEV-1 guida, tutti partecipano
- Stato: [x] fatto
- Dipende da: T0.1
- Branch: setup/architecture
- Durata stimata: 1 giorno
- Obiettivo: concordare com'è fatta una gara nel nostro sistema; è il primo accordo tra i moduli.
- Finito quando:
  - [x] tutti e tre i dev hanno approvato la PR
  - [x] ogni campo ha tipo e significato chiari
  - [x] i dubbi aperti sono elencati come domande da chiudere in T1.1
- Note: approvazione = merge della PR `setup/architecture` (i tre ruoli sono coperti dalla stessa persona). Decisioni D1–D7 in [ARCHITECTURE.md](ARCHITECTURE.md) sezione 5.2 e ADR-006…010 in [DECISIONS.md](DECISIONS.md); prima sintesi TED in sezione 5.1.

### T0.5 – Contratto API
- Responsabile: DEV-3 scrive, DEV-1 e DEV-2 approvano
- Stato: [x] fatto (2026-10-15, merge ab2f877)
- Dipende da: T0.4
- Branch: setup/api-contract
- Durata stimata: 1 giorno
- Obiettivo: definire prima del codice cosa esporrà il backend; è il secondo accordo tra i moduli e permette di progettare il frontend in anticipo.
- Finito quando:
  - [x] il file supera la validazione OpenAPI (ad esempio con `openapi-spec-validator`)
  - [x] tutti e tre i dev hanno approvato (revisione del lead nel loop; approvato dall'utente al checkpoint di fine Fase 0, 2026-10-15)
  - [x] da questo momento il file si modifica solo con una PR approvata da tutti (hook `PreToolUse` di T0.3 e ADR-011)
- Note: unito in `develop` il 2026-10-15 (merge ab2f877), 2 giri di revisione; approvato al checkpoint umano. Aggiunte al piano in ADR-012; valore iniziale di `ai_label` "Contenuto generato con IA – da revisionare" approvato dall'utente.
- Note: produce `docs/API_CONTRACT.yaml` (OpenAPI 3) con gli 11 endpoint del piano, errori `404`/`409`/`422`, formato errore `{ "error": "codice", "message": "descrizione" }` e un esempio per endpoint.

### T0.6 – Compilazione di `docs/TASKS.md` e dei file di coordinamento
- Responsabile: DEV-1
- Stato: [x] fatto
- Dipende da: T0.1, T0.2
- Branch: setup/init
- Durata stimata: 0,5 giorni
- Obiettivo: creare il file di riferimento da cui ogni dev e ogni Claude sa cosa fare, più i documenti di supporto.
- Finito quando:
  - [x] `/my-tasks DEV-1`, `/my-tasks DEV-2` e `/my-tasks DEV-3` restituiscono i task corretti
  - [x] tutti i link relativi tra i documenti puntano a file esistenti

### T0.7 – Ambiente locale con Docker
- Responsabile: DEV-3
- Stato: [x] fatto (2026-10-15, merge 2b9580b) – avvio con Docker IN ATTESA UMANA
- Dipende da: T0.1
- Branch: setup/docker
- Durata stimata: 0,5 giorni
- Obiettivo: dare a tutti lo stesso ambiente con un solo comando.
- Finito quando:
  - [ ] IN ATTESA UMANA – i 3 dev avviano l'ambiente con `docker compose up` sul proprio computer (Docker non installato sulla macchina del loop)
  - [x] `GET /health` risponde `200` (verificato con uvicorn in locale; nel container DA VERIFICARE)
- Note: produce `docker-compose.yml` (servizi `db` e `api`), completa `.env.example` e documenta l'avvio in `CLAUDE.md` e [ONBOARDING.md](ONBOARDING.md).
- Esito: `Dockerfile`, `docker-compose.yml` (db PostgreSQL 16 + api con migrazioni all'avvio, porte solo su 127.0.0.1), `.dockerignore`, `.env.example` completato, sezione in [ONBOARDING.md](ONBOARDING.md); 14 test statici.

---

## DEV-1 – Fase 1A Ingestion (settimane 2–3)

### T1.1 – Studio dell'API di TED
- Responsabile: DEV-1
- Stato: [x] fatto (2026-10-15, merge 58008a5)
- Dipende da: T0.3
- Branch: research/ted-api
- Durata stimata: 1 giorno
- Obiettivo: capire con precisione come interrogare TED prima di scrivere il client.
- Finito quando:
  - [x] tutte e 9 le domande hanno risposta o sono marcate "DA VERIFICARE"
  - [x] una richiesta reale di prova restituisce gare italiane IT
  - [x] i dubbi aperti di T0.4 sono chiusi o riportati
- Note: produce `docs/TED_API_NOTES.md` e 2–3 risposte reali di TED in `backend/tests/fixtures/`; usa il subagent `ted-api-researcher`.
- Esito: `docs/TED_API_NOTES.md` con risposte verificate da chiamate reali; 3 fixture e `test_ted_fixtures.py`. Scoperte: limite campi × limit ≤ 10.000, `429` sulle raffiche, rettifiche come change notice collegati via `change-notice-version-identifier` → `notice-identifier` (catena), scadenza offerte = `deadline-receipt-tender-*` (non `deadline`). Q7 e pre-eForms DA VERIFICARE.

### T1.2 – Client API di TED
- Responsabile: DEV-1
- Stato: [x] fatto (2026-10-15, merge 8e30217)
- Dipende da: T1.1
- Branch: feat/ted-client
- Durata stimata: 2 giorni
- Obiettivo: avere una funzione che, data una data, restituisce tutte le gare italiane IT pubblicate in quel giorno.
- Finito quando:
  - [x] i test passano senza connessione a internet (usano le fixture)
  - [x] un test simula un errore 500 e verifica i 3 tentativi
  - [x] un'esecuzione reale su un giorno recente restituisce gare
- Esito: revisione con code-reviewer (1 giro: risposte 200 non valide, fine paginazione robusta); esecuzione reale 2026-10-15: 16 avvisi del 2026-10-13, 9 del 2026-10-14. Ritentativi: prima richiesta + 3 (attese 1, 2, 4 s), anche su 429.


### T1.3 – Parser: dal formato TED al nostro modello
- Responsabile: DEV-1
- Stato: [x] fatto (2026-10-15, merge 206ef37)
- Dipende da: T1.2, T0.4, T2.1
- Branch: feat/ted-parser
- Durata stimata: 2 giorni
- Obiettivo: trasformare ogni avviso TED in un oggetto `Tender` conforme al modello dati.
- Note: dipendenza da T2.1 aggiunta in T0.4 (ADR-006: `TenderCreate` vive in `backend/domain/schemas.py`).
- Finito quando:
  - [x] tutte le fixture vengono convertite senza errori
  - [x] un avviso privo di importo e scadenza restituisce `null` per quei campi
  - [x] la tabella di mappatura è documentata
- Esito: 1 giro di revisione (robustezza: importi fuori scala, URL e stringhe lunghe, valute, offset, input inattesi). Tabella in `backend/ingestion/MAPPING.md`, collegata dal CLAUDE.md del modulo (il piano la voleva nel CLAUDE.md, che ha il limite di 30 righe). `parse_notice` solleva `NoticeParseError` solo senza numero o data di pubblicazione; `parse_notices` non solleva mai.


### T1.4 – Deduplica e gestione delle rettifiche
- Responsabile: DEV-1
- Stato: [x] fatto (2026-10-15, merge a3a0298)
- Dipende da: T1.3, T2.1
- Branch: feat/dedup
- Durata stimata: 1,5 giorni
- Obiettivo: evitare che la stessa gara compaia due volte e collegare le rettifiche alla gara originale.
- Finito quando:
  - [x] importare due volte lo stesso giorno non crea duplicati
  - [x] una rettifica aggiorna la scadenza della gara originale
  - [x] un report esistente torna `to_review` dopo una rettifica
- Esito: 2 giri di revisione. Rettifica = aggiornamento della riga dell'originale (ADR-014, Proposta: da approvare dall'utente); catena dei change notice risalita su TED con cache e fermata al primo avviso già salvato; un avviso più vecchio non sovrascrive; errore TED → `ChainLookupError` senza scritture. Limite noto: due righe se l'originale manca nel database.


### T1.5 – Job giornaliero
- Responsabile: DEV-1
- Stato: [x] fatto (2026-10-15, merge 96cd044)
- Dipende da: T1.4, T2.2, T2.3, T2.4
- Branch: feat/scheduler
- Durata stimata: 1 giorno
- Obiettivo: eseguire tutto il flusso automaticamente ogni mattina.
- Finito quando:
  - [x] il job parte all'orario configurato (testabile impostando un orario vicino)
  - [x] una seconda esecuzione contemporanea viene rifiutata
  - [x] simulando un giorno fallito, il giorno dopo vengono recuperati entrambi
- Note: dipendenza da T2.4 aggiunta in T0.4 (decisione D3). Recupero dei giorni falliti basato su `ingestion_runs.run_date` (ADR-009).
- Esito: 1 giro di revisione. `backend/ingestion/pipeline.py` (`run_daily_ingestion`, `run_pending_days`) e `scheduler.py` (APScheduler 3.11, 06:00 Europe/Rome, `INGESTION_SCHEDULE`). Un avviso anomalo è saltato senza far fallire il giorno; riga dell'esecuzione chiusa anche in caso di interruzione. Limite: un solo worker (lock nel processo, nessun vincolo univoco su `running`). Recupero secondo ADR-009: un giorno senza successo prima dell'ultimo riuscito non viene ripreso.


### T1.6 – Registro delle esecuzioni e log
- Responsabile: DEV-1
- Stato: [x] fatto (2026-10-15, merge 882a912)
- Dipende da: T1.5
- Branch: feat/run-logging
- Durata stimata: 0,5 giorni
- Obiettivo: sapere sempre se il monitoraggio ha funzionato e cosa ha prodotto.
- Finito quando:
  - [x] ogni esecuzione, riuscita o fallita, lascia una riga completa in `ingestion_runs`
  - [x] un errore simulato produce stato `failed` con messaggio leggibile
- Esito: Revisione del lead. Log JSON con `backend/ingestion/logging_config.configure_logging` (da chiamare all'avvio in T4.1).


---

## DEV-2 – Fase 1B Dominio e Dati (settimane 1–3)

### T2.1 – Schema del database e migrazioni
- Responsabile: DEV-2
- Stato: [x] fatto (2026-10-15, merge e23e9d9)
- Dipende da: T0.4
- Branch: feat/db-schema
- Durata stimata: 1,5 giorni
- Obiettivo: creare nel database le tabelle concordate in T0.4.
- Finito quando:
  - [x] `alembic upgrade head` crea tutte le tabelle su un database vuoto
  - [x] `alembic downgrade base` le rimuove senza errori
  - [x] `seed.py` popola il database
  - [x] i test del repository passano
- Note: include `backend/domain/schemas.py` con `TenderCreate` (ADR-006), l'inizializzazione di Alembic (`alembic init`) e i comandi delle migrazioni in `CLAUDE.md`.
- Esito: 2 giri di revisione; 69 test + 1 saltato (filtro `cpv` su PostgreSQL: DA VERIFICARE con `TEST_POSTGRES_URL`). Decisione dell'utente: `relevance_score` NOT NULL, `upsert_tender` riceve `TenderEvaluation`. Alembic in `backend/domain/alembic.ini`.

### T2.2 – Filtri automatici
- Responsabile: DEV-2
- Stato: [x] fatto (2026-10-15, merge 10513aa)
- Dipende da: T2.1
- Branch: feat/filters
- Durata stimata: 1,5 giorni
- Obiettivo: scartare con regole semplici le gare non utili, prima di assegnare il punteggio.
- Finito quando:
  - [x] ogni regola ha almeno 2 test (un caso tenuto e uno scartato)
  - [x] cambiando la soglia nel file di configurazione cambia il risultato, senza modifiche al codice
- Esito: 2 giri di revisione; configurazione in `backend/domain/config.toml` (ADR-013); tipi di avviso con codici eForms esatti; `buyer_country` obbligatorio (codici ISO a 3 lettere, passati dal chiamante).

### T2.3 – Punteggio di pertinenza
- Responsabile: DEV-2
- Stato: [x] fatto (2026-10-15, merge fabe2b7) – validazione di Giuseppe IN ATTESA UMANA
- Dipende da: T2.2
- Branch: feat/relevance-score
- Durata stimata: 2 giorni
- Obiettivo: ordinare le gare per interesse con un voto da 1 a 5 calcolato con regole trasparenti, senza LLM.
- Finito quando:
  - [x] ogni gara salvata ha un punteggio da 1 a 5
  - [x] 10 gare di esempio danno il punteggio atteso (9 avvisi reali + 7 sintetici)
  - [ ] IN ATTESA UMANA – Giuseppe ha visto un campione di 20 gare reali con il loro punteggio e ha confermato che l'ordine è sensato
- Esito: 2 giri di revisione. Regole e pesi in `backend/domain/config.toml` `[scoring]`; campione per Giuseppe: `python -m backend.domain.scoring_sample --per-score 4` (serve un database con gare reali, dopo T1.5). Il voto si ricalcola a ogni upsert dell'avviso.


### T2.4 – Documenti di gara
- Responsabile: DEV-2
- Stato: [x] fatto (2026-10-15, merge 4bc32c8)
- Dipende da: T2.1, T1.3
- Branch: feat/documents
- Durata stimata: 2 giorni
- Obiettivo: per ogni gara rilevante, sapere dove sono i documenti e scaricarli quando possibile.
- Finito quando:
  - [x] per ogni gara rilevante esiste almeno una riga in `documents` (anche solo `not_accessible`)
  - [x] un link diretto a un PDF viene scaricato e salvato
  - [x] un file oltre i 50 MB viene rifiutato con messaggio chiaro
- Esito: 2 giri di revisione (protezione SSRF su ogni salto di redirect, classificazione degli errori, tempo massimo complessivo, nomi file senza collisioni). Limite noto: DNS rebinding; in produzione bloccare la rete in uscita verso gli indirizzi interni. Incluso il repository delle esecuzioni per T1.5/T3.5.


### T2.5 – Archiviazione dei report
- Responsabile: DEV-2
- Stato: [x] fatto (2026-10-15, merge 961b428)
- Dipende da: T2.1
- Branch: feat/reports
- Durata stimata: 1,5 giorni
- Obiettivo: salvare i report prodotti dalla Skill e gestirne lo stato di verifica.
- Finito quando:
  - [x] un report non conforme allo schema viene rifiutato con errore chiaro
  - [x] un report diventa `verified` solo dopo la conferma di tutti i campi critici
  - [x] l'etichetta AI si aggiorna con nome del revisore e data
- Esito: 2 giri di revisione. `backend/domain/reports.py` e `report_schema.json` (uguale a `ReportCreate`/`FieldReview` del contratto, test di parità senza jsonschema); lunghezze controllate nel dominio (422); data dell'etichetta in Europe/Rome. Punti aperti per l'utente: report senza campi critici `verified` alla prima revisione; dopo una rettifica basta una conferma per tornare `verified`; proposta `maxLength` nel contratto (T4.3).


---

## DEV-3 – Fase 1C API e Qualità (settimane 1–3)

### T3.1 – Struttura dell'API con dati di prova
- Responsabile: DEV-3
- Stato: [x] fatto (2026-10-15, merge 1cd7ba0)
- Dipende da: T0.5
- Branch: feat/api-skeleton
- Durata stimata: 1,5 giorni
- Obiettivo: avere subito un'API funzionante che restituisce dati di prova, così da non aspettare DEV-1 e DEV-2.
- Finito quando:
  - [x] tutti gli endpoint del contratto rispondono con dati di prova
  - [x] la documentazione generata da FastAPI (`/docs`) coincide con il contratto
- Esito: 2 giri di revisione; risposte validate contro il contratto, `/docs` confrontato con il contratto (unica eccezione nota: if/then di `FieldReview`, imposto da validatore); handler `{error, message}` per 404/405/409/422/500. Origine reale del frontend per CORS: DA VERIFICARE.

### T3.2 – Elenco delle gare (`GET /tenders`)
- Responsabile: DEV-3
- Stato: [x] fatto (2026-10-15, merge a453b32)
- Dipende da: T3.1, T2.1
- Branch: feat/api-tenders-list
- Durata stimata: 1,5 giorni
- Obiettivo: restituire l'elenco delle gare dal database reale, con filtri, ordinamento e paginazione.
- Finito quando:
  - [x] ogni filtro ha un test
  - [x] con i dati di `seed.py` la risposta è conforme al contratto
- Esito: 2 giri di revisione; test del fuso con attese indipendenti, `q` con escape di `%`/`_`, `cpv` per prefisso; `ValueError` del repository → 422.


### T3.3 – Dettaglio, documenti e report
- Responsabile: DEV-3
- Stato: [x] fatto (2026-10-15, merge 9fb5c35)
- Dipende da: T3.2, T2.4, T2.5
- Branch: feat/api-tender-detail
- Durata stimata: 1,5 giorni
- Obiettivo: restituire tutte le informazioni di una singola gara.
- Finito quando:
  - [x] i 4 endpoint rispondono come da contratto
  - [x] un report non valido inviato con `POST` restituisce `422`
- Esito: Revisione del lead. Dettaglio, documenti e report dal dominio (`backend.domain.reports`), errori del dominio mappati a 404/409/422 nel formato del contratto.


### T3.4 – Revisione umana dei campi
- Responsabile: DEV-3
- Stato: [x] fatto (2026-10-15, merge fb2366b)
- Dipende da: T3.3
- Branch: feat/api-review
- Durata stimata: 1 giorno
- Obiettivo: permettere al revisore di confermare o correggere i campi critici del report.
- Finito quando:
  - [x] confermando tutti i campi critici, il report diventa `verified`
  - [x] una correzione conserva il valore originale
- Esito: revisione del lead; PATCH tramite `backend.domain.reports.review_field`, 25 test.


### T3.5 – Scadenze, statistiche ed esecuzioni
- Responsabile: DEV-3
- Stato: [x] fatto (2026-10-15, merge a54bc53)
- Dipende da: T3.2, T1.6
- Branch: feat/api-dashboard
- Durata stimata: 1,5 giorni
- Obiettivo: fornire i dati per dashboard e calendario.
- Finito quando:
  - [x] gli indicatori di `/stats` coincidono con un conteggio manuale sui dati di `seed.py`
  - [x] con due `POST /runs` consecutivi, il primo restituisce `202` e il secondo `409`
- Esito: 2 giri di revisione. `POST /runs` avvia `run_pending_days` in un thread (202, 409 se un'esecuzione è in corso); senza giorni da recuperare rielabora ieri. Un solo worker.


### T3.6 – Qualità, sicurezza e CI
- Responsabile: DEV-3
- Stato: [x] fatto (2026-10-15, merge 31fc6e1)
- Dipende da: T0.3
- Branch: setup/ci
- Durata stimata: 1,5 giorni (poi continuativo)
- Obiettivo: controllare automaticamente ogni modifica di tutti e tre i dev.
- Finito quando:
  - [ ] una PR con un test fallito non si può unire a `main` — IN ATTESA UMANA (Actions e protezione di `main` su GitHub)
  - [ ] `@claude` risponde in una PR di prova — IN ATTESA UMANA / DA VERIFICARE (GitHub App, secret, `CLAUDE_ENABLED`, SHA della action)
  - [x] il test di conformità al contratto è attivo (job `test`: `pytest -m contract`; verificato in locale, prima esecuzione su GitHub DA VERIFICARE)
- Note: Claude in GitHub Actions richiede una configurazione di autenticazione: le opzioni con account Pro sono DA VERIFICARE.
- Esito: 2 giri di revisione. Workflow `.github/workflows/ci.yml` (lint, contratto, test, PostgreSQL) e `claude.yml` (dietro `vars.CLAUDE_ENABLED`). Passi umani in [handoff/DEV-3.md](handoff/DEV-3.md).


---

## Integrazione – Fase 2 (tutti, settimana 4)

### T4.1 – Collegamento dei moduli
- Responsabile: Tutti (coordina DEV-1)
- Stato: [x] fatto (2026-10-15, merge e5dd0f7 (parte api 868a0c1))
- Dipende da: Fasi 1A, 1B, 1C (T1.1–T1.6, T2.1–T2.5, T3.1–T3.6)
- Branch: feat/integration
- Durata stimata: 2 giorni
- Obiettivo: unire i moduli e seguire il flusso completo TED → database → filtri → punteggio → API su un giorno reale.
- Finito quando:
  - [x] un'esecuzione reale completa porta gare visibili in `GET /tenders`
- Esito: Esecuzione reale del 2026-10-15 con `python -m backend.ingestion.pipeline --date 2026-10-14` su un database migrato: 9 avvisi, 9 gare nuove, 5 rilevanti, 6 visibili in `GET /tenders` (gli esiti sono scartati), `/runs` success. Test d'integrazione offline in `backend/tests/test_integration.py`; avvio di log JSON e scheduler (`ENABLE_SCHEDULER`) nel ciclo di vita dell'API; compose con `--workers 1`.


### T4.2 – Test end-to-end
- Responsabile: DEV-3 (con DEV-1 e DEV-2)
- Stato: [~] in corso
- Dipende da: T4.1
- Branch: test/e2e
- Durata stimata: 1,5 giorni
- Obiettivo: verificare automaticamente 4 scenari: giorno normale, doppia esecuzione, rettifica, TED non raggiungibile.
- Finito quando:
  - [ ] i 4 scenari passano in CI

### T4.3 – Revisione incrociata finale
- Responsabile: Tutti
- Stato: [ ] da fare
- Dipende da: T4.2
- Branch: docs/final-review
- Durata stimata: 1 giorno
- Obiettivo: rivedere a turno il modulo di un altro dev e aggiornare la documentazione con quanto imparato.
- Finito quando:
  - [ ] non restano segnalazioni critiche aperte

---

## Report con Skill – Fase 3 (DEV-2 + Giuseppe, settimane 4–5)

### T5.1 – Creazione della Skill `analisi-gara`
- Responsabile: DEV-2 + Giuseppe
- Stato: [!] bloccato
- Bloccato da: in attesa dei prompt di Giuseppe (`docs/source/prompt_giuseppe/` non esiste)
- Dipende da: T2.5
- Branch: feat/skill-analisi-gara
- Durata stimata: 2 giorni
- Obiettivo: trasformare i prompt di Giuseppe in una procedura riutilizzabile, con sempre lo stesso metodo e lo stesso formato.
- Finito quando:
  - [ ] Giuseppe ha validato la Skill su almeno 3 gare
- Note: produce `.claude/skills/analisi-gara/SKILL.md` e la copia di `report_schema.json`.

### T5.2 – Esecuzione della Skill sui documenti
- Responsabile: DEV-2
- Stato: [!] bloccato
- Bloccato da: in attesa dei prompt di Giuseppe (`docs/source/prompt_giuseppe/` non esiste)
- Dipende da: T5.1, T3.3
- Branch: feat/skill-run
- Durata stimata: 1,5 giorni
- Obiettivo: produrre i report delle gare rilevanti con documenti, in modo interattivo e headless (`claude -p`), e caricarli con `POST /tenders/{id}/report`.
- Finito quando:
  - [ ] almeno 10 gare hanno un report caricato e visibile in API

### T5.3 – Validazione dei report
- Responsabile: Giuseppe (con DEV-2)
- Stato: [!] bloccato
- Bloccato da: in attesa dei prompt di Giuseppe (`docs/source/prompt_giuseppe/` non esiste)
- Dipende da: T5.2
- Branch: fix/skill-tuning
- Durata stimata: 1 giorno
- Obiettivo: confrontare 5 report con l'analisi manuale del team di Giuseppe e correggere la Skill sugli errori ricorrenti.
- Finito quando:
  - [ ] i campi critici sono corretti in almeno il 90% dei casi del campione, oppure le cause degli errori sono documentate e corrette nella Skill
