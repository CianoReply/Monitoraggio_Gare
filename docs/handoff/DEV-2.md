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
