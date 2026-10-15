# Registro delle decisioni (ADR)

> Ogni decisione architetturale si registra qui con una PR approvata da tutti e tre i dev.
> Formato: contesto, decisione, motivazione, conseguenze. Numerazione progressiva, mai riusata.
> Le decisioni ADR-001…005 provengono da [docs/source/PIANO_BACKEND.md](source/PIANO_BACKEND.md) e sono state confermate in T0.4; ADR-006…010 sono le decisioni D1–D7 di T0.4 ([ARCHITECTURE.md](ARCHITECTURE.md), sezione 5.2).

| ADR | Titolo | Stato |
|---|---|---|
| ADR-001 | API di TED invece dello scraping | Accettata |
| ADR-002 | Nessun agente LLM nel backend | Accettata |
| ADR-003 | Il repository è l'unica memoria condivisa | Accettata |
| ADR-004 | Contratto API scritto prima del codice | Accettata |
| ADR-005 | Punteggio a regole configurabili | Accettata |
| ADR-006 | `TenderCreate` vive nel modulo domain | Accettata |
| ADR-007 | `cpv_codes` come colonna JSON portabile | Accettata |
| ADR-008 | Al massimo un report per gara | Accettata |
| ADR-009 | Recupero dei giorni falliti con `run_date` | Accettata |
| ADR-010 | Punteggio per ogni gara salvata | Accettata |
| ADR-011 | Integrazione su `develop` con revisione del lead e una sola persona | Accettata |
| ADR-012 | Gare scartate e stato del report nell'API | Accettata |
| ADR-013 | Configurazione in TOML invece di YAML | Accettata |
| ADR-014 | Una rettifica aggiorna la riga della gara originale | Proposta |
| ADR-015 | API senza autenticazione, solo per rete locale | Proposta |

---

## ADR-001 – API di TED invece dello scraping
- **Contesto:** le gare si trovano sia nella pagina di ricerca di TED sia nella sua API di ricerca.
- **Decisione:** il backend usa l'API di ricerca di TED.
- **Motivazione:** la pagina web è pensata per le persone e può cambiare spesso; l'API restituisce dati strutturati ed è più stabile.
- **Conseguenze:** prima del client serve uno studio dell'API (T1.1, `docs/TED_API_NOTES.md`); endpoint, filtri, paginazione e limiti sono DA VERIFICARE in T1.1.

## ADR-002 – Nessun agente LLM nel backend
- **Contesto:** il progetto usa Claude in modo intensivo, ma il backend gira ogni giorno senza supervisione.
- **Decisione:** raccolta, filtri e punteggio sono codice tradizionale; Claude si usa per costruire il software e, manualmente, per analizzare i documenti con la Skill `analisi-gara`.
- **Motivazione:** risultati deterministici, verificabili con test e spiegabili al management.
- **Conseguenze:** il punteggio usa regole esplicite (ADR-005); i report generati con IA passano da una revisione umana con etichetta di trasparenza (T2.5, T3.4).

## ADR-003 – Il repository è l'unica memoria condivisa
- **Contesto:** i tre dev usano account Claude Pro separati, senza workspace condiviso; nessun Claude vede le sessioni degli altri.
- **Decisione:** ogni informazione utile a un dev o al suo Claude sta in un file versionato: `CLAUDE.md`, `docs/TASKS.md`, `docs/handoff/DEV-n.md` e gli altri documenti di `docs/`.
- **Motivazione:** chi clona il repository può ripartire senza chiedere nulla a voce.
- **Conseguenze:** un file di handoff per dev per evitare conflitti; stato dei task aggiornato nella stessa PR del codice; `CLAUDE.md` brevi per non consumare i limiti dell'account Pro.

## ADR-004 – Contratto API scritto prima del codice
- **Contesto:** API (DEV-3), dominio (DEV-2) e frontend devono procedere in parallelo.
- **Decisione:** `docs/API_CONTRACT.yaml` (OpenAPI 3) si scrive e si approva in T0.5, prima di ogni endpoint.
- **Motivazione:** DEV-3 parte subito con dati di prova (T3.1) e il frontend si progetta in anticipo con gli stessi nomi dei campi.
- **Conseguenze:** il contratto si modifica solo con PR approvata da tutti; in T3.6 un test di conformità confronta le risposte reali con il contratto.

## ADR-005 – Punteggio a regole configurabili
- **Contesto:** il management deve capire perché una gara ha un certo voto, e le regole vanno tarate con Giuseppe.
- **Decisione:** `compute_score` somma punti per CPV, parole chiave, importo e scadenza, e li converte in un voto da 1 a 5; pesi, parole chiave, CPV core e soglie stanno in `backend/domain/config.yaml`.
- **Motivazione:** regole trasparenti e modificabili senza toccare il codice.
- **Conseguenze:** le regole sono documentate in `backend/domain/CLAUDE.md`; ogni modifica dei pesi si verifica con i test delle 10 gare di esempio (T2.3).

