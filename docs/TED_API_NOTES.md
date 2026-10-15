# Note sull'API di ricerca di TED (T1.1)

> Scritte da DEV-1 il 2026-10-15. Fonte di riferimento per il client (T1.2), il parser (T1.3) e la deduplica (T1.4).
> Ogni risposta indica se è **verificata con una chiamata reale** (fixture in `backend/tests/fixtures/`)
> o solo **dalla documentazione**; ciò che non è confermato è marcato **DA VERIFICARE**.

## Fixture reali salvate

Ogni file contiene `request` (corpo inviato) e `response` (risposta grezza di TED).

| File | Richiesta | Contenuto |
|---|---|---|
| `ted_search_it_2026-10-14.json` | avvisi con ente italiano, CPV IT, pubblicati il 2026-10-14 | 9 avvisi (6 `cn-standard`, 3 `can-standard`), con 41 campi |
| `ted_search_it_changes_2026-10.json` | come sopra, solo change notice, 1–14 ottobre 2026 | 3 avvisi di modifica (rettifiche) su 15 |
| `ted_lookup_change_predecessors.json` | ricerca per `notice-identifier` degli avvisi a cui puntano i change notice | 4 avvisi, tra cui una catena di due modifiche |

## Risposte alle 9 domande del piano

### 1. Endpoint e chiave API — verificato
- `POST https://api.ted.europa.eu/v3/notices/search`, corpo JSON, **nessuna chiave** per la ricerca
  (la chiave serve solo per gli avvisi non ancora pubblicati: [docs](https://docs.ted.europa.eu/api/latest/index.html)).
- Corpo: `query` (stringa, sintassi "expert search"), `fields` (lista di nomi di campo, obbligatoria),
  `limit`, `page`, `paginationMode` (`PAGE_NUMBER` predefinito o `ITERATION`), `iterationNextToken`.
- Risposta: `{"notices": [...], "totalNoticeCount": n, "iterationNextToken": ..., "timedOut": false}`.
- Un campo non supportato in `fields` dà `400` con l'elenco dei 1830 campi ammessi nel messaggio.
- `checkQuerySyntax: true` controlla solo la sintassi: risposta con `notices` vuoto e `totalNoticeCount: null`.
- `scope`: `ACTIVE` e `ALL` restituiscono risultati, `LATEST` ha restituito 0 avvisi su una query che ne ha 9.
  `onlyLatestVersions: true` è accettato senza errori. Effetto di entrambi **DA VERIFICARE**: il client non li usa.

### 2. Filtro Paese dell'ente = Italia — verificato
- `buyer-country=ITA` (codice ISO a 3 lettere). Nella risposta il campo è una lista: `"buyer-country": ["ITA"]`.
- `place-of-performance` è il luogo di esecuzione, non l'ente: non si usa.

### 3. Filtro CPV per prefisso — verificato
- `classification-cpv IN (72* 48* 302* 324* 642*)`: il carattere `*` finale fa da prefisso; `IN` equivale a un OR.
- `classification-cpv` copre procedura e lotti; nella risposta è una lista con **duplicati**
  (es. `["72500000", "72500000"]`): il parser li toglie (ADR-007). Esistono anche `main-classification-proc`
  e `main-classification-lot` (CPV principale).

### 4. Filtro data di pubblicazione — verificato
- Un giorno: `publication-date=20261014`. Intervallo: `publication-date=(20261001 <> 20261014)`, estremi inclusi.
- Nella risposta la data ha il fuso: `"publication-date": "2026-10-14+02:00"`.

### 5. Tipi di avviso — verificato
- `notice-type` (codelist eForms): bandi `cn-standard`, `cn-social`, `cn-desg`; preinformazione `pin-*`;
  esiti `can-standard`, `can-social`, `can-desg`, `can-tran`; modifica di contratto `can-modif`; altri `veat`, `compl`, `subco`, `pmc`
  ([codelist](https://docs.ted.europa.eu/eforms/latest/reference/code-lists/notice-type.html)).
- `form-type`: `competition` per i bandi, `result` per gli esiti (osservati).
- **Non esiste un tipo "rettifica"**: vedi domanda 9.
- Avvisi pre-eForms (formulari standard prima del 2023-10-25): copertura nella Search API **DA VERIFICARE** (non incontrati).

### 6. Paginazione — verificato
- `PAGE_NUMBER`: `limit` massimo **250** (con 251 → `400 SEARCH_EXCEEDS_MAX_LIMIT`), `page` da 1;
  massimo 15.000 avvisi per query (solo documentazione).
- Limite combinato: **numero di campi × `limit` ≤ 10.000** (`400 SEARCH_FIELDS_PER_PAGE_EXCEEDS_MAX_LIMIT`).
  Con i 41 campi del parser si usa `limit` 200.
- `ITERATION`: la risposta contiene `iterationNextToken`; la richiesta successiva con lo stesso corpo e il token
  restituisce la pagina seguente senza sovrapposizioni (verificato). Durata del token **DA VERIFICARE**.
- Volume tipico: 150 avvisi con ente italiano in un giorno, 9 con CPV IT (2026-10-14). Una pagina basta quasi sempre,
  ma il client deve comunque iterare finché `notices` è vuoto o si raggiunge `totalNoticeCount`.

### 7. Rate limit — verificato in parte
- Una raffica di richieste ravvicinate (circa 1 al secondo) riceve **`429 Too Many Requests`** con corpo HTML di nginx,
  senza intestazioni `Retry-After` né `X-RateLimit-*`. Con 3 secondi tra le richieste non ci sono stati errori.
- La documentazione indica solo regole generali del sito (700 richieste al minuto,
  [developers' corner](https://ted.europa.eu/en/simap/developers-corner-for-reusers)): il limite reale della ricerca è più basso, valore esatto **DA VERIFICARE**.
- Conseguenza per T1.2: trattare `429` come errore da ritentare (oltre a 5xx e rete), con attesa crescente, e almeno 1 secondo tra le pagine.

### 8. Campi di titolo, ente, importo, scadenza, documenti — verificato
I testi sono oggetti per lingua con codici ISO a 3 lettere minuscoli (`ita`, `eng`, `mul`), a volte con lista di valori.

| Dato | Campo TED | Forma nella risposta | Note |
|---|---|---|---|
| Numero di pubblicazione | `publication-number` | `"707611-2026"` | 6 cifre + anno negli avvisi osservati |
| Titolo | `title-proc` | `{"ita": "..."}` | `notice-title` ha il prefisso "Italia – Servizi informatici – ..." (meno utile) |
| Descrizione | `description-proc` | `{"ita": "..."}` | |
| Ente | `buyer-name` | `{"ita": ["Comune di Pizzo"]}` | uguale a `organisation-name-buyer` negli esempi |
| Città dell'ente | `buyer-city` | `{"mul": ["Pizzo Calabro"]}` | `organisation-city-buyer` è una lista semplice |
| Importo stimato | `estimated-value-proc` + `estimated-value-cur-proc` | `"293278.68"` (stringa) + `"EUR"` | per lotto: `estimated-value-lot` / `-cur-lot` (liste) |
| Scadenza offerte | `deadline-receipt-tender-date-lot` + `deadline-receipt-tender-time-lot` | `["2026-11-16+02:00"]` + `["12:00:00+02:00"]` | una voce per lotto; **non** usare `deadline` (vedi sotto) |
| Link ai documenti | `document-url-lot` | lista di URL | spesso la piattaforma di gara, non un PDF |
| Link per l'offerta | `submission-url-lot` | lista di URL | |
| Link all'avviso | `links.html.ITA` | `https://ted.europa.eu/it/notice/-/detail/707611-2026` | anche `links.pdf.ITA`, `links.xml.MUL` |
| Tipo di procedura | `procedure-type` | `"open"` | |

- `deadline` e `deadline-date-lot` sono un'**altra scadenza** (BT-13, richieste di informazioni): nell'avviso 707611-2026
  valgono 2026-11-06 mentre le offerte scadono il 2026-11-16. Per `submission_deadline` vale solo `deadline-receipt-tender-*`.
- Campi assenti: TED omette la chiave (non manda `null`). Gli esiti (`can-*`) non hanno scadenza; alcuni bandi non hanno importo.

### 9. Riconoscere una rettifica e collegarla all'originale — verificato
- Una rettifica è un **change notice**: ha lo **stesso `notice-type`** dell'avviso che modifica (es. `cn-standard`)
  e il campo **`change-notice-version-identifier`** valorizzato, nella forma `<notice-identifier>-<versione>`
  (es. `"42f656d2-162c-4575-ac34-52915bdfec90-01"`). Altri campi possibili: `change-reason-code` (es. `update-add`),
  `change-description` (testo per lingua), `change-previous-notice-section-identifier` (es. `["LOT-0001"]`).
- Il riferimento punta all'avviso **immediatamente precedente**, non per forza all'originale: 687833-2026 → 566426-2026,
  che è a sua volta una modifica di 437009-2026. Per trovare l'originale si risale la catena cercando
  `notice-identifier=<uuid>` finché l'avviso trovato non ha `change-notice-version-identifier`.
- `procedure-identifier` **non** è affidabile per il collegamento: in 684359-2026 è diverso da quello dell'avviso modificato.
- Proposta per T1.3/T1.4 (nessuna modifica al modello dati): il client risale la catena con una ricerca per
  `notice-identifier` e il parser imposta `parent_publication_number` al `publication-number` dell'avviso **originale**
  della catena. `raw_data` conserva `notice-identifier` e `change-notice-version-identifier`.

## Dubbi aperti di T0.4 (ARCHITECTURE §5.1)

| # | Esito |
|---|---|
| Q1 | Chiuso: endpoint e assenza di chiave verificati (domanda 1). |
| Q2 | Chiuso: `buyer-country=ITA` (domanda 2). |
| Q3 | Chiuso: `classification-cpv` con `*` (domanda 3). |
| Q4 | Chiuso: `publication-date`, formato `YYYYMMDD`, intervalli `(a <> b)` (domanda 4). |
| Q5 | Chiuso per gli avvisi eForms (domanda 5); pre-eForms DA VERIFICARE. |
| Q6 | Chiuso: 250 per pagina, campi × limit ≤ 10.000, `ITERATION` verificata (domanda 6). |
| Q7 | Riportato: 429 osservato, limite esatto DA VERIFICARE (domanda 7). |
| Q8 | Chiuso: tabella della domanda 8. |
| Q9 | Chiuso con correzione: il legame passa da `change-notice-version-identifier` → `notice-identifier`, non da `procedure-identifier` (domanda 9). |
| Q10 | Chiuso: `publication-number` a 6 cifre + anno negli avvisi recenti; lingue come oggetti `ita`/`eng`/`mul`. |
| Q11 | Riportato a T1.3: importo e scadenza esistono per procedura e per lotto; regola proposta: importo da `estimated-value-proc` (se manca, somma dei lotti nella stessa valuta), scadenza = la più vicina tra i lotti. |

La sezione 5.1 di [ARCHITECTURE.md](ARCHITECTURE.md) resta invariata (file condiviso): questo file ne è l'aggiornamento.

## Richiesta di riferimento per T1.2

```json
{
  "query": "buyer-country=ITA AND classification-cpv IN (72* 48* 302* 324* 642*) AND publication-date=20261014",
  "fields": ["publication-number", "notice-identifier", "notice-type", "..."],
  "limit": 200,
  "page": 1
}
```
L'elenco completo dei 41 campi è in `request.fields` della fixture `ted_search_it_2026-10-14.json`.
