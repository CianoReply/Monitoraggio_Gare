# Modulo domain – regole e dati

- **Responsabile:** DEV-2
- **Scopo:** passi ④ Filtro e ⑤ Punteggio, schema del database, documenti di gara e report.

## Cosa espone agli altri moduli
- `models.py`: modelli SQLAlchemy delle 5 tabelle; `schemas.py`: `TenderCreate` (T2.1, ADR-006)
- `repository.py`: `upsert_tender`, `list_tenders` (filtri e paginazione), `get_tender` (T2.1)
- `filters.py`: una funzione per regola, esito "tenuta" o "scartata con motivo" (T2.2)
- `scoring.compute_score(tender, config, now=None) -> int` e `scoring.evaluate_tender(tender, filter_result, config, now=None) -> TenderEvaluation` (T2.3)
- `documents.process_tender_documents(session, tender, client=None) -> list[Document]` (T2.4) e `report_schema.json` con le regole di verifica (T2.5)

## Task del modulo
T2.1 schema e migrazioni · T2.2 filtri · T2.3 punteggio · T2.4 documenti · T2.5 report · T5.1–T5.3 Skill `analisi-gara`

## Regole specifiche
- Unico modulo che accede direttamente al database; non importa `ingestion` né `api`.
- I modelli seguono esattamente `docs/ARCHITECTURE.md`; per cambiarli serve una PR approvata da tutti.
- Soglie, CPV, parole chiave e pesi stanno in `backend/domain/config.toml` (TOML, letto con `config.py`; pyyaml non è tra le dipendenze), mai nel codice.
- Ogni gara scartata salva il motivo in `discard_reason`.
- Il punteggio è deterministico: nessuna chiamata a LLM.
- Download solo per gare con `is_relevant = true`, massimo 50 MB per file, nessun login automatico.
- I campi critici di un report nascono "Da verificare"; il report è `verified` solo con tutti confermati.
- Per i test usa il subagent `test-writer`, anche in background o in un worktree.

## Da completare
- Taratura delle regole di punteggio con Giuseppe (T2.3, IN ATTESA UMANA).

## Database, migrazioni e seed (T2.1)
- `DATABASE_URL` dall'ambiente (vedi `.env.example`); i test usano SQLite, produzione PostgreSQL.
- Configurazione Alembic in `backend/domain/alembic.ini`, migrazioni in `backend/domain/migrations/versions/`.
- Applica: `alembic -c backend/domain/alembic.ini upgrade head` · annulla: `... downgrade base`.
- Nuova migrazione: `alembic -c backend/domain/alembic.ini revision --autogenerate -m "descrizione"`, poi controlla il file (i CHECK degli enum non vanno duplicati).
- Dati fittizi: `python -m backend.domain.seed` (20 gare, 2 report, 2 esecuzioni; idempotente).
- Il repository fa solo `flush`: il `commit` spetta a chi possiede la transazione.
- `upsert_tender(session, TenderCreate, TenderEvaluation)`: la gara si salva solo già valutata (punteggio 1-5 obbligatorio, ADR-010); il job calcola filtri e punteggio prima, nella stessa transazione.
- `list_tenders` segue `GET /tenders` del contratto (sort `relevance|deadline|published`, `include_discarded`, `report_status` derivato incluso negli item, intervalli di scadenza in giorni Europe/Rome). `is_relevant`, `publication_from/to` sono solo per uso interno (`/deadlines`, `/stats`).
- DA VERIFICARE: il filtro `cpv` (CAST della colonna JSON a testo + LIKE) è testato solo su SQLite. Su PostgreSQL esiste `test_cpv_prefix_filter_on_postgres`, saltato senza `TEST_POSTGRES_URL` (es. `postgresql+psycopg://user:pwd@localhost/test`; il test ricrea e poi cancella le tabelle: usare un database di prova).

