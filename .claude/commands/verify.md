---
description: Verifica il lavoro del branch corrente rispetto ai criteri "Finito quando" del task
---

Branch corrente: !`git branch --show-current`

## Procedura

1. Leggi `docs/TASKS.md` e trova il task (o i task) la cui riga `Branch:` coincide con il branch corrente.
   Se nessun task corrisponde, chiedi all'utente quale task verificare e fermati.
   Se ne corrispondono più di uno (es. `setup/init`), verificali tutti, uno per tabella.
2. Raccogli le evidenze del lavoro svolto:
   - `git status` e `git diff main...HEAD --stat` per i file modificati;
   - `pytest` e `ruff check .` (riporta l'esito reale, anche se fallisce);
   - lettura dei file citati nei criteri.
3. Per ogni criterio "Finito quando" decidi:
   - **Sì** solo se hai un'evidenza concreta: test che passa, file esistente con il contenuto atteso,
     output di un comando eseguito in questa sessione.
   - **No** se l'evidenza mostra che il criterio non è soddisfatto.
   - **Non verificabile** se il criterio richiede persone o sistemi che non puoi controllare
     (approvazioni di PR, validazione di Giuseppe, prove sul computer di altri dev, chiamate reali a TED
     senza autorizzazione). Dichiaralo: non presumere mai che sia soddisfatto.
4. Non modificare file e non spuntare i criteri in `docs/TASKS.md`: lo fa l'utente nella PR.

## Formato della risposta

```
## Verifica <codice task> – <titolo>

| Criterio | Verificato | Evidenza |
|---|---|---|
| <testo del criterio> | Sì / No / Non verificabile | <test, file, comando eseguito ed esito> |
```

Chiudi con: numero di criteri soddisfatti sul totale, cosa manca per chiudere il task e se lo stato
può passare a `[x]`.
