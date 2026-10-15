"""Parser degli avvisi TED (T1.3): dal JSON della Search API a `TenderCreate`.

Mappatura dei campi in backend/ingestion/MAPPING.md; forma dei dati in docs/TED_API_NOTES.md.
Regole:
- un campo mancante o non interpretabile diventa `None` con un warning nel log, mai un'eccezione;
- testi: italiano, altrimenti inglese, altrimenti la prima lingua disponibile;
- importo: quello della procedura, altrimenti la somma dei lotti nella stessa valuta;
- scadenza: la più vicina tra quelle dei lotti (data + ora con fuso);
- CPV a 8 cifre senza duplicati; `raw_data` conserva l'avviso originale.
`parse_notice` solleva `NoticeParseError` solo se manca un dato senza cui la gara non esiste
(numero o data di pubblicazione validi); `parse_notices` non solleva mai: salta l'avviso e
registra il motivo, qualunque sia l'errore.
"""

import logging
import re
from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from backend.domain.schemas import TenderCreate

logger = logging.getLogger(__name__)

LANGUAGE_PREFERENCE = ("ita", "eng", "mul")
TED_NOTICE_URL = "https://ted.europa.eu/it/notice/-/detail/{publication_number}"
MISSING_TITLE = "(titolo non indicato)"
MISSING_BUYER = "(ente non indicato)"
MISSING_NOTICE_TYPE = "unknown"
_CPV_DIGITS = re.compile(r"^(\d{8})(?:-\d)?$")
_CENT = Decimal("0.01")
# Colonna `estimated_value` Numeric(18, 2): al massimo 16 cifre intere.
MAX_AMOUNT = Decimal(10) ** 16
MAX_PUBLICATION_NUMBER = 50
MAX_NOTICE_TYPE = 100
MAX_URL = 1000
_CURRENCY = re.compile(r"^[A-Za-z]{3}$")


class NoticeParseError(ValueError):
    """Avviso senza numero o data di pubblicazione: non si può trasformare in una gara."""


def pick_text(value: Any) -> str | None:
    """Restituisce il testo nella lingua preferita da un campo multilingua di TED.

    Accetta una stringa, una lista di stringhe o un oggetto `{lingua: testo | [testi]}`.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        texts = [t.strip() for t in value if isinstance(t, str) and t.strip()]
        return " ".join(dict.fromkeys(texts)) or None
    if isinstance(value, dict):
        languages = [lang for lang in LANGUAGE_PREFERENCE if lang in value]
        languages += [lang for lang in value if lang not in LANGUAGE_PREFERENCE]
        for lang in languages:
            text = pick_text(value[lang])
            if text:
                return text
    return None


def pick_first_text(value: Any) -> str | None:
    """Come `pick_text`, ma con più valori (es. più enti) tiene solo il primo."""
    if isinstance(value, dict):
        return pick_text({lang: first_value(texts) for lang, texts in value.items()})
    return pick_text(first_value(value))


def first_value(value: Any) -> Any:
    """Primo elemento di una lista di TED, oppure il valore stesso se non è una lista."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def as_list(value: Any) -> list[Any]:
    """Normalizza un campo di TED in lista (TED usa liste per i campi dei lotti)."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def parse_ted_date(value: Any) -> date | None:
    """Converte una data TED (`2026-10-14+02:00` o `2026-10-14`) in `date`."""
    text = first_value(value)
    if not isinstance(text, str) or len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _split_offset(text: str) -> tuple[str, str]:
    """Separa `2026-11-16+02:00` in (`2026-11-16`, `+02:00`); il fuso può mancare."""
    match = re.match(r"^(.*?)(Z|[+-]\d{2}:\d{2})?$", text.strip())
    if match is None:  # pragma: no cover - l'espressione accetta qualsiasi stringa
        return text, ""
    return match.group(1), match.group(2) or ""


def combine_deadline(date_value: Any, time_value: Any) -> datetime | None:
    """Unisce data e ora di una scadenza TED in un datetime con fuso.

    Senza ora si usa la fine della giornata (23:59:59), per non scartare la gara in anticipo.
    Il fuso dell'ora ha la precedenza su quello della data; senza fuso il valore è scartato.
    """
    if not isinstance(date_value, str):
        return None
    day_text, day_offset = _split_offset(date_value)
    try:
        day = date.fromisoformat(day_text)
    except ValueError:
        return None
    clock = time(23, 59, 59)
    offset = day_offset
    if isinstance(time_value, str) and time_value.strip():
        time_text, time_offset = _split_offset(time_value)
        try:
            clock = time.fromisoformat(time_text)
        except ValueError:
            return None
        offset = time_offset or day_offset
    if not offset:
        return None
    offset = "+00:00" if offset == "Z" else offset
    try:
        return datetime.fromisoformat(f"{day.isoformat()}T{clock.isoformat()}{offset}")
    except ValueError:
        return None


def earliest_deadline(raw: dict[str, Any]) -> datetime | None:
    """Scadenza offerte più vicina tra i lotti (`deadline-receipt-tender-*`, non `deadline`)."""
    dates = as_list(raw.get("deadline-receipt-tender-date-lot"))
    times = as_list(raw.get("deadline-receipt-tender-time-lot"))
    deadlines = []
    for index, day in enumerate(dates):
        clock = times[index] if index < len(times) else None
        deadline = combine_deadline(day, clock)
        if deadline is None:
            logger.warning("Scadenza non interpretabile: %r %r", day, clock)
        else:
            deadlines.append(deadline)
    return min(deadlines) if deadlines else None


def parse_amount(value: Any) -> Decimal | None:
    """Converte un importo TED (stringa o numero) in `Decimal` a due decimali, o `None`."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).strip())
        if not amount.is_finite() or amount < 0 or amount >= MAX_AMOUNT:
            return None
        return amount.quantize(_CENT)
    except InvalidOperation:
        return None


