# Note tecniche del modulo domain

Dettagli del modulo `backend/domain/` (firme complete, configurazione, documenti, report, fusi orari, limiti noti).
Le regole brevi e le responsabilità stanno in [CLAUDE.md](CLAUDE.md).

## Cosa espone agli altri moduli
- `models.py`: modelli SQLAlchemy delle 5 tabelle e tipo `UtcDateTime`; `schemas.py`: `TenderCreate` (ADR-006) e `TenderEvaluation`; `timeutil.py`: `ROME`, `utcnow()`, `as_utc(now)`
- `repository.py` (solo `flush`): `upsert_tender(session, TenderCreate, TenderEvaluation)`, `get_tender`, `get_tender_by_publication_number`, `list_tenders(...)` (solleva `InvalidQueryError`), `reset_report_to_review`, `count_tenders_created_between`, registro esecuzioni (`start_run`, `finish_run`, `get_run`, `get_running_run`, `has_successful_run`, `last_successful_run_date`, `list_runs`)
- `filters.apply_filters(tender, buyer_country=..., config=..., now=None) -> FilterResult` e una funzione per regola (T2.2)
- `scoring.compute_score(tender, config, now=None) -> int` e `scoring.evaluate_tender(tender, filter_result, config, now=None) -> TenderEvaluation` (T2.3)
- `documents.process_tender_documents(session, tender, client=None, *, config=None, documents_dir=None, resolver=None, clock=...) -> list[Document]` (T2.4); `reports.py` (`create_report`, `get_report_for_tender`, `get_report`, `review_field`, eccezioni 404/409/422) e `report_schema.json` (T2.5)

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
- Test PostgreSQL (`test_postgres.py`) mai eseguiti su un vero database (DA VERIFICARE).

## Database, migrazioni e seed (T2.1)
- `DATABASE_URL` dall'ambiente (vedi `.env.example`); i test usano SQLite, produzione PostgreSQL.
- Configurazione Alembic in `backend/domain/alembic.ini`, migrazioni in `backend/domain/migrations/versions/`.
- Applica: `alembic -c backend/domain/alembic.ini upgrade head` · annulla: `... downgrade base`.
- Nuova migrazione: `alembic -c backend/domain/alembic.ini revision --autogenerate -m "descrizione"`, poi controlla il file (i CHECK degli enum non vanno duplicati).
- Dati fittizi: `python -m backend.domain.seed` (20 gare, 2 report, 2 esecuzioni; idempotente).
- Il repository fa solo `flush`: il `commit` spetta a chi possiede la transazione.
- `upsert_tender(session, TenderCreate, TenderEvaluation)`: la gara si salva solo già valutata (punteggio 1-5 obbligatorio, ADR-010); il job calcola filtri e punteggio prima, nella stessa transazione.
- `list_tenders` segue `GET /tenders` del contratto (sort `relevance|deadline|published`, `include_discarded`, `report_status` derivato incluso negli item, intervalli di scadenza in giorni Europe/Rome). `is_relevant`, `publication_from/to` sono solo per uso interno (`/deadlines`, `/stats`).
- DA VERIFICARE: il filtro `cpv` (CAST della colonna JSON a testo + LIKE) è testato solo su SQLite. I test su PostgreSQL stanno in `backend/tests/domain/test_postgres.py` (marker `postgres`, saltati senza `TEST_POSTGRES_URL`; il nome del database deve finire con `_test` perché i test cancellano le tabelle): migrazione su/giù, CHECK degli enum, fusi, ordinamento dei null, ricerca testuale, filtri `cpv` e `report_status`. DA VERIFICARE: non eseguiti nell'ambiente di sviluppo (nessun PostgreSQL).

