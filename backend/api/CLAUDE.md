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
- Stato: `GET /tenders`, dettaglio, documenti e report (GET/POST) leggono dal dominio tramite la sessione `deps.get_session` (`DATABASE_URL`); gli errori di `backend/domain/reports.py` sono mappati in `errors.py` (404/409/422), il commit lo fa l'API. `PATCH` dei campi, `/deadlines`, `/stats` e `/runs` usano ancora i dati di prova di `sample_data.py` (T3.4, T3.5).
- Test con database: `backend/tests/api_db.py` (`make_seeded_engine`, `make_app`) crea un SQLite in memoria con `seed.py` e sostituisce `get_session`.
- Pipeline CI e test di conformità al contratto (T3.6).