def estimated_value(raw: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    """Importo stimato e valuta: procedura, altrimenti somma dei lotti nella stessa valuta."""
    amount = parse_amount(raw.get("estimated-value-proc"))
    currency = first_value(raw.get("estimated-value-cur-proc"))
    if amount is not None:
        return amount, currency if isinstance(currency, str) else None

    lot_amounts = [parse_amount(v) for v in as_list(raw.get("estimated-value-lot"))]
    lot_currencies = {c for c in as_list(raw.get("estimated-value-cur-lot")) if isinstance(c, str)}
    if lot_amounts and None not in lot_amounts and len(lot_currencies) <= 1:
        total = sum((a for a in lot_amounts if a is not None), Decimal(0))
        return total, next(iter(lot_currencies), None)

    amount = parse_amount(raw.get("estimated-value-glo"))
    currency = first_value(raw.get("estimated-value-cur-glo"))
    if amount is not None:
        return amount, currency if isinstance(currency, str) else None
    return None, None


def normalize_cpv_codes(raw: dict[str, Any]) -> list[str]:
    """CPV di procedura e lotti a 8 cifre, senza duplicati; i codici non validi sono ignorati."""
    codes: dict[str, None] = {}
    fields = ("classification-cpv", "main-classification-proc", "main-classification-lot")
    for field in fields:
        for value in as_list(raw.get(field)):
            match = _CPV_DIGITS.match(str(value).strip())
            if match:
                codes.setdefault(match.group(1), None)
            else:
                logger.warning("CPV non valido ignorato: %r", value)
    return list(codes)


def notice_url(raw: dict[str, Any], publication_number: str) -> str:
    """Link alla pagina dell'avviso su TED, in italiano se disponibile."""
    links = raw.get("links")
    html = links.get("html") if isinstance(links, dict) else None
    if isinstance(html, dict):
        for lang in ("ITA", "ENG"):
            url = html.get(lang)
            if isinstance(url, str) and url.strip() and len(url) <= MAX_URL:
                return url.strip()
    return TED_NOTICE_URL.format(publication_number=publication_number)


def normalize_currency(value: Any) -> str | None:
    """Codice valuta a 3 lettere maiuscole; `None` se assente o non valido."""
    if isinstance(value, str) and _CURRENCY.match(value.strip()):
        return value.strip().upper()
    return None


def change_reference(raw: dict[str, Any]) -> str | None:
    """`notice-identifier` dell'avviso modificato da un change notice; `None` se non è una modifica.

    `change-notice-version-identifier` vale `<notice-identifier>-<versione>`
    (docs/TED_API_NOTES.md, domanda 9).
    """
    value = first_value(raw.get("change-notice-version-identifier"))
    if not isinstance(value, str) or "-" not in value:
        return None
    return value.rsplit("-", 1)[0]


def is_change_notice(raw: dict[str, Any]) -> bool:
    """Indica se l'avviso è una rettifica (change notice) di un avviso precedente."""
    return change_reference(raw) is not None


def _warn_missing(publication_number: str, field: str) -> None:
    logger.warning("Avviso %s: campo %s assente, impostato a null", publication_number, field)


def parse_notice(raw: dict[str, Any], parent_publication_number: str | None = None) -> TenderCreate:
    """Trasforma un avviso TED in `TenderCreate`.

    `parent_publication_number` lo passa il chiamante per le rettifiche (T1.4 risale la catena
    dei change notice fino all'avviso originale).
    """
    publication_number = first_value(raw.get("publication-number"))
    if not isinstance(publication_number, str) or not publication_number.strip():
        raise NoticeParseError("Avviso senza publication-number")
    publication_number = publication_number.strip()
    if len(publication_number) > MAX_PUBLICATION_NUMBER:
        raise NoticeParseError(f"publication-number troppo lungo: {publication_number[:60]!r}")
    publication_date = parse_ted_date(raw.get("publication-date"))
    if publication_date is None:
        raise NoticeParseError(f"Avviso {publication_number} senza data di pubblicazione valida")

    title = pick_text(raw.get("title-proc")) or pick_text(raw.get("notice-title"))
    if title is None:
        title = pick_text(raw.get("title-lot")) or MISSING_TITLE
        _warn_missing(publication_number, "title-proc")
    buyer_name = pick_first_text(raw.get("buyer-name")) or pick_first_text(
        raw.get("organisation-name-buyer")
    )
    if buyer_name is None:
        buyer_name = MISSING_BUYER
        _warn_missing(publication_number, "buyer-name")
    buyer_city = pick_first_text(raw.get("buyer-city")) or pick_first_text(
        raw.get("organisation-city-buyer")
    )
    notice_type = first_value(raw.get("notice-type"))
    if not isinstance(notice_type, str) or not notice_type.strip():
        notice_type = MISSING_NOTICE_TYPE
        _warn_missing(publication_number, "notice-type")

    amount, raw_currency = estimated_value(raw)
    currency = normalize_currency(raw_currency)
    if amount is None:
        _warn_missing(publication_number, "estimated-value")
    elif currency is None:
        logger.warning(
            "Avviso %s: valuta %r non valida, impostata a null", publication_number, raw_currency
        )
    deadline = earliest_deadline(raw)
    if deadline is None:
        _warn_missing(publication_number, "deadline-receipt-tender")
    documents = [u for u in as_list(raw.get("document-url-lot")) if isinstance(u, str)]

    return TenderCreate(
        publication_number=publication_number,
        title=title,
        description=pick_text(raw.get("description-proc")),
        buyer_name=buyer_name[:500],
        buyer_city=buyer_city[:200] if buyer_city else None,
        cpv_codes=normalize_cpv_codes(raw),
        notice_type=notice_type.strip()[:MAX_NOTICE_TYPE],
        estimated_value=amount,
        currency=currency if amount is not None else None,
        publication_date=publication_date,
        submission_deadline=deadline,
        ted_url=notice_url(raw, publication_number),
        documents_url=documents[0][:MAX_URL] if documents else None,
        parent_publication_number=parent_publication_number,
        raw_data=raw,
    )


def parse_notices(raws: Iterable[dict[str, Any]]) -> list[TenderCreate]:
    """Trasforma una lista di avvisi; quelli non convertibili sono saltati con un warning."""
    tenders = []
    for raw in raws:
        try:
            tenders.append(parse_notice(raw))
        except (NoticeParseError, ValidationError) as exc:
            logger.warning("Avviso saltato: %s", exc)
        except Exception:  # il job giornaliero non deve mai fermarsi per un avviso anomalo
            logger.exception("Avviso saltato per un errore inatteso")
    return tenders
