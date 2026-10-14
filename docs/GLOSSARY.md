# Glossario

Termini usati nei documenti e nel codice. Lo modificano tutti: aggiungi un termine quando lo introduci.
I dettagli tecnici su TED sono DA VERIFICARE in T1.1 (`docs/TED_API_NOTES.md`).

## Dominio

| Termine | Significato | Nel codice |
|---|---|---|
| TED | *Tenders Electronic Daily*: portale ufficiale dell'UE per gli avvisi di appalto pubblico ([ted.europa.eu](https://ted.europa.eu)) | `ted_client`, `ted_url` |
| Avviso | Singola pubblicazione su TED (bando, rettifica, aggiudicazione…) | `notice` |
| Gara | Procedura di appalto; nel nostro sistema una riga di `tenders` | `tender` |
| Bando | Avviso che apre una gara e invita a presentare offerte | `notice_type` |
| Avviso di preinformazione | Avviso che annuncia una gara futura | `notice_type` |
| Rettifica | Avviso che modifica un avviso precedente (es. nuova scadenza) | `parent_publication_number` |
| Aggiudicazione | Avviso che comunica il vincitore; viene scartato dai filtri | `notice_type` |
| Numero di pubblicazione | Identificativo TED di un avviso; chiave della deduplica | `publication_number` |
| Ente appaltante | Amministrazione che bandisce la gara | `buyer_name`, `buyer_city` |
| CPV | *Common Procurement Vocabulary*: codici di 8 cifre che classificano l'oggetto dell'appalto | `cpv_codes` |
| CPV IT | Codici che iniziano con 72, 48, 302, 324 o 642 | `TED_CPV_PREFIXES` |
| CPV core | CPV IT di maggior interesse (es. 72200000, 72500000), con più punti nel punteggio | `config.yaml` |
| eForms | Standard UE per la struttura dei dati degli avvisi | parser (T1.3) |
| Lotto | Parte di una gara aggiudicabile separatamente | DA VERIFICARE in T1.1 |
| Importo stimato | Valore stimato dell'appalto, con valuta separata | `estimated_value`, `currency` |
| Scadenza offerte | Termine per presentare le offerte | `submission_deadline` |
| Disciplinare | Documento con regole di partecipazione e criteri di valutazione | `documents` |
| Capitolato | Documento con le specifiche tecniche della fornitura o del servizio | `documents` |
| Piattaforma di e-procurement | Sito dove l'ente pubblica i documenti, spesso con registrazione (es. MEPA) | `status = not_accessible` |
| Punteggio di pertinenza | Voto da 1 a 5 calcolato con regole deterministiche | `relevance_score` |
| Gara rilevante | Gara con voto ≥ soglia (predefinita 3) | `is_relevant` |
| Motivo di scarto | Regola di filtro non rispettata | `discard_reason` |
| Report di gara | Analisi dei documenti prodotta con la Skill `analisi-gara` | `reports` |
| Campo critico | Campo del report da verificare a mano: importi, fatturati, norme, requisiti legali o contrattuali | `is_critical` |
| Etichetta AI | Dicitura di trasparenza (AI Act) con revisore e data | `ai_label` |
| Esecuzione | Un giro completo del job giornaliero | `ingestion_runs` |

## Tecnici e Claude Code

| Termine | Significato |
|---|---|
| `CLAUDE.md` | File di istruzioni che Claude Code carica a ogni sessione; uno in radice, uno per modulo |
| Slash command | Comando di team in `.claude/commands/`, es. `/my-tasks DEV-2`, `/verify`, `/handoff` |
| Subagent | Assistente con contesto separato definito in `.claude/agents/`; restituisce solo una sintesi |
| Hook | Comando eseguito automaticamente da Claude Code in un momento preciso, es. `PostToolUse` dopo una modifica |
| Skill | Procedura riutilizzabile in `.claude/skills/<nome>/SKILL.md` (es. `analisi-gara`, T5.1) |
| Plan mode | Modalità in cui Claude ragiona e propone senza modificare file |
| Worktree | Seconda cartella dello stesso repository su un altro branch, con sessione separata |
| Handoff | Nota di passaggio a fine sessione in `docs/handoff/DEV-n.md` |
| ADR | *Architecture Decision Record*: voce di [DECISIONS.md](DECISIONS.md) |
| Contratto API | `docs/API_CONTRACT.yaml` in OpenAPI 3 (T0.5) |
| Fixture | Risposta TED salvata in `backend/tests/fixtures/`, usata nei test senza rete |
| Deduplica | Aggiornare una gara esistente invece di inserirla due volte |
| Headless | Esecuzione di Claude Code senza interfaccia, con `claude -p` (T5.2) |
| Definition of Done | Criteri "Finito quando" di ogni task in [TASKS.md](TASKS.md) |
