# Registro delle decisioni (ADR)

> Ogni decisione architetturale si registra qui con una PR approvata da tutti e tre i dev.
> Formato: contesto, decisione, motivazione, conseguenze. Numerazione progressiva, mai riusata.
> Le decisioni ADR-001…005 provengono da [docs/source/PIANO_BACKEND.md](source/PIANO_BACKEND.md) e vanno confermate in T0.4.

| ADR | Titolo | Stato |
|---|---|---|
| ADR-001 | API di TED invece dello scraping | Proposta |
| ADR-002 | Nessun agente LLM nel backend | Proposta |
| ADR-003 | Il repository è l'unica memoria condivisa | Proposta |
| ADR-004 | Contratto API scritto prima del codice | Proposta |
| ADR-005 | Punteggio a regole configurabili | Proposta |

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
