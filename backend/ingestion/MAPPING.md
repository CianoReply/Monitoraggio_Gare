# Mappatura campo TED → `tenders` (T1.3)

Implementata in `backend/ingestion/parser.py`. Forma dei dati TED in [docs/TED_API_NOTES.md](../../docs/TED_API_NOTES.md).
Un campo mancante o non interpretabile diventa `null` con un warning nel log; il parser non blocca mai il job.

| Campo `tenders` | Campo TED (in ordine di preferenza) | Normalizzazione |
|---|---|---|
| `publication_number` | `publication-number` | obbligatorio: senza, l'avviso è saltato |
| `title` | `title-proc` → `notice-title` → `title-lot` | lingua `ita` → `eng` → altre; se manca "(titolo non indicato)" |
| `description` | `description-proc` | come `title`; `null` se manca |
| `buyer_name` | `buyer-name` → `organisation-name-buyer` | primo ente; se manca "(ente non indicato)" |
| `buyer_city` | `buyer-city` → `organisation-city-buyer` | primo valore; `null` se manca |
| `cpv_codes` | `classification-cpv` + `main-classification-proc` + `main-classification-lot` | 8 cifre (il suffisso `-n` è tolto), senza duplicati; codici non validi ignorati |
| `notice_type` | `notice-type` | codice eForms (es. `cn-standard`); se manca `unknown` |
| `estimated_value` | `estimated-value-proc` → somma di `estimated-value-lot` (stessa valuta) → `estimated-value-glo` | `Decimal` a 2 decimali; negativo o non numerico → `null` |
| `currency` | `estimated-value-cur-*` dello stesso livello dell'importo | codice a 3 lettere; `null` senza importo |
| `publication_date` | `publication-date` | solo la data (`2026-10-14+02:00` → 2026-10-14); obbligatoria |
| `submission_deadline` | `deadline-receipt-tender-date-lot` + `deadline-receipt-tender-time-lot` | la più vicina tra i lotti, con fuso; senza ora → 23:59:59; **non** `deadline` (BT-13) |
| `ted_url` | `links.html.ITA` → `links.html.ENG` | se mancano: `https://ted.europa.eu/it/notice/-/detail/<numero>` |
| `documents_url` | `document-url-lot` | primo URL; spesso la piattaforma di gara, non un PDF |
| `parent_publication_number` | passato dal chiamante | per i change notice: avviso originale della catena (T1.4) |
| `raw_data` | intero avviso | invariato |

Il paese dell'ente (`buyer-country`, es. `["ITA"]`) non è nel modello: il job lo legge da `raw_data`
e lo passa a `apply_filters` (T2.2). Un change notice si riconosce con `is_change_notice` e
`change_reference` restituisce il `notice-identifier` dell'avviso modificato.