## Filtri (T2.2)
- Carica la configurazione una volta: `config = load_filters_config()` (da `config.toml`, sezione `[filters]`), poi `filters.apply_filters(tender, buyer_country=..., config=config, now=None) -> FilterResult(kept, reason)`; `reason` va in `discard_reason`. Una funzione per regola: `filter_country`, `filter_cpv`, `filter_notice_type`, `filter_deadline`, `filter_min_value`.
- `buyer_country` è obbligatorio (lo passa il chiamante: `TenderCreate` non ha il paese): codice ISO a 3 lettere o lista di codici come li dà TED (es. `["ITA"]`). `None` = non noto, la gara è tenuta (la query TED già filtra).
- Tipo di avviso: confronto esatto sui codici eForms `notice-type` (ammessi `cn-standard`, `cn-social`, `cn-desg`); `can-*` e `pin-*` scartati. Le rettifiche (`parent_publication_number` valorizzato) passano.
- `currency=None` con importo = euro. Importi in altre valute non si confrontano con la soglia.
- `now` deve avere il fuso orario (altrimenti `ValueError`).
- DA VERIFICARE: i codici `notice-type` degli avvisi pre-eForms.

## Punteggio di pertinenza (T2.3)
- Pesi, CPV core, parole chiave e soglia stanno in `config.toml`, sezione `[scoring]` (`load_scoring_config()`); nessun LLM.
- Regole (valori predefiniti, da tarare con Giuseppe): CPV core (prefissi 722, 725) +2, altrimenti altro CPV IT +1; parole chiave +1 ogni 2 voci distinte trovate, max +2; importo >= 1.000.000 EUR (o senza valuta) +1; scadenza tra 10 e 60 giorni +1; scadenza a meno di 5 giorni o già passata -1. Voto = totale limitato a 1..5.
- Parole chiave: parola intera in titolo o descrizione, senza maiuscole. I plurali non si trovano da soli: si scrivono come varianti della stessa voce (`portale|portali`), che conta una volta. Se una parola è dentro una più lunga di un'altra voce (`software` in `sviluppo software`) conta solo la più lunga. "AI" e "data" non sono keyword (preposizione "ai", parola "data"): si usano "intelligenza artificiale", "big data", ecc.
- `score_breakdown(...)` spiega i criteri. `evaluate_tender` calcola il voto SEMPRE (ADR-010): `is_relevant` = tenuta dai filtri e voto >= `relevance_threshold` (predefinita 3); `discard_reason` = motivo dei filtri.
- Quando si ricalcola: a ogni upsert dell'avviso (nuovo o rettifica) in T1.5/T1.4, non ogni giorno. Il voto dipende dalla scadenza rispetto a `now`, quindi può diventare vecchio finché l'avviso non cambia.
- Validazione con Giuseppe: `python -m backend.domain.scoring_sample --limit 20` oppure `--per-score 4` (campione per voto, anche i voti bassi), con `DATABASE_URL`.

## Documenti di gara (T2.4)
- `documents.process_tender_documents(session, tender, client=None, config=None, documents_dir=None) -> list[Document]`: la chiama il job (T1.5) per ogni gara salvata. Gara non rilevante: nessuna riga e nessun download. Rilevante: sempre almeno una riga in `documents`. Idempotente (nessun duplicato per gara e link). Fa solo `flush`.
- Classificazione di `documents_url` (`classify_link`): link diretto a un file (estensioni `.pdf`, `.zip` in `config.toml` `[documents]`) -> download; pagina di una piattaforma di gara -> riga `not_accessible` con il link (il login non si automatizza, i documenti si scaricano a mano); nessun link o non http/https -> riga `not_accessible` senza url. Nelle fixture TED reali il caso normale è la piattaforma.
- Download con httpx in streaming, massimo `max_file_mb` (50): controllo di `Content-Length` e conteggio dei byte ricevuti; oltre il limite il file è rifiutato ("File troppo grande: ... (massimo 50 MB)") e non resta nessun file parziale. Una pagina HTML al posto del file (es. login) è rifiutata.
- Stati: `downloaded`; `not_accessible` (piattaforma, nessun link, errore permanente 4xx, file troppo grande: non si riprova); `pending` (errore temporaneo: rete, timeout, 5xx: si riprova alla chiamata successiva). Il motivo dell'errore va nel log (`logging`), non in tabella: `documents` non ha una colonna per il messaggio.
- File in `$DOCUMENTS_DIR/<publication_number>/<nome>` (`DOCUMENTS_DIR`, predefinita `/data/documents`); i nomi sono ripuliti da percorsi e caratteri speciali.
