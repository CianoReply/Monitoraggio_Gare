# Note di passaggio – DEV-2

> Questo file lo scrive **solo DEV-2** (di solito con `/handoff`); tutti gli altri lo leggono.
> Le note nuove vanno **in cima**, subito sotto il marcatore `<!-- Note -->` (la nota più recente è sempre la prima). Una nota per sessione o per task.
> Regole complete in [WORKFLOW.md](../WORKFLOW.md).

## Formato di riferimento

```markdown
## AAAA-MM-GG – Tn.n Titolo del task
- Fatto: cosa è stato completato.
- Da fare: cosa manca.
- Decisioni: scelte prese e perché.
- Impatto sugli altri dev: chi deve fare o sapere cosa.
```

---

<!-- Note -->

## 2026-10-15 – T2.5 Archiviazione dei report
- Fatto: `report_schema.json` (stesso schema di `ReportCreate` e `FieldReview` del contratto, test di confronto e test di equivalenza con jsonschema se presente), `reports.py` con `create_report`, `get_report_for_tender`, `get_report`, `review_field`, `compute_report_status`, modelli pydantic di validazione ed eccezioni dedicate (404/409/422).
- Da fare: T5.1-T5.3 (Skill) restano bloccati in attesa dei prompt di Giuseppe.
- Decisioni: validazione con pydantic (nessun jsonschema nel codice); un report senza campi critici diventa `verified` alla prima revisione (regola letterale del contratto: tutti i campi critici `verified`); `ai_label` "verificato" riporta l'ultimo revisore e la data UTC; dopo `reset_report_to_review` l'etichetta resta l'ultima finché non è riverificato.
- Impatto sugli altri dev: DEV-3 (T3.3/T3.4) chiama le funzioni di `reports.py` e mappa `ReportError.code`/`message` agli errori del contratto (404 `tender_not_found` / `report_not_found` / `field_not_found`, 409 `report_already_exists`, 422 `validation_error`); può usare `ReportCreate` e `FieldReview` come corpo delle richieste. DEV-1 (T1.4) usa già `reset_report_to_review`.

## 2026-10-15 – T2.4 Documenti di gara
- Fatto: `documents.py` (`classify_link`, `download_document`, `process_tender_documents`), sezione `[documents]` in `config.toml` con `load_documents_config`, test con `httpx.MockTransport` (nessuna rete).
- Da fare: verificare su link reali di TED quali estensioni dirette compaiono (finora solo piattaforme di gara); un'eventuale colonna per il motivo dell'errore richiede una modifica al modello dati (non fatta, il motivo va nel log).
- Decisioni: download solo per link diretti a `.pdf`/`.zip`; piattaforme e link assenti -> riga `not_accessible` (il login non si automatizza); protezione SSRF con redirect manuali (max 5) e controllo a ogni salto che l'host sia pubblico; `pending` solo per errori temporanei (timeout, rete, 408/429/5xx, DNS, disco pieno, tempo complessivo di 300 s scaduto), che si riprovano alla chiamata successiva; 4xx, URL non valido o non consentito e file oltre 50 MB sono `not_accessible` e non si riprovano; pagine HTML e contenuti senza la firma `%PDF-`/ZIP sono rifiutati; file salvati come `<id>_<nome>`; `DOCUMENTS_DIR` predefinita `/data/documents`.
- Limiti noti: DNS rebinding non escluso (serve un blocco di rete in uscita in produzione); nessun UNIQUE(tender_id, url), si presume un solo job alla volta; `pending` senza limite di tentativi.
- Impatto sugli altri dev: DEV-1 in T1.5 chiama `process_tender_documents(session, tender)` per ogni gara salvata (fa solo flush, il commit è del job); DEV-3 per T3.3 legge `tender.documents` e per Docker deve fornire un volume scrivibile per `DOCUMENTS_DIR` e, in produzione, bloccare dal container l'uscita verso gli indirizzi interni.

