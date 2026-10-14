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
- Gli errori usano sempre il formato `{ "error": "codice", "message": "descrizione" }`.
- I dati si leggono solo tramite `backend/domain/repository.py`; nessuna regola di business nell'API.
- L'avvio manuale (`POST /runs`) chiama `run_daily_ingestion` di DEV-1 in background: `202`, oppure `409` se già in corso.
- `page_size` predefinito 20, massimo 100; parametri non validi → `422` con messaggio chiaro.
- `/security-review` su ogni PR che tocca input esterni (client TED, download, endpoint).

## Da completare
- Comando di avvio dell'API e dell'ambiente Docker (T3.1, T0.7).
- Configurazione CORS per il frontend (T3.1).
- Pipeline CI e test di conformità al contratto (T3.6).
