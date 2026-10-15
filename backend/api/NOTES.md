# Modulo api – note di dettaglio

Dettagli che non entrano nel limite di 30 righe di [CLAUDE.md](CLAUDE.md). Contratto: [../../docs/API_CONTRACT.yaml](../../docs/API_CONTRACT.yaml).

## Struttura e convenzioni
- `main.py` (app, middleware, ciclo di vita), `deps.py` (sessione, orologio, dipendenze del job), `errors.py` (handler), `schemas.py` (risposte e controlli), `convert.py`, un router per gruppo: `tenders.py`, `reports.py`, `stats.py` (`/deadlines`, `/stats`), `runs.py`.
- Gli schemi di risposta seguono esattamente il contratto. `tests/test_api_skeleton.py` confronta `/openapi.json` con il contratto (percorsi, parametri, corpi, risposte 2xx); l'unica differenza nota è l'`if/then` di `FieldReview` (imposto dal modello del dominio). Le risposte sono validate contro gli schemi del contratto (marker `contract`).
- I corpi di `POST` report e `PATCH` campo sono i modelli stretti di `backend/domain/reports.py`, senza conversioni; validazione e regole di business restano al dominio, l'API fa solo il commit.
- Il parametro `from` di `/deadlines` è `from_` in Python con `alias="from"`.

## Errori
- Formato unico `{ "error": "codice", "message": "descrizione" }`. Per un errore applicativo solleva `ApiError(status, codice, messaggio)`, mai `HTTPException`.
- `errors.py` gestisce `ApiError`, `RequestValidationError` (422 `validation_error`), gli errori di `backend/domain/reports.py` (404/409/422), gli errori HTTP di Starlette (404, 405) e ogni altra eccezione (500 `internal_error`, senza dettagli). Il repository solleva `InvalidQueryError` (422); un altro `ValueError` è un bug (500).
- Messaggi di validazione, 404 e 405 in italiano, con il prefisso del parametro (`page_size: ...`).

## Variabili d'ambiente
`DATABASE_URL`, `CORS_ORIGINS` (predefinite `http://localhost:3000,http://localhost:5173`; l'indirizzo reale del frontend è DA VERIFICARE; `*` vietato), `ALLOWED_HOSTS` (predefiniti `localhost,127.0.0.1,testserver`), `DOCS_ENABLED` (`false` spegne `/docs`, `/redoc`, `/openapi.json`), `ENABLE_SCHEDULER`, `INGESTION_SCHEDULE`. Elenco commentato in `.env.example`.

## POST /runs (`runs.py`)
- Avvia in un thread il recupero dei giorni mancanti (`pipeline.run_pending_days`); senza giorni da recuperare rielabora ieri (idempotente, così risponde sempre con l'id di una nuova esecuzione).
- `202` con l'id della prima nuova esecuzione; `409 run_in_progress` se c'è una riga `running` recente, un thread già attivo, il lock del job o un'altra richiesta che sta avviando (nessuna attesa); `500 internal_error` se il job non crea la riga entro 15 s o fallisce prima di crearla.
- Limite: l'id è dedotto dal database (prima riga con id maggiore di quelli presenti all'avvio), quindi vale con un solo worker e senza altre esecuzioni (es. lo scheduler) che partano nello stesso istante. Una callback `on_run_started` nel job lo renderebbe esatto: da chiedere a DEV-1 se serve.
- La sessione del job viene dalla factory in cache di `deps.session_factory()`.

## Ciclo di vita (`main.make_lifespan`)
Configura il log JSON; all'avvio chiude `failed` le esecuzioni rimaste `running` ("Esecuzione interrotta da un riavvio"); avvia lo scheduler solo con `ENABLE_SCHEDULER=true` e lo ferma con `shutdown(wait=False)`; alla chiusura attende il job manuale al massimo `SHUTDOWN_WAIT_SECONDS`. Un solo worker (`--workers 1` nel compose): i lock valgono solo nel processo.

## Sicurezza e limiti noti
- **Nessuna autenticazione** (decisione dell'utente, da pianificare prima del rilascio al management): esporre solo su `127.0.0.1` o su una rete fidata; il compose pubblica le porte solo su `127.0.0.1`.
- `reviewer` è un testo libero scritto dal client, **non un'identità verificata**.
- Difese: host ammessi (400 `invalid_host`), CORS con origini e intestazioni espliciti, documentazione disattivabile.
- Valori estremi danno `422`, mai 500: id oltre 2147483647, `page` oltre 1.000.000, anni fuori da 1900-2999, importi oltre 10^16, NUL nei testi e nei corpi, intervallo di `/deadlines` oltre 366 giorni. Sono controlli nel codice (`schemas.py`: `at_most`, `YEAR_RANGE`, `NO_NUL`), non nel contratto, per non rompere la parità `/docs`-contratto.
- Le risposte 500 e i rifiuti per host non passano dal CORS: un browser le vede come errore di rete.
- `/deadlines` ragiona per giorno di calendario (Europe/Rome): le scadenze di oggi già passate nell'orario restano incluse, con `days_left` 0.

## Test
- `backend/tests/api_db.py`: `make_seeded_engine` (SQLite con `seed.py`; `file_backed=True` per i test con thread) e `make_app` (sostituisce `get_session`, `get_now`, `get_pipeline_deps`: TED finto, mai la rete).
- Marker `contract` (conformità al contratto) ed `e2e` (4 scenari TED finto → job → database → API), registrati in `backend/tests/conftest.py`; la CI li esegue esplicitamente.
- Con `with TestClient(app)` si prova il ciclo di vita; i test normali non lo avviano.
