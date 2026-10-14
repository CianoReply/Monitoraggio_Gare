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
- Prima di toccare query o campi TED leggi `docs/TED_API_NOTES.md` (T1.1); finché non esiste, "DA VERIFICARE".
- Le ricerche nella documentazione TED si fanno con il subagent `ted-api-researcher`.
- Il client usa httpx: timeout 30 s, 3 tentativi con attesa 1 s, 2 s, 4 s su errori 5xx o di rete, rispetto del rate limit.
- Il parser non solleva mai eccezioni per un campo mancante: imposta `null` e registra un warning.
- Normalizza: date ISO con fuso, importo decimale con valuta separata, CPV a 8 cifre, testo in italiano o in inglese.
- Salva sempre il dato originale in `raw_data`.
- Il salvataggio passa dalle funzioni di `backend/domain/repository.py`, mai da query dirette.
- I test usano le fixture in `backend/tests/fixtures/`, mai la rete.

## Da completare
- Tabella di mappatura campo TED → campo `tenders` (T1.3).
- Regole di riconoscimento delle rettifiche (T1.4).
- Formato dei log JSON (T1.6).