## 2026-10-15 – T2.3 Punteggio di pertinenza
- Fatto: `scoring.py` (`compute_score`, `score_breakdown`, `evaluate_tender`), sezione `[scoring]` in `config.toml` con `load_scoring_config`, `scoring_sample.py` per la validazione, seed che calcola i voti con le regole, test su 9 avvisi reali della fixture TED e 7 casi sintetici.
- Da fare: validazione di Giuseppe su 20 gare reali (IN ATTESA UMANA; `python -m backend.domain.scoring_sample --limit 20` dopo che il job ha riempito il database) e taratura di pesi, CPV core e parole chiave in `config.toml`.
- Decisioni: CPV core come prefissi 722 e 725; deviazioni dal piano: "AI" e "data" NON sono keyword ("ai" è una preposizione, "data" è la parola "data"; si usano "intelligenza artificiale", "big data", ecc.); parola intera con plurali come varianti della stessa voce (`portale|portali`, contano una volta); se una keyword è dentro una più lunga conta solo la più lunga; scadenza già passata penalizzata come < 5 giorni; il punteggio vale anche per le gare scartate (ADR-010). Il voto si ricalcola a ogni upsert dell'avviso (nuovo o rettifica) in T1.5/T1.4, non ogni giorno (decisione del lead).
- Impatto sugli altri dev: DEV-1 in T1.5 chiama `evaluate_tender(tender, apply_filters(...), scoring_config)` e passa il risultato a `upsert_tender`; carica le due config una volta con `load_filters_config()` e `load_scoring_config()`. Il seed ora calcola i voti con le regole.

## 2026-10-15 – T2.2 Filtri automatici
- Fatto: `filters.py` (cinque regole + `apply_filters` -> `FilterResult(kept, reason)`), `config.py` e `config.toml` (sezione `[filters]`), test.
- Da fare: T2.3 aggiungerà la sezione `[scoring]` nello stesso `config.toml`; verificare i codici `notice-type` degli avvisi pre-eForms (DA VERIFICARE).
- Decisioni: configurazione in TOML (`tomllib`) e non YAML (ADR-013); la config si carica una volta e si passa alle funzioni; tipo di avviso con confronto esatto sui codici eForms (ammessi `cn-standard`, `cn-social`, `cn-desg`); rettifiche tenute se `parent_publication_number` è valorizzato; `buyer_country` obbligatorio e fornito dal chiamante (`None` = non noto = tenuta).
- Impatto sugli altri dev: DEV-1 in T1.5 chiama `apply_filters(tender, buyer_country=<codici TED, es. ["ITA"]>, config=config)` e salva `reason` in `discard_reason` (via `TenderEvaluation`); il parser (T1.3) valorizza `parent_publication_number` per i change notice e fornisce datetime con fuso.

## 2026-10-15 – T2.1 Schema del database e migrazioni
- Fatto: modelli (5 tabelle), migrazione `0001`, `TenderCreate` e `TenderEvaluation` in `schemas.py`, repository (`upsert_tender`, `get_tender`, `list_tenders`), `seed.py` (20 gare), test su SQLite. Mergiato su develop (e23e9d9).
- Da fare: verificare il filtro `cpv` su PostgreSQL (`TEST_POSTGRES_URL`); `tzdata` per `zoneinfo` su Windows (dipendenza da decidere con l'utente).
- Decisioni: Alembic dentro `backend/domain/` (`alembic -c backend/domain/alembic.ini upgrade head`); `relevance_score` NOT NULL, la gara si salva già valutata (`upsert_tender(session, data, TenderEvaluation)`); `list_tenders` segue `GET /tenders` del contratto; il repository fa solo `flush`.
- Impatto sugli altri dev: DEV-1 calcola filtri e punteggio prima dell'upsert e fornisce datetime con fuso; DEV-3 riceve `TenderRow` con `report_status` e mappa i `ValueError` a 422.
