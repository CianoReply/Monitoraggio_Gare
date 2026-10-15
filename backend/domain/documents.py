"""Documenti di gara (T2.4): classifica il link, scarica i file diretti, registra in `documents`.

Il link arriva da `tenders.documents_url` (primo link ai documenti dell'avviso TED). Spesso è la
pagina di una piattaforma di gara, che richiede registrazione: il login NON si automatizza, quindi
il link si salva con stato `not_accessible` e i documenti si scaricano a mano. Si scarica solo se
il link è diretto a un file (estensioni in `config.toml`, sezione `[documents]`).

Stati: `downloaded` = file salvato; `not_accessible` = non scaricabile in automatico (piattaforma,
nessun link, errore permanente, indirizzo non consentito, file troppo grande); `pending` = errore
temporaneo (rete, timeout, 5xx, disco), da ritentare alla prossima chiamata.

Sicurezza del download (SSRF): i link vengono da avvisi pubblici, quindi non sono fidati. I
reindirizzamenti si seguono a mano (max `max_redirects`) e a ogni salto si accettano solo
http/https verso host pubblici: `localhost` e indirizzi privati, loopback, link-local, riservati
o multicast sono rifiutati. Limite noto: il controllo risolve il nome con `getaddrinfo` e poi
httpx lo risolve di nuovo per connettersi, quindi un DNS "rebinding" (risposte diverse tra i due
controlli) non è escluso. In produzione va aggiunto un blocco di rete in uscita verso gli
indirizzi interni (firewall o regole del container).

Limiti noti, da non risolvere con migrazioni: non c'è un vincolo UNIQUE(tender_id, url), perciò si
presume un solo job alla volta; un documento `pending` si riprova a ogni chiamata, senza limite di
tentativi.
"""

from __future__ import annotations

import errno
import ipaddress
import logging
import os
import re
import socket
import time
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.config import DocumentsConfig, load_documents_config
from backend.domain.models import Document, DocumentStatus, Tender, utcnow

logger = logging.getLogger(__name__)

DEFAULT_DOCUMENTS_DIR = "/data/documents"
PLATFORM_DOCUMENT_NAME = "Documenti di gara (piattaforma)"
MISSING_LINK_DOCUMENT_NAME = "Documenti di gara (nessun link)"
CHUNK_SIZE = 64 * 1024
USER_AGENT = "radar-gare-it/0.1 (monitoraggio gare pubbliche)"
MAX_FILENAME_LENGTH = 200
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
TEMPORARY_STATUSES = frozenset({408, 429})
# Contenuti che non sono file ma pagine web (es. la pagina di login di una piattaforma).
WEB_PAGE_TYPES = ("text/html", "application/xhtml+xml")
# Firma iniziale attesa per estensione (tipo di file dichiarato dal link).
FILE_SIGNATURES = {
    ".pdf": (b"%PDF-",),
    ".zip": (b"PK\x03\x04", b"PK\x05\x06"),
}

# (host, porta) -> elenco nello stesso formato di socket.getaddrinfo
Resolver = Callable[..., list[tuple]]


class LinkKind(StrEnum):
    """Tipo di link ai documenti."""

    DIRECT_FILE = "direct_file"  # link diretto a un file: si scarica
    PLATFORM = "platform"  # pagina di una piattaforma di gara: solo link
    MISSING = "missing"  # nessun link (o non http/https)


class DocumentDownloadError(Exception):
    """Download non riuscito. `temporary=True` se vale la pena ritentare più tardi."""

    def __init__(self, message: str, *, temporary: bool = False) -> None:
        super().__init__(message)
        self.temporary = temporary


class DocumentTooLargeError(DocumentDownloadError):
    """Il file supera la dimensione massima consentita."""


class UnsafeUrlError(DocumentDownloadError):
    """L'indirizzo non è consentito (schema non http/https, host interno o non pubblico)."""


