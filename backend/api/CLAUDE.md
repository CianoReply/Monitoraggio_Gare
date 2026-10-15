# Modulo api – esposizione, revisione e qualità

- **Responsabile:** DEV-3
- **Scopo:** passo ⑥ Esposizione via API REST (FastAPI), revisione umana dei report, test di integrazione e CI.

## Cosa espone agli altri moduli
- Gli endpoint di `docs/API_CONTRACT.yaml` (T0.5), usati dal frontend; `GET /health` per verificare il servizio.
- Avvio: `uvicorn backend.api.main:app --reload`, documentazione su `/docs` (nel compose: `docker compose up`).

## Task del modulo
T0.5 contratto · T0.7 Docker · T3.1 scheletro · T3.2 elenco gare · T3.3 dettaglio · T3.4 revisione · T3.5 dashboard · T3.6 CI · T4.2 e2e

## Regole specifiche
- Il contratto viene prima del codice: gli schemi seguono esattamente `docs/API_CONTRACT.yaml`; per cambiarlo serve una PR approvata da tutti e tre i dev.
- Errori sempre nel formato `{ "error": "codice", "message": "descrizione" }`: solleva `ApiError`, mai `HTTPException`.
- I dati passano solo da `backend/domain` (repository, `reports`); nessuna regola di business nell'API, che fa solo il commit.
- `POST /runs` avvia il job in un thread: `202`, oppure `409` se già in corso; un solo worker.
- `page_size` predefinito 20, massimo 100; parametri non validi o estremi → `422` con messaggio in italiano.
- L'API non ha autenticazione: solo `127.0.0.1` o rete fidata; `reviewer` non è un'identità verificata.
- `/security-review` su ogni PR che tocca input esterni (client TED, download, endpoint).

## Da completare
- Passi umani: provare CI e `@claude` su GitHub (T3.6) e `docker compose up` (T0.7); autenticazione da pianificare.
- Dettagli (errori, variabili, `POST /runs`, ciclo di vita, sicurezza, test): [NOTES.md](NOTES.md).