## ADR-006 – `TenderCreate` vive nel modulo domain
- **Contesto:** il parser di DEV-1 (T1.3) restituisce un `TenderCreate`, che il repository di DEV-2 salva (T1.4, T2.1). Il piano non dice in quale modulo stia lo schema.
- **Decisione:** `TenderCreate` è uno schema Pydantic in `backend/domain/schemas.py`, creato da DEV-2 in T2.1, con gli stessi campi di `tenders` esclusi quelli calcolati (`id`, `relevance_score`, `is_relevant`, `discard_reason`, `created_at`, `updated_at`).
- **Motivazione:** `domain` è il proprietario del modello dati e non importa gli altri moduli; `ingestion` dipende da `domain`, non il contrario.
- **Conseguenze:** T1.3 dipende anche da T2.1 (nel calendario T2.1 è in settimana 1, T1.3 in settimana 2). Pydantic è già incluso in FastAPI: nessuna nuova dipendenza.

## ADR-007 – `cpv_codes` come colonna JSON portabile
- **Contesto:** una gara ha più CPV (procedura e lotti). PostgreSQL ha il tipo array, SQLite (usato nei test) no.
- **Decisione:** `cpv_codes` è una colonna JSON con una lista di string a 8 cifre, senza duplicati.
- **Motivazione:** lo stesso modello funziona in produzione e nei test; resta una sola tabella per la gara, come nel piano.
- **Conseguenze:** il filtro `cpv` per prefisso di `GET /tenders` si implementa in `repository.list_tenders` (T2.1) e va testato su SQLite e PostgreSQL. Se diventa lento, si valuterà una tabella di associazione con un nuovo ADR.

## ADR-008 – Al massimo un report per gara
- **Contesto:** l'API espone `GET /tenders/{id}/report` al singolare; una rettifica può cambiare i dati di un report già prodotto.
- **Decisione:** `reports.tender_id` è univoco. Un secondo `POST /tenders/{id}/report` risponde `409`. Dopo una rettifica il report esistente torna `to_review` (T1.4).
- **Motivazione:** un solo report per gara è sufficiente per la prima versione e semplifica API, revisione e frontend.
- **Conseguenze:** la sostituzione di un report non è prevista in questa versione; se servirà, si aggiungerà con un nuovo ADR e una modifica del contratto API.

## ADR-009 – Recupero dei giorni falliti con `run_date`
- **Contesto:** T1.5 chiede che, dopo un'esecuzione fallita, la successiva recuperi anche i giorni mancanti; `ingestion_runs` non registrava quale giorno era stato elaborato.
- **Decisione:** nuovo campo `ingestion_runs.run_date` (giorno di pubblicazione TED elaborato). Il job elabora, in ordine, ogni giorno fino a ieri che non ha un'esecuzione `success`, partendo dall'ultimo `run_date` riuscito.
- **Motivazione:** il recupero si basa su dati salvati, non su supposizioni sull'orario dell'ultima esecuzione.
- **Conseguenze:** un'esecuzione per giorno elaborato; il primo avvio in assoluto elabora solo ieri. Indice su `run_date`.

## ADR-010 – Punteggio per ogni gara salvata
- **Contesto:** T2.3 chiede che ogni gara salvata abbia un punteggio da 1 a 5; i filtri (T2.2) possono scartare una gara.
- **Decisione:** il punteggio si calcola per tutte le gare salvate, anche quelle scartate. `is_relevant` è `true` solo se la gara non è scartata e il voto è ≥ soglia.
- **Motivazione:** il criterio di T2.3 resta verificabile su tutte le righe e si può spiegare perché una gara scartata avrebbe avuto un certo voto.
- **Conseguenze:** le gare scartate restano in `tenders` con `discard_reason`; se e come esporle nell'API si decide in T0.5.

## ADR-011 – Integrazione su `develop` con revisione del lead e una sola persona
- **Contesto:** i ruoli DEV-1, DEV-2 e DEV-3 sono coperti da una sola persona con un solo account GitHub, che non può approvare le proprie PR; dal 2026-10-15 lo sviluppo del backend procede con un agent team (lead DEV-1 e due subagent) senza accesso al remote.
- **Decisione:** i task si integrano nel branch locale `develop` con `git merge --no-ff`, uno alla volta, dopo l'approvazione del lead (revisione con il subagent `code-reviewer`). Una dipendenza è soddisfatta quando il task è unito in `develop`. Lo stato in `docs/TASKS.md` lo aggiorna solo il lead. Le modifiche ai file condivisi (`docs/ARCHITECTURE.md`, `docs/API_CONTRACT.yaml`, `CLAUDE.md` radice, `.claude/`) richiedono l'OK dei tre agenti e, tramite l'hook `PreToolUse`, la conferma dell'utente per i due documenti di accordo. `develop → main` passa da una PR che rivede e unisce l'utente: per `main` l'approvazione coincide con il merge della PR.
- **Motivazione:** la regola "approvazione su GitHub di entrambi gli altri due dev" ([WORKFLOW.md](WORKFLOW.md)) non è applicabile con una sola persona; la revisione resta obbligatoria, ma la fa il lead e la conferma l'utente sulla PR finale.
- **Conseguenze:** prevale su [WORKFLOW.md](WORKFLOW.md) (merge in `main` solo tramite PR approvata) e su [TASKS.md](TASKS.md) regole 1 e 2 per la durata del loop; il diario è in [team/LOOP_LOG.md](team/LOOP_LOG.md). Commit nel formato `<tipo>(<modulo>): <descrizione> [<task>]`. Approvata dall'utente al checkpoint di fine Fase 0 (2026-10-15).

