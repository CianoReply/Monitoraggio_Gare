---
description: Mostra i task di un dev da docs/TASKS.md con dipendenze e note di handoff rilevanti
argument-hint: DEV-1 | DEV-2 | DEV-3
---

Il codice del dev è: **$ARGUMENTS**

Se il codice è vuoto o non è uno tra `DEV-1`, `DEV-2`, `DEV-3`, chiedi all'utente quale dev è e fermati.

## Procedura

1. Leggi `docs/TASKS.md` per intero e cerca in tutte le sezioni (i task di Fase 0 hanno responsabili diversi).
   Leggi la riga `Responsabile:` di ogni task:
   - **task del dev:** il primo codice dev della riga è quello indicato, oppure la riga inizia con "Tutti";
   - **partecipazione:** il codice compare più avanti nella riga (es. "rivedono DEV-2 e DEV-3",
     "DEV-1 e DEV-2 approvano") o la riga dice "tutti partecipano". Questi task vanno nella sezione
     "Revisioni e partecipazioni", non tra i task del dev.
2. Per ogni task considera stato (`[ ]` da fare, `[~]` in corso, `[x]` fatto, `[!]` bloccato) e la riga `Dipende da:`.
   Una dipendenza è **soddisfatta** solo se il task da cui si dipende è `[x]`.
   "Fasi 1A, 1B, 1C" significa tutti i task T1.x, T2.x e T3.x.
3. Classifica i task del dev:
   - **In corso:** stato `[~]`.
   - **Prossimo task:** il primo task `[ ]`, nell'ordine del file, con tutte le dipendenze soddisfatte.
     Se nessuno è libero, dillo esplicitamente.
   - **Bloccati:** task `[ ]` o `[!]` con almeno una dipendenza non soddisfatta; per ognuno indica quali
     dipendenze mancano, il loro responsabile e il loro stato.
4. Individua gli altri dev responsabili delle dipendenze dei task in corso, del prossimo task e dei bloccati.
   Per ognuno leggi `docs/handoff/DEV-n.md` e riporta **solo la nota più recente** (la prima sotto `<!-- Note -->`).
   Se il file non contiene note, scrivi "nessuna nota".
5. Non modificare alcun file.

## Formato della risposta

```
## Task di <DEV-n>

### In corso
| Task | Branch | Criteri ancora aperti |

### Prossimo task
<codice – titolo> · branch <branch> · durata <durata>
Obiettivo: <obiettivo>
Dipendenze: <elenco, tutte [x]>

### Bloccati
| Task | Manca | Responsabile della dipendenza | Stato della dipendenza |

### Revisioni e partecipazioni
| Task | Ruolo del dev | Stato |

### Note di handoff rilevanti
| Dev | Data e task della nota | Impatto su di te |
```

Chiudi con una riga: il task che consigli di iniziare adesso e perché. Se ti manca un'informazione, dichiaralo
invece di dedurla.