def safe_url(url: str) -> str:
    """URL senza credenziali né query string né frammento: è l'unica forma che si scrive nei log
    e nei messaggi di errore (la query può contenere token o dati personali)."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        return "(indirizzo non valido)"
    return f"{parsed.scheme}://{host}{port}{parsed.path}" if host else "(indirizzo non valido)"


def get_documents_dir() -> Path:
    """Cartella radice dei documenti: `DOCUMENTS_DIR` oppure `/data/documents`."""
    return Path(os.environ.get("DOCUMENTS_DIR", "").strip() or DEFAULT_DOCUMENTS_DIR)


def classify_link(url: str | None, config: DocumentsConfig) -> LinkKind:
    """Classifica il link: file diretto (estensione ammessa nel percorso), piattaforma o assente."""
    if not url or not url.strip():
        return LinkKind.MISSING
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return LinkKind.MISSING
    if parsed.path.lower().endswith(config.direct_file_extensions):
        return LinkKind.DIRECT_FILE
    return LinkKind.PLATFORM


def truncate_filename(name: str, max_length: int = MAX_FILENAME_LENGTH) -> str:
    """Accorcia il nome a `max_length` caratteri mantenendo l'estensione."""
    if len(name) <= max_length:
        return name
    stem, dot, extension = name.rpartition(".")
    if not dot or len(extension) > 10:
        return name[:max_length]
    return stem[: max_length - len(extension) - 1] + "." + extension


def _safe_name(name: str, fallback: str) -> str:
    """Nome di file sicuro: solo l'ultimo segmento, senza caratteri speciali, non troppo lungo."""
    base = unquote(name).replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^\w.\- ]", "_", base).strip(" .")
    return truncate_filename(cleaned) or fallback


def document_name_from_url(url: str) -> str:
    """Nome del documento ricavato dal percorso del link (es. `Disciplinare.pdf`)."""
    return _safe_name(urlparse(url).path, "documento")


def tender_documents_dir(publication_number: str, root: Path | None = None) -> Path:
    """Cartella dei file della gara: `<radice>/<publication_number>/`."""
    return (root or get_documents_dir()) / _safe_name(publication_number, "gara")


def document_file_path(document: Document, tender: Tender, root: Path | None = None) -> Path:
    """Percorso del file di un documento: `<cartella gara>/<id>_<nome>` (l'id evita collisioni)."""
    name = truncate_filename(f"{document.id}_{document.name}")
    return tender_documents_dir(tender.publication_number, root) / name


# --- Controllo dell'indirizzo (SSRF) ---


# Reti che Python considera globali ma che portano a indirizzi interni o non raggiungibili:
# NAT64 (64:ff9b::/96) traduce verso IPv4 arbitrari, comprese le reti private.
_BLOCKED_NETWORKS = (ipaddress.ip_network("64:ff9b::/96"),)


def _is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if any(
        address in network for network in _BLOCKED_NETWORKS if network.version == address.version
    ):
        return False
    return address.is_global and not address.is_multicast