## Filtri (T2.2)
- Carica la configurazione una volta: `config = load_filters_config()` (da `config.toml`, sezione `[filters]`), poi `filters.apply_filters(tender, buyer_country=..., config=config, now=None) -> FilterResult(kept, reason)`; `reason` va in `discard_reason`. Una funzione per regola: `filter_country`, `filter_cpv`, `filter_notice_type`, `filter_deadline`, `filter_min_value`.
- `buyer_country` è obbligatorio (lo passa il chiamante: `TenderCreate` non ha il paese): codice ISO a 3 lettere o lista di codici come li dà TED (es. `["ITA"]`). `None` = non noto, la gara è tenuta (la query TED già filtra).
- Tipo di avviso: confronto esatto sui codici eForms `notice-type` (ammessi `cn-standard`, `cn-social`, `cn-desg`); `can-*` e `pin-*` scartati. Una rettifica (`parent_publication_number` valorizzato) passa solo se il tipo è `cn-*` (rettifica di un bando); un `can-*` con padre (es. `can-modif`) è scartato come ogni esito.
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
- Download con httpx in streaming, massimo `max_file_mb` (50): controllo di `Content-Length` e conteggio dei byte ricevuti dopo l'eventuale decompressione; oltre il limite il file è rifiutato ("File troppo grande: ... (massimo 50 MB)") e non resta nessun file parziale. Sono rifiutati: solo status 200 vale come successo; pagine HTML/XHTML al posto del file (es. login); contenuti senza la firma attesa (`%PDF-` per i PDF, `PK` per gli ZIP). Tempo complessivo massimo `total_timeout_seconds` (300).
- Sicurezza (SSRF): i link vengono da avvisi pubblici e non sono fidati. I redirect si seguono a mano (max `max_redirects`, anche con un client iniettato che li seguirebbe) e a ogni salto `check_public_url` accetta solo http/https verso host pubblici: sono rifiutati `localhost`, IP privati, loopback, link-local, riservati e multicast, anche quando un nome DNS li risolve (basta un indirizzo non pubblico). Rifiuto = `not_accessible`. Limite noto: il controllo risolve il nome con `getaddrinfo` e poi httpx lo risolve di nuovo per connettersi, quindi un DNS rebinding (risposte diverse nei due momenti) non è escluso. In produzione serve un blocco di rete in uscita verso gli indirizzi interni (firewall o regole del container/Docker, es. impedire al servizio di raggiungere la rete privata e l'endpoint dei metadati del cloud 169.254.169.254).
- Stati: `downloaded`; `not_accessible` (piattaforma, nessun link, 4xx/204/3xx, URL non valido o non consentito, file troppo grande, contenuto non valido: non si riprova); `pending` (errore temporaneo: timeout, rete, protocollo remoto, 408/429/5xx, DNS, tempo complessivo scaduto, disco pieno o permessi: si riprova alla chiamata successiva). Un `downloaded` il cui file non esiste più si riscarica. Il motivo dell'errore va nel log (`logging`), non in tabella: `documents` non ha una colonna per il messaggio.
- File in `$DOCUMENTS_DIR/<publication_number>/<id>_<nome>` (`DOCUMENTS_DIR`, predefinita `/data/documents`): il prefisso con l'id del documento evita collisioni, i nomi sono ripuliti da percorsi e caratteri speciali e accorciati a 200 caratteri mantenendo l'estensione. `url` e `name` del documento restano quelli del link dell'avviso anche se c'è stato un redirect.
- Limiti noti, senza migrazioni: non c'è un vincolo UNIQUE(tender_id, url), quindi si presume un solo job alla volta; un documento `pending` si riprova a ogni chiamata, senza limite di tentativi.

## Registro delle esecuzioni (T1.5)
- In `repository.py` (solo `flush`): `start_run(session, run_date, now=None)`, `finish_run(session, run, status=success|failed, fetched_count, new_count, updated_count, relevant_count, error_message, now=None)`, `get_running_run`, `has_successful_run(session, run_date)`, `last_successful_run_date`, `list_runs(session, limit=20)` (più recenti prima, per `GET /runs`).

## Report (T2.5)
- `report_schema.json` è il formato del report della Skill e coincide con `ReportCreate` e `FieldReview` di `docs/API_CONTRACT.yaml` (lo verifica un test; la validazione è in codice con pydantic, senza jsonschema). I modelli `ReportCreate` e `FieldReview` di `reports.py` si possono usare anche come corpo delle richieste.
- Funzioni di `reports.py` (solo `flush`): `create_report(session, tender_id, payload, now=None)`, `get_report_for_tender(session, tender_id)`, `get_report(session, report_id)`, `review_field(session, report_id, field_id, review, now=None)` (`confirm` / `correct`), `compute_report_status(report)`.
- Errori (hanno `code` e `message`, da mappare nell'API): `ReportValidationError` 422 (`validation_error`, `.errors` elenca i problemi), `TenderNotFoundError` 404 (`tender_not_found`), `ReportNotFoundError` 404 (`report_not_found`), `FieldNotFoundError` 404 (`field_not_found`), `ReportAlreadyExistsError` 409 (`report_already_exists`, ADR-008).
- Regole: il report nasce `to_review`, campi `to_verify`, `ai_label` "Contenuto generato con IA – da revisionare". `correct` salva il valore della Skill in `original_value` (solo alla prima correzione). Dopo ogni revisione il report è `verified` solo se tutti i campi critici sono `verified` (senza campi critici: alla prima revisione); allora `ai_label` = "Contenuto generato con IA – revisionato da [nome], [AAAA-MM-GG]" con l'ultimo revisore e la data di Europe/Rome. Gli orari si salvano in UTC e `now` deve avere il fuso orario (ValueError). Dopo una rettifica `repository.reset_report_to_review` lo riporta a `to_review` senza toccare campi ed etichetta.
- Lunghezze: il contratto non ha `maxLength`, quindi `create_report` e `review_field` controllano `label` (200), `source_doc` (500) e `reviewer` (200) dopo lo schema e rispondono `ReportValidationError` (422), mai un errore del database. Due richieste concorrenti sullo stesso report: il perdente riceve `ReportAlreadyExistsError` (409) grazie a un savepoint.
- Punti aperti (decisi dal lead, da portare all'utente): (1) un report senza campi critici diventa `verified` alla prima revisione; (2) dopo una rettifica `reset_report_to_review` lascia i campi `verified`, quindi basta una sola nuova revisione di un campo qualsiasi perché il report torni `verified` (riverifica parziale).

## Fusi orari, limiti del database e concorrenza (T4.3)
- Fusi: le colonne data/ora usano `UtcDateTime` (scrive UTC, rilegge sempre con fuso UTC anche da SQLite; un valore senza fuso si considera UTC; nessuna migrazione). `timeutil.as_utc(now)`: `now` senza fuso = `ValueError`. Una sola `ROME`; le date dell'etichetta dei report e dei filtri di scadenza sono in Europe/Rome.
- Limiti che il database rifiuterebbe diventano errori chiari: `estimated_value` < 10^16 (`Numeric(18,2)`), `source_page` <= 2147483647, lunghezze delle colonne, nessun carattere NUL nei testi (`TenderCreate`, report, `q`, `discard_reason`), date fuori intervallo e `page` troppo grande in `list_tenders` (`InvalidQueryError`, sottoclasse di `ValueError`: l'API cattura solo quella).
- Limiti noti: si presume UN SOLO scrittore (un job alla volta, un worker); in caso di concorrenza `upsert_tender` può dare `IntegrityError` (unicità di `publication_number`) e `create_report` risponde 409 grazie al savepoint, ma `review_field` non usa lock (due revisioni simultanee sullo stesso report: vince l'ultima); se `documents_url` di una gara cambia, il documento del vecchio link resta (orfano) e se ne crea uno nuovo; il download accetta qualsiasi porta (solo host pubblici, http/https); il DNS rebinding non è escluso (serve il blocco di rete in uscita in produzione); `documents` non ha UNIQUE(tender_id, url).
- Punto aperto per l'utente: dopo una rettifica la riverifica del report è parziale (`reset_report_to_review` lascia i campi `verified`).

## Osservazione e decisioni (ADR-016)
- `workflow.set_watch`, `set_decision`, `list_published_on`, `list_active_watch`, `list_decided`, `search`; solo `flush`.
- Migrazione 0002: colonne `watch_status`, `watched_at`, `decision_*` in `tenders`, `group` in `report_fields` (critico = `requirements`).
