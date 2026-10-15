"""Client dell'API di ricerca di TED (T1.2).

Riferimento: docs/TED_API_NOTES.md. Il client restituisce gli avvisi grezzi (dict) così come
arrivano da TED; la conversione nel nostro modello è compito del parser (T1.3).

Comportamento:
- query: ente in Italia (`buyer-country=ITA`), CPV IT per prefisso, data di pubblicazione;
- paginazione `ITERATION`: nessun limite sul totale, si segue `iterationNextToken` fino alla fine;
- timeout di 30 s per richiesta; su errori di rete, 5xx e 429 fino a 3 nuovi tentativi
  dopo il primo, con attese di 1 s, 2 s e 4 s;
- pausa minima tra due richieste (rate limit: TED risponde 429 alle raffiche).
"""

import logging
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api.ted.europa.eu/v3/notices/search"
DEFAULT_CPV_PREFIXES: tuple[str, ...] = ("72", "48", "302", "324", "642")

# Campi richiesti a TED (docs/TED_API_NOTES.md, domanda 8). Campi × page_size ≤ 10.000.
NOTICE_FIELDS: tuple[str, ...] = (
    "publication-number",
    "notice-identifier",
    "notice-version",
    "notice-type",
    "form-type",
    "procedure-type",
    "contract-nature-main-proc",
    "publication-date",
    "dispatch-date",
    "notice-title",
    "title-proc",
    "title-lot",
    "description-proc",
    "buyer-name",
    "buyer-city",
    "buyer-country",
    "organisation-name-buyer",
    "organisation-city-buyer",
    "classification-cpv",
    "main-classification-proc",
    "main-classification-lot",
    "estimated-value-proc",
    "estimated-value-cur-proc",
    "estimated-value-lot",
    "estimated-value-cur-lot",
    "estimated-value-glo",
    "estimated-value-cur-glo",
    "deadline-receipt-tender-date-lot",
    "deadline-receipt-tender-time-lot",
    "deadline-date-lot",
    "deadline",
    "document-url-lot",
    "submission-url-lot",
    "identifier-lot",
    "procedure-identifier",
    "change-notice-version-identifier",
    "change-description",
    "change-reason-code",
    "change-previous-notice-section-identifier",
    "previous-notice-id-proc",
    "links",
)
MAX_FIELDS_PER_PAGE = 10_000
MAX_PAGE_SIZE = 250
RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)
MAX_PAGES = 100  # 100 × 200 = 20.000 avvisi, ben oltre il volume di un giorno


class TedApiError(Exception):
    """Errore non recuperabile nella comunicazione con TED."""


@dataclass(frozen=True)
class TedClientConfig:
    """Parametri del client; `from_env` li legge da `TED_API_URL` e `TED_CPV_PREFIXES`."""

    api_url: str = DEFAULT_API_URL
    cpv_prefixes: tuple[str, ...] = DEFAULT_CPV_PREFIXES
    page_size: int = 200
    timeout: float = 30.0
    min_interval: float = 1.0

    def __post_init__(self) -> None:
        if not self.cpv_prefixes:
            raise ValueError("Serve almeno un prefisso CPV.")
        for prefix in self.cpv_prefixes:
            if not (prefix.isascii() and prefix.isdigit() and 1 <= len(prefix) <= 8):
                raise ValueError(f"Prefisso CPV non valido: {prefix!r} (da 1 a 8 cifre).")
        if not 1 <= self.page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size deve essere tra 1 e {MAX_PAGE_SIZE}.")
        if len(NOTICE_FIELDS) * self.page_size > MAX_FIELDS_PER_PAGE:
            raise ValueError(
                f"page_size troppo grande: {len(NOTICE_FIELDS)} campi × {self.page_size} "
                f"supera il limite TED di {MAX_FIELDS_PER_PAGE} campi per pagina."
            )

    @classmethod
    def from_env(cls) -> "TedClientConfig":
        """Legge la configurazione dalle variabili d'ambiente; i valori vuoti usano i default."""
        api_url = os.environ.get("TED_API_URL", "").strip() or DEFAULT_API_URL
        if not api_url.lower().startswith("https://"):
            raise ValueError(f"TED_API_URL deve usare https: {api_url!r}")
        if not api_url.lower().startswith("https://api.ted.europa.eu/"):
            logger.warning("TED_API_URL punta a un host diverso da api.ted.europa.eu: %s", api_url)
        raw_prefixes = os.environ.get("TED_CPV_PREFIXES", "")
        prefixes = tuple(p.strip() for p in raw_prefixes.split(",") if p.strip())
        return cls(api_url=api_url, cpv_prefixes=prefixes or DEFAULT_CPV_PREFIXES)


