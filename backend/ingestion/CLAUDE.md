# Modulo ingestion – raccolta dati da TED

- **Responsabile:** DEV-1
- **Scopo:** passi ① Raccolta, ② Lettura, ③ Pulizia del flusso, più lo scheduler giornaliero (06:00 Europe/Rome).

## Cosa espone agli altri moduli
- `ted_client.fetch_notices(publication_date) -> list[dict]` (T1.2)
- `parser.parse_notice(raw: dict) -> TenderCreate` (T1.3; `TenderCreate` importato da `backend/domain/schemas.py`, ADR-006)
- `pipeline.run_daily_ingestion(date)` (T1.5), chiamata da `POST /runs` di DEV-3

## Task del modulo
T1.1 studio API TED · T1.2 client · T1.3 parser · T1.4 deduplica e rettifiche · T1.5 job giornaliero · T1.6 registro esecuzioni

## Regole specifiche
- Prima di toccare query o campi TED leggi `docs/TED_API_NOTES.md` (T1.1).
- Le ricerche nella documentazione TED si fanno con il subagent `ted-api-researcher`.
- Client (`ted_client.py`): httpx, paginazione `ITERATION`, timeout 30 s; su rete, 5xx e 429 la prima richiesta più 3 tentativi (attese 1, 2, 4 s); almeno 1 s tra due richieste.
- Il parser non solleva mai eccezioni per un campo mancante: imposta `null` e registra un warning.
- Normalizza: date ISO con fuso, importo decimale con valuta separata, CPV a 8 cifre, testo in italiano o in inglese.
- Mappatura campo TED → `tenders`: [MAPPING.md](MAPPING.md) (fuori da questo file per il limite di 30 righe).
- Salva sempre il dato originale in `raw_data`.
- Il salvataggio passa dalle funzioni di `backend/domain/repository.py`, mai da query dirette.
- Rettifiche (`dedup.py`, ADR-014): si risale la catena e si aggiorna il primo avviso già salvato (report → `to_review`); un avviso più vecchio non sovrascrive; errore TED → `ChainLookupError`, nulla salvato.
- I test usano le fixture in `backend/tests/fixtures/`, mai la rete.

## Da completare
- Formato dei log JSON (T1.6).
- Job (`pipeline.py`, `scheduler.py`): `run_pending_days` alle 06:00 Europe/Rome (`INGESTION_SCHEDULE`); lo scheduler si avvia con `start_scheduler()` dall'app (T4.1).