def check_public_url(url: str, resolver: Resolver | None = None) -> None:
    """Solleva `UnsafeUrlError` se `url` non è http/https verso un host pubblico.

    Rifiuta `localhost`, IP letterali e nomi che si risolvono (anche solo in parte) in indirizzi
    privati, loopback, link-local, riservati o multicast. Un nome che non si risolve è un errore
    temporaneo (DNS). `resolver` ha la firma di `socket.getaddrinfo` ed è iniettabile nei test.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError(
            f"Schema non consentito ({parsed.scheme or 'assente'}): {safe_url(url)}"
        )
    try:
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError(f"Indirizzo non valido: {safe_url(url)}") from exc
    if not host:
        raise UnsafeUrlError(f"Indirizzo senza host: {safe_url(url)}")
    host = host.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeUrlError(f"Host interno non consentito ({host})")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public(literal):
            raise UnsafeUrlError(f"Indirizzo non pubblico non consentito ({host})")
        return
    try:
        infos = (resolver or socket.getaddrinfo)(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise DocumentDownloadError(
            f"Impossibile risolvere l'host {host}: {exc}", temporary=True
        ) from exc
    addresses = [ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in infos]
    if not addresses:
        raise DocumentDownloadError(f"Nessun indirizzo per l'host {host}", temporary=True)
    if not all(_is_public(a) for a in addresses):
        raise UnsafeUrlError(f"L'host {host} punta a un indirizzo non pubblico: non consentito")


# --- Download ---


def _check_signature(path: Path, extension: str) -> None:
    signatures = FILE_SIGNATURES.get(extension.lower())
    if signatures is None:
        return
    with open(path, "rb") as handle:
        head = handle.read(8)
    if not head.startswith(signatures):
        kind = extension.lstrip(".").upper()
        raise DocumentDownloadError(f"Il contenuto scaricato non è un file {kind} valido")


def download_document(
    client: httpx.Client,
    url: str,
    destination: Path,
    max_bytes: int,
    *,
    max_redirects: int = 5,
    total_timeout: float = 300.0,
    resolver: Resolver | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Scarica `url` in `destination` (percorso del file) e restituisce i byte scritti.

    - Redirect seguiti a mano (anche se il client è configurato per seguirli): al massimo
      `max_redirects` salti, ognuno ricontrollato con `check_public_url`. L'URL finale è solo
      quello scaricato: non cambia `url` e `name` del documento registrato.
    - Solo lo status 200 è un successo; 3xx senza destinazione, 204, 304, 4xx sono errori
      permanenti, 408/429/5xx temporanei.
    - Il file è rifiutato con `DocumentTooLargeError` se `Content-Length` o i byte ricevuti (dopo
      l'eventuale decompressione) superano `max_bytes`. Pagine web e contenuti che non hanno la
      firma attesa (%PDF-, ZIP) sono rifiutati. Non lascia file parziali.
    - `total_timeout` (secondi, su `clock`) limita il tempo complessivo: poi errore temporaneo.
    - Errori temporanei: timeout, rete, protocollo remoto, disco pieno o permessi; permanenti gli
      altri (URL non valido, schema non supportato, troppi reindirizzamenti, ...).
    """
    limit_mb = max_bytes / (1024 * 1024)
    started = clock()

    def check_time() -> None:
        if clock() - started > total_timeout:
            raise DocumentDownloadError(
                f"Tempo massimo di download superato ({total_timeout:.0f} s): {safe_url(url)}",
                temporary=True,
            )

    partial = destination.with_name(destination.name + ".part")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        current = url
        for _hop in range(max_redirects + 1):
            check_time()
            check_public_url(current, resolver)
            next_url: str | None = None
            with client.stream("GET", current, follow_redirects=False) as response:
                status = response.status_code
                if status in REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise DocumentDownloadError(
                            f"Reindirizzamento {status} senza destinazione per {safe_url(current)}"
                        )
                    next_url = urljoin(current, location)
                elif status != 200:
                    raise DocumentDownloadError(
                        f"Il server ha risposto {status} per {safe_url(current)}",
                        temporary=status >= 500 or status in TEMPORARY_STATUSES,
                    )
                else:
                    _save_response(response, partial, current, max_bytes, limit_mb, check_time)
            if next_url is None:
                _check_signature(partial, destination.suffix)
                partial.replace(destination)
                return destination.stat().st_size
            current = next_url
        raise DocumentDownloadError(
            f"Troppi reindirizzamenti (massimo {max_redirects}): {safe_url(url)}"
        )
    except DocumentDownloadError:
        raise
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
        raise DocumentDownloadError(
            f"Download non riuscito per {safe_url(url)}: {exc}", temporary=True
        ) from exc
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        # InvalidURL, UnsupportedProtocol, TooManyRedirects, errori di decodifica: permanenti
        raise DocumentDownloadError(f"Download non riuscito per {safe_url(url)}: {exc}") from exc
    except OSError as exc:
        # disco pieno o permessi: problema dell'ambiente, da ritentare dopo averlo sistemato
        temporary = isinstance(exc, PermissionError) or exc.errno == errno.ENOSPC
        logger.error("Errore di archiviazione per %s in %s: %s", safe_url(url), destination, exc)
        raise DocumentDownloadError(
            f"Impossibile salvare {destination}: {exc}", temporary=temporary
        ) from exc
    finally:
        partial.unlink(missing_ok=True)


def _save_response(
    response: httpx.Response,
    partial: Path,
    url: str,
    max_bytes: int,
    limit_mb: float,
    check_time: Callable[[], None],
) -> None:
    content_type = response.headers.get("content-type", "").lower()
    if content_type.startswith(WEB_PAGE_TYPES):
        raise DocumentDownloadError(
            f"Il link restituisce una pagina web, non un file: {safe_url(url)}"
        )
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise DocumentTooLargeError(
            f"File troppo grande: {int(declared) / (1024 * 1024):.1f} MB "
            f"(massimo {limit_mb:.0f} MB)"
        )
    written = 0
    with open(partial, "wb") as handle:
        for chunk in response.iter_bytes(CHUNK_SIZE):
            written += len(chunk)
            if written > max_bytes:
                raise DocumentTooLargeError(
                    f"File troppo grande: oltre il massimo di {limit_mb:.0f} MB"
                )
            check_time()
            handle.write(chunk)


