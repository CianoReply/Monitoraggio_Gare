"""Documenti di gara (T2.4): classifica il link, scarica i file diretti, registra in `documents`.

Il link arriva da `tenders.documents_url` (primo link ai documenti dell'avviso TED). Spesso è la
pagina di una piattaforma di gara, che richiede registrazione: il login NON si automatizza, quindi
il link si salva con stato `not_accessible` e i documenti si scaricano a mano. Si scarica solo se
il link è diretto a un file (estensioni in `config.toml`, sezione `[documents]`).

Stati: `downloaded` = file salvato; `not_accessible` = non scaricabile in automatico (piattaforma,
nessun link, errore permanente, file troppo grande); `pending` = errore temporaneo (rete, timeout,
5xx), da ritentare alla prossima chiamata.
"""

from __future__ import annotations

import logging
import os
import re
from enum import StrEnum
from pathlib import Path
from urllib.parse import unquote, urlparse

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


def _safe_name(name: str, fallback: str) -> str:
    """Nome di file sicuro: solo l'ultimo segmento, senza caratteri speciali."""
    base = unquote(name).replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^\w.\- ]", "_", base).strip(" .")
    return cleaned or fallback


def document_name_from_url(url: str) -> str:
    """Nome del documento ricavato dal percorso del link (es. `Disciplinare.pdf`)."""
    return _safe_name(urlparse(url).path, "documento")


def tender_documents_dir(publication_number: str, root: Path | None = None) -> Path:
    """Cartella dei file della gara: `<radice>/<publication_number>/`."""
    return (root or get_documents_dir()) / _safe_name(publication_number, "gara")


def download_document(client: httpx.Client, url: str, destination: Path, max_bytes: int) -> int:
    """Scarica `url` in `destination` (percorso del file) e restituisce i byte scritti.

    Il file è rifiutato con `DocumentTooLargeError` se `Content-Length` o i byte ricevuti
    superano `max_bytes` (il conteggio avviene durante lo streaming, quindi vale anche senza
    `Content-Length`). Non lascia file parziali. Altri errori: `DocumentDownloadError`.
    """
    limit_mb = max_bytes / (1024 * 1024)
    partial = destination.with_name(destination.name + ".part")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with client.stream("GET", url) as response:
            status = response.status_code
            if status >= 400:
                raise DocumentDownloadError(
                    f"Il server ha risposto {status} per {url}", temporary=status >= 500
                )
            if response.headers.get("content-type", "").lower().startswith("text/html"):
                raise DocumentDownloadError(
                    f"Il link restituisce una pagina web, non un file: {url}"
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
                    handle.write(chunk)
        partial.replace(destination)
        return written
    except httpx.HTTPError as exc:
        raise DocumentDownloadError(
            f"Download non riuscito per {url}: {exc}", temporary=True
        ) from exc
    except OSError as exc:
        raise DocumentDownloadError(f"Impossibile salvare {destination}: {exc}") from exc
    finally:
        partial.unlink(missing_ok=True)


def _existing_document(session: Session, tender: Tender, url: str | None) -> Document | None:
    return session.scalar(
        select(Document).where(
            Document.tender_id == tender.id,
            Document.url.is_(None) if url is None else Document.url == url,
        )
    )


def process_tender_documents(
    session: Session,
    tender: Tender,
    client: httpx.Client | None = None,
    *,
    config: DocumentsConfig | None = None,
    documents_dir: Path | None = None,
) -> list[Document]:
    """Registra (ed eventualmente scarica) i documenti di una gara salvata; usata dal job (T1.5).

    - Gara non rilevante (`is_relevant` falso): non fa nulla e restituisce `[]`.
    - Rilevante: garantisce almeno una riga in `documents` per il link `documents_url`.
    - Link diretto a un file: lo scarica (max `max_file_mb`) in
      `<DOCUMENTS_DIR>/<publication_number>/`. Un file già `downloaded` o `not_accessible`
      (errore permanente) non si riprova; un `pending` (errore temporaneo) sì.
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

    if (
        kind is LinkKind.DIRECT_FILE
        and url
        and (is_new or document.status is DocumentStatus.PENDING)
    ):
        _download_into(document, tender, url, client, config, documents_dir)
    session.flush()
    return list(tender.documents)


def _download_into(
    document: Document,
    tender: Tender,
    url: str,
    client: httpx.Client | None,
    config: DocumentsConfig,
    documents_dir: Path | None,
) -> None:
    destination = tender_documents_dir(tender.publication_number, documents_dir) / document.name
    own_client = client is None
    http = client or httpx.Client(
        timeout=config.request_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        download_document(http, url, destination, config.max_file_bytes)
    except DocumentDownloadError as exc:
        logger.warning(
            "Documento %s della gara %s non scaricato: %s", url, tender.publication_number, exc
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
