---
description: Aggiunge in cima a docs/handoff/<dev>.md una nota di passaggio sulla sessione
argument-hint: DEV-1 | DEV-2 | DEV-3 (facoltativo)
---

Data di oggi: !`date +%F`
Branch corrente: !`git branch --show-current`
Dev indicato: $ARGUMENTS

## Procedura

1. Stabilisci il dev:
   - se è indicato sopra, usa quello;
   - altrimenti usa il `Responsabile:` del task che in `docs/TASKS.md` ha come `Branch:` il branch corrente;
   - se ancora non è chiaro, chiedilo all'utente e fermati.
2. Stabilisci il task dal branch corrente (codice e titolo da `docs/TASKS.md`); se non corrisponde a un task,
   chiedilo all'utente.
3. Ricostruisci la sessione da questa conversazione, da `git log main..HEAD --oneline` e da `git diff main...HEAD --stat`.
4. Prepara la nota esattamente in questo formato:

   ```markdown
   ## <data> – <codice task> <titolo breve>
   - Fatto: <cosa è stato completato, con file o test principali>
   - Da fare: <cosa manca rispetto ai criteri "Finito quando">
   - Decisioni: <scelte prese e perché; "nessuna" se non ce ne sono>
   - Impatto sugli altri dev: <chi deve fare o sapere cosa; "nessuno" se non c'è>
   ```

5. Mostra la nota all'utente e chiedi conferma.
6. Dopo la conferma inseriscila in `docs/handoff/<dev>.md` **subito sotto** la riga `<!-- Note -->`,
   sopra le note esistenti, senza modificare il resto del file.

Regole:
- Scrivi solo nel file del dev stabilito al punto 1, mai nei file degli altri dev.
- Riporta solo fatti verificabili; ciò che non è certo va scritto come "DA VERIFICARE".
- Massimo 4 righe dopo il titolo: i dettagli stanno nel codice e nella PR.