# --- Registrazione in `documents` ---


def _existing_document(session: Session, tender: Tender, url: str | None) -> Document | None:
    return session.scalar(
        select(Document).where(
            Document.tender_id == tender.id,
            Document.url.is_(None) if url is None else Document.url == url,
        )
    )


def _needs_download(document: Document, *, is_new: bool) -> bool:
    if is_new or document.status is DocumentStatus.PENDING:
        return True
    # già scaricato ma il file non c'è più (volume svuotato): si riscarica
    return document.status is DocumentStatus.DOWNLOADED and not (
        document.local_path and Path(document.local_path).is_file()
    )


def process_tender_documents(
    session: Session,
    tender: Tender,
    client: httpx.Client | None = None,
    *,
    config: DocumentsConfig | None = None,
    documents_dir: Path | None = None,
    resolver: Resolver | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> list[Document]:
    """Registra (ed eventualmente scarica) i documenti di una gara salvata; usata dal job (T1.5).

    - Gara non rilevante (`is_relevant` falso): non fa nulla e restituisce `[]`.
    - Rilevante: garantisce almeno una riga in `documents` per il link `documents_url`.
    - Link diretto a un file: lo scarica (max `max_file_mb`) in
      `<DOCUMENTS_DIR>/<publication_number>/<id>_<nome>`. Un file già `downloaded` (e presente su
      disco) o `not_accessible` (errore permanente) non si riprova; un `pending` (errore
      temporaneo) o un `downloaded` il cui file è sparito sì.
      Piattaforma o nessun link: riga `not_accessible`, nessun download.
    - È idempotente (nessun duplicato per la stessa gara e lo stesso link). Fa solo `flush`.
    Restituisce tutti i documenti della gara.
    """
    if not tender.is_relevant:
        return []
    config = config or load_documents_config()
    url = (tender.documents_url or "").strip() or None
    kind = classify_link(url, config)
    if kind is LinkKind.MISSING:
        url = None

    document = _existing_document(session, tender, url)
    is_new = document is None
    if document is None:
        name = {
            LinkKind.MISSING: MISSING_LINK_DOCUMENT_NAME,
            LinkKind.PLATFORM: PLATFORM_DOCUMENT_NAME,
            LinkKind.DIRECT_FILE: document_name_from_url(url or ""),
        }[kind]
        document = Document(tender=tender, name=name, url=url, status=DocumentStatus.NOT_ACCESSIBLE)
        session.add(document)
    session.flush()  # serve l'id del documento per il nome del file

    if kind is LinkKind.DIRECT_FILE and url and _needs_download(document, is_new=is_new):
        _download_into(document, tender, url, client, config, documents_dir, resolver, clock)
    session.flush()
    return list(tender.documents)


def _download_into(
    document: Document,
    tender: Tender,
    url: str,
    client: httpx.Client | None,
    config: DocumentsConfig,
    documents_dir: Path | None,
    resolver: Resolver | None,
    clock: Callable[[], float],
) -> None:
    destination = document_file_path(document, tender, documents_dir)
    own_client = client is None
    http = client or httpx.Client(
        timeout=config.request_timeout_seconds,
        follow_redirects=False,
        trust_env=False,  # niente proxy né certificati dall'ambiente (HTTP(S)_PROXY, SSL_CERT_FILE)
        headers={"User-Agent": USER_AGENT},
    )
    try:
        download_document(
            http,
            url,
            destination,
            config.max_file_bytes,
            max_redirects=config.max_redirects,
            total_timeout=config.total_timeout_seconds,
            resolver=resolver,
            clock=clock,
        )
    except DocumentDownloadError as exc:
        logger.warning(
            "Documento %s della gara %s non scaricato: %s",
            safe_url(url),
            tender.publication_number,
            exc,
        )
        document.status = DocumentStatus.PENDING if exc.temporary else DocumentStatus.NOT_ACCESSIBLE
        document.local_path = None
        document.downloaded_at = None
    else:
        document.status = DocumentStatus.DOWNLOADED
        document.local_path = str(destination)
        document.downloaded_at = utcnow()
    finally:
        if own_client:
            http.close()
