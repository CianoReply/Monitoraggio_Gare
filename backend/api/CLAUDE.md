# Modulo api – esposizione, revisione e qualità

- **Responsabile:** DEV-3
- **Scopo:** passo ⑥ Esposizione via API REST (FastAPI), revisione umana dei report, test di integrazione e CI.

## Cosa espone agli altri moduli
- Gli endpoint di `docs/API_CONTRACT.yaml` (T0.5), usati dal frontend.
- `GET /health` per verificare che il servizio sia attivo (T0.7).

## Task del modulo
T0.5 contratto · T0.7 Docker · T3.1 scheletro · T3.2 elenco gare · T3.3 dettaglio · T3.4 revisione · T3.5 dashboard · T3.6 CI · T4.2 e2e

## Regole specifiche
- Il contratto viene prima del codice: gli schemi Pydantic seguono esattamente `docs/API_CONTRACT.yaml`.
- Per cambiare il contratto serve una PR approvata da tutti e tre i dev.
- Gli errori usano sempre il formato `{ "error": "codice", "message": "descrizione" }`: `backend/api/errors.py` registra gli handler per `ApiError` (404/409/422 applicativi), `RequestValidationError` (422 `validation_error`) e gli errori HTTP di Starlette. Per un errore solleva `ApiError(status, codice, messaggio)`, mai `HTTPException`.
- Gli schemi Pydantic stanno in `schemas.py`; `tests/test_api_skeleton.py` verifica che `/openapi.json` coincida con il contratto (percorsi, parametri, codici di risposta) e che le risposte rispettino gli schemi del contratto.
- Il parametro `from` di `/deadlines` è `from_` in Python con `alias="from"`.
- I dati si leggono solo tramite `backend/domain/repository.py`; nessuna regola di business nell'API.
- L'avvio manuale (`POST /runs`) chiama `run_daily_ingestion` di DEV-1 in background: `202`, oppure `409` se già in corso.
- `page_size` predefinito 20, massimo 100; parametri non validi → `422` con messaggio chiaro.
- `/security-review` su ogni PR che tocca input esterni (client TED, download, endpoint).

## Da completare
- Ambiente Docker (T0.7).
- Avvio locale dell'API (T3.1): `uvicorn backend.api.main:app --reload`, documentazione su `/docs`. Da riportare nel `CLAUDE.md` radice (file condiviso: proposta al lead).
- CORS (T3.1): origini da `CORS_ORIGINS` (separate da virgola), predefinite `http://localhost:3000` e `http://localhost:5173`; l'indirizzo reale del frontend è DA VERIFICARE.
- Stato: tutti gli endpoint del contratto leggono e scrivono tramite il dominio con la sessione `deps.get_session` (`DATABASE_URL`); gli errori di `backend/domain/reports.py` sono mappati in `errors.py` (404/409/422) e il commit lo fa l'API.
- `POST /runs` (`runs.py`): avvia in un thread il recupero dei giorni mancanti (`pipeline.run_pending_days`); se non ci sono giorni da recuperare rielabora ieri (scelta: è idempotente e così risponde sempre con l'id di una nuova esecuzione). Risponde `202` con l'id della prima nuova esecuzione, `409 run_in_progress` se c'è una riga `running` recente, un thread già attivo o il lock del job, `500 internal_error` se il job non crea la riga entro 15 s o fallisce prima di crearla.
- Limiti di `POST /runs`: l'id della riga non viene dal job ma dedotto dal database (la prima riga con id maggiore di quelli presenti all'avvio), quindi vale con un solo worker e senza altre esecuzioni (es. lo scheduler nello stesso processo) che partano nello stesso istante. Un aggancio nel job (callback `on_run_started`) lo renderebbe esatto: da chiedere a DEV-1 se serve.
- La sessione del job viene dalla factory in cache di `deps.session_factory()` (nessun engine nuovo a ogni richiesta).
- Orologio e job sono sostituibili nei test con `deps.get_now` e `deps.get_pipeline_deps` (vedi `backend/tests/api_db.py`: `make_app` usa un TED finto, mai la rete; i test con thread usano `make_seeded_engine(file_backed=True)`).
- Test con database: `backend/tests/api_db.py` (`make_seeded_engine`, `make_app`) crea un SQLite in memoria con `seed.py` e sostituisce `get_session`.
- Pipeline CI e test di conformità al contratto (T3.6).
- Ciclo di vita (`main.lifespan`, T4.1): configura il log JSON (`configure_logging`) e avvia lo scheduler del job giornaliero (`start_scheduler`, orario `INGESTION_SCHEDULE`) solo con `ENABLE_SCHEDULER=true`; alla chiusura `shutdown(wait=False)`. Predefinito spento (test e sviluppo); il compose lo accende e avvia uvicorn con `--workers 1` perché i lock valgono solo nel processo. I test usano `with TestClient(app)` solo per provare il ciclo di vita.

## Sicurezza e limiti noti
- **Nessuna autenticazione** (decisione dell'utente, da pianificare prima del rilascio al management): l'API va esposta solo su `127.0.0.1` o su una rete fidata. Il compose pubblica le porte solo su `127.0.0.1`.
- `reviewer` nelle revisioni è un testo libero scritto dal client, **non un'identità verificata**: etichetta e `reviewer` non provano chi ha rivisto.
- Difese: `ALLOWED_HOSTS` (Host ammessi; predefiniti `localhost,127.0.0.1,testserver`; gli altri ricevono 400 `invalid_host`), `CORS_ORIGINS` (`*` è vietato: l'app non parte), `CORS_ALLOWED_HEADERS` espliciti, `DOCS_ENABLED=false` spegne `/docs`, `/redoc` e `/openapi.json`.
- Valori estremi danno `422 validation_error`, mai 500: id oltre 2147483647, `page` oltre 1.000.000, anni fuori da 1900-2999, importi oltre 10^16, NUL nei testi e nei corpi, intervallo di `/deadlines` oltre 366 giorni. Sono controlli nel codice (`schemas.py`: `at_most`, `YEAR_RANGE`, `NO_NUL`), non nel contratto, per non rompere la parità `/docs`-contratto.
- Le risposte 500 (`internal_error`) e i rifiuti per host non passano dal CORS: un browser le vede come errore di rete.
- `/deadlines` ragiona per giorno di calendario (Europe/Rome): le scadenze di oggi già passate nell'orario restano incluse, con `days_left` 0.
- I corpi di `POST` report e `PATCH` campo sono i modelli stretti di `backend/domain/reports.py` (nessuna conversione di tipo); i messaggi di validazione, 404 e 405 sono in italiano (`errors.py`).
- Ciclo di vita (`main.make_lifespan`): all'avvio le esecuzioni rimaste `running` si chiudono `failed` ("Esecuzione interrotta da un riavvio", un solo worker); alla chiusura si attende il job manuale al massimo `SHUTDOWN_WAIT_SECONDS`. `POST /runs` risponde 409 subito se un'altra richiesta sta avviando il job.