def build_query(publication_date: date, cpv_prefixes: Iterable[str]) -> str:
    """Costruisce la query "expert search" per gli avvisi IT con ente italiano di un giorno."""
    cpv = " ".join(f"{prefix}*" for prefix in cpv_prefixes)
    day = publication_date.strftime("%Y%m%d")
    return f"buyer-country=ITA AND classification-cpv IN ({cpv}) AND publication-date={day}"


def is_retryable_status(status_code: int) -> bool:
    """Indica se una risposta HTTP va ritentata: errori del server e rate limit (429)."""
    return status_code == 429 or status_code >= 500


class TedClient:
    """Esegue ricerche su TED con ritentativi, pausa tra le richieste e paginazione."""

    def __init__(
        self,
        config: TedClientConfig | None = None,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or TedClientConfig.from_env()
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=self.config.timeout)
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None

    def close(self) -> None:
        """Chiude la connessione HTTP, solo se l'ha creata il client stesso."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "TedClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _wait_rate_limit(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._clock() - self._last_request_at
        if elapsed < self.config.min_interval:
            self._sleep(self.config.min_interval - elapsed)

    def post_search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Invia una richiesta di ricerca con i ritentativi; restituisce il JSON della risposta."""
        attempts = len(RETRY_DELAYS) + 1
        last_error = ""
        for attempt in range(1, attempts + 1):
            self._wait_rate_limit()
            self._last_request_at = self._clock()
            try:
                response = self._http.post(
                    self.config.api_url, json=body, timeout=self.config.timeout
                )
            except httpx.RequestError as exc:
                last_error = f"errore di rete: {exc.__class__.__name__}: {exc}"
            else:
                if response.status_code == 200:
                    try:
                        data = response.json()
                    except ValueError:
                        data = None
                    if isinstance(data, dict) and data.get("timedOut"):
                        last_error = "TED ha risposto timedOut: risultato parziale"
                    elif isinstance(data, dict):
                        return data
                    last_error = f"risposta 200 non valida: {response.text[:200]!r}"
                elif not is_retryable_status(response.status_code):
                    raise TedApiError(
                        f"TED ha risposto {response.status_code}: {response.text[:200]}"
                    )
                else:
                    last_error = f"TED ha risposto {response.status_code}: {response.text[:200]!r}"
            if attempt < attempts:
                delay = RETRY_DELAYS[attempt - 1]
                logger.warning(
                    "Richiesta a TED fallita (%s), tentativo %d di %d tra %.0f s",
                    last_error,
                    attempt + 1,
                    attempts,
                    delay,
                )
                self._sleep(delay)
        raise TedApiError(f"TED non raggiungibile dopo {attempts} richieste: {last_error}")

    def search(self, query: str, fields: Iterable[str] = NOTICE_FIELDS) -> list[dict[str, Any]]:
        """Restituisce tutti gli avvisi della query, seguendo la paginazione `ITERATION`.

        Si ferma alla prima pagina vuota, senza token, con un token già visto o quando ha raccolto
        `totalNoticeCount` avvisi; oltre `MAX_PAGES` pagine solleva `TedApiError`.
        """
        field_list = list(fields)
        if len(field_list) * self.config.page_size > MAX_FIELDS_PER_PAGE:
            raise ValueError("Troppi campi per la dimensione della pagina (limite TED 10.000).")
        body: dict[str, Any] = {
            "query": query,
            "fields": field_list,
            "limit": self.config.page_size,
            "paginationMode": "ITERATION",
        }
        notices: list[dict[str, Any]] = []
        seen_tokens: set[str] = set()
        for _ in range(MAX_PAGES):
            data = self.post_search(body)
            page = data.get("notices") or []
            notices.extend(page)
            total = data.get("totalNoticeCount")
            token = data.get("iterationNextToken")
            if not page or not token or token in seen_tokens:
                return notices
            if isinstance(total, int) and len(notices) >= total:
                return notices
            seen_tokens.add(token)
            body = {**body, "iterationNextToken": token}
        raise TedApiError(f"Paginazione interrotta dopo {MAX_PAGES} pagine: risultato incompleto.")

    def fetch_notices(self, publication_date: date) -> list[dict[str, Any]]:
        """Restituisce gli avvisi IT con ente italiano pubblicati nel giorno indicato."""
        query = build_query(publication_date, self.config.cpv_prefixes)
        notices = self.search(query)
        logger.info("TED: %d avvisi per il %s", len(notices), publication_date.isoformat())
        return notices


def fetch_notices(
    publication_date: date, config: TedClientConfig | None = None
) -> list[dict[str, Any]]:
    """Funzione di comodo del piano: apre un client, scarica gli avvisi del giorno e lo chiude."""
    with TedClient(config) as client:
        return client.fetch_notices(publication_date)