## ADR-012 – Gare scartate e stato del report nell'API
- **Contesto:** ADR-010 rimandava a T0.5 la scelta su come esporre le gare scartate; il piano prevede il filtro `report_status` su `GET /tenders`, ma il modello dati non ha uno stato del report nella gara.
- **Decisione:** `GET /tenders` esclude le gare scartate salvo il parametro aggiuntivo `include_discarded=true` (predefinito `false`); `GET /tenders/{id}` restituisce sempre la gara. L'oggetto `Tender` dell'API espone il campo derivato `report_status` (`none` / `to_review` / `verified`), calcolato da `reports.status` (`none` se la gara non ha report), senza nuova colonna.
- **Motivazione:** l'elenco mostra di default solo ciò che serve; le gare scartate restano consultabili e spiegabili (ADR-010). Il frontend filtra e mostra lo stato del report senza una chiamata per gara.
- **Conseguenze:** `repository.list_tenders` (DEV-2) implementa `include_discarded` e restituisce `report_status`; contratto in [API_CONTRACT.yaml](API_CONTRACT.yaml) (T0.5). Approvata dall'utente al checkpoint di fine Fase 0 (2026-10-15).

## ADR-013 – Configurazione in TOML invece di YAML
- **Contesto:** il piano prevede `config.yaml` per soglie, CPV e pesi (T2.2, T2.3), ma `pyyaml` non è tra le dipendenze autorizzate dall'utente (2026-10-15).
- **Decisione:** la configurazione del dominio è in `backend/domain/config.toml`, letta con `tomllib` della libreria standard; T2.3 vi aggiunge la sezione `[scoring]`.
- **Motivazione:** nessuna nuova dipendenza; TOML è leggibile quanto YAML per una configurazione piatta.
- **Conseguenze:** dove il piano dice `config.yaml` si intende `backend/domain/config.toml`. Se un giorno servisse YAML, si cambierà con un nuovo ADR e l'autorizzazione della dipendenza.

## ADR-014 – Una rettifica aggiorna la riga della gara originale
- **Contesto:** su TED una rettifica è un change notice con un proprio `publication_number`, collegato all'avviso precedente da `change-notice-version-identifier`; le modifiche possono formare una catena (T1.1). Il piano (T1.4) chiede di aggiornare la gara originale e di salvare il collegamento in `parent_publication_number`.
- **Decisione:** la rettifica aggiorna la riga del primo avviso della catena già salvato (di solito l'originale): restano `publication_number`, data di pubblicazione e `parent_publication_number` della riga, gli altri campi e `raw_data` prendono i valori della rettifica, il report torna `to_review`. Non si crea una riga per la rettifica. `parent_publication_number` si usa solo per una rettifica salvata a sé perché l'originale non è nel database. Un avviso più vecchio di quello già applicato (data, poi numero) non sovrascrive la riga.
- **Motivazione:** una gara compare una sola volta in `GET /tenders`, sempre con i dati più recenti; l'ordine di arrivo da TED non è garantito.
- **Conseguenze:** sulla riga aggiornata il segnale della rettifica è `raw_data` (`change-notice-version-identifier`); `ted_url` punta all'ultima rettifica. Limite noto: senza l'originale nel database possono restare due righe per la stessa gara (originale arrivato dopo una rettifica salvata a sé, o due rettifiche salvate a sé in ordine inverso); una soluzione richiederebbe una ricerca per `parent_publication_number` nel repository. Stato "Proposta" fino all'approvazione dell'utente.

## ADR-015 – API senza autenticazione, solo per rete locale
- **Contesto:** il contratto API non prevede autenticazione. La revisione di sicurezza di T4.3 segnala che chiunque raggiunga la porta può avviare il job (`POST /runs`), creare report e confermare campi indicando un `reviewer` qualsiasi, così l'etichetta "revisionato da [nome]" non attesta un'identità.
- **Decisione (proposta):** nella prima versione l'API resta senza autenticazione ed è usata solo in locale (porte pubblicate su `127.0.0.1` nel compose, `ALLOWED_HOSTS`, un solo worker). Prima di qualsiasi esposizione su una rete condivisa serve un reverse proxy con autenticazione e il `reviewer` va ricavato dall'utente autenticato.
- **Motivazione:** il progetto è un prototipo interno; l'autenticazione cambia il contratto e il frontend e va decisa con l'utente.
- **Conseguenze:** limite documentato in `backend/api/CLAUDE.md` e in [ONBOARDING.md](ONBOARDING.md); da riesaminare prima del rilascio. Stato "Proposta" fino alla decisione dell'utente.
