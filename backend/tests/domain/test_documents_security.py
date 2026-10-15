"""Test della sicurezza e della robustezza del download dei documenti (T2.4): SSRF, errori httpx,
tempo complessivo, nomi di file, errori di archiviazione, firma del contenuto. Nessuna rete."""

import errno
import gzip
import logging
import socket
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session

from backend.domain import documents as documents_module
from backend.domain.config import DocumentsConfig, load_documents_config
from backend.domain.documents import (
    DocumentDownloadError,
    DocumentTooLargeError,
    UnsafeUrlError,
    document_file_path,
    download_document,
    process_tender_documents,
    truncate_filename,
)
from backend.domain.models import Document, DocumentStatus
from backend.tests.domain.test_documents import (
    DNS,
    MB,
    PDF_BYTES,
    PDF_URL,
    PUBLIC_IP,
    add_tender,
    forbidden_handler,
    make_client,
    pdf_handler,
    public_dns,  # noqa: F401  (fixture autouse: DNS finto con host pubblici)
)


@pytest.fixture
def config() -> DocumentsConfig:
    return load_documents_config()


# --- SSRF ---


def redirecting_client(location: str, requests: list[str] | None = None) -> httpx.Client:
    """Client il cui primo link reindirizza a `location`; registra gli URL richiesti."""

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(str(request.url))
        if request.url.host == "ente.example.invalid":
            return httpx.Response(302, headers={"location": location})
        return pdf_handler(request)

    return make_client(handler)


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/a.pdf",
        "http://localhost/a.pdf",
        "http://app.localhost/a.pdf",
        "http://[::1]/a.pdf",
        "http://[::ffff:127.0.0.1]/a.pdf",
        "http://169.254.169.254/latest/meta-data/a.pdf",
        "https://10.0.0.5/a.pdf",
        "https://192.168.1.10/a.pdf",
        "https://172.16.0.1/a.pdf",
        "http://0.0.0.0/a.pdf",
        "http://224.0.0.1/a.pdf",
        "file:///etc/passwd",
        "ftp://ente.example.invalid/a.pdf",
        "javascript:alert(1)",
    ],
)
def test_redirect_to_internal_or_unsupported_target_is_rejected(
    tmp_path: Path, location: str
) -> None:
    requests: list[str] = []
    client = redirecting_client(location, requests)
    # httpx rifiuta da solo alcune destinazioni malformate (InvalidURL): comunque errore permanente
    with pytest.raises(DocumentDownloadError) as excinfo:
        download_document(client, "https://ente.example.invalid/a.pdf", tmp_path / "a.pdf", MB)
    assert excinfo.value.temporary is False
    assert requests == ["https://ente.example.invalid/a.pdf"]  # il bersaglio non è mai richiesto
    assert not (tmp_path / "a.pdf").exists()


@pytest.mark.parametrize("ips", [["10.1.2.3"], ["127.0.0.1"], [PUBLIC_IP, "192.168.0.7"], ["::1"]])
def test_host_resolving_to_non_public_address_is_rejected(tmp_path: Path, ips: list[str]) -> None:
    DNS["intranet.example.invalid"] = ips
    requests: list[str] = []
    client = redirecting_client("https://intranet.example.invalid/a.pdf", requests)
    with pytest.raises(UnsafeUrlError, match="non pubblico"):
        download_document(client, "https://ente.example.invalid/a.pdf", tmp_path / "a.pdf", MB)
    assert len(requests) == 1


def test_first_url_is_checked_too(tmp_path: Path) -> None:
    with pytest.raises(UnsafeUrlError):
        download_document(
            make_client(forbidden_handler), "http://127.0.0.1/a.pdf", tmp_path / "a.pdf", MB
        )


def test_public_redirect_is_followed_including_relative_location(tmp_path: Path) -> None:
    DNS["cdn.example.invalid"] = ["151.101.1.1"]
    requests: list[str] = []
    client = redirecting_client("https://cdn.example.invalid/files/a.pdf", requests)
    destination = tmp_path / "a.pdf"
    download_document(client, "https://ente.example.invalid/a.pdf", destination, MB)
    assert destination.read_bytes() == PDF_BYTES
    assert requests[-1] == "https://cdn.example.invalid/files/a.pdf"

    def relative(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start.pdf":
            return httpx.Response(301, headers={"location": "/files/real.pdf"})
        return pdf_handler(request)

    other = tmp_path / "b.pdf"
    download_document(make_client(relative), "https://ente.example.invalid/start.pdf", other, MB)
    assert other.read_bytes() == PDF_BYTES


def test_injected_client_that_follows_redirects_is_still_checked_hop_by_hop(
    tmp_path: Path,
) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(307, headers={"location": "http://127.0.0.1/secret.pdf"})

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with pytest.raises(UnsafeUrlError):
        download_document(client, PDF_URL, tmp_path / "a.pdf", MB)
    assert requests == [PDF_URL]


def test_too_many_redirects_is_a_permanent_error(tmp_path: Path) -> None:
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        target = f"https://ente.example.invalid/{counter['n']}.pdf"
        return httpx.Response(302, headers={"location": target})

    with pytest.raises(DocumentDownloadError, match="Troppi reindirizzamenti") as excinfo:
        download_document(make_client(handler), PDF_URL, tmp_path / "a.pdf", MB, max_redirects=3)
    assert excinfo.value.temporary is False
    assert counter["n"] == 4  # richiesta iniziale + 3 salti

    counter["n"] = 0
    with pytest.raises(DocumentDownloadError, match="Troppi"):
        download_document(make_client(handler), PDF_URL, tmp_path / "b.pdf", MB, max_redirects=0)
    assert counter["n"] == 1


def test_redirect_without_location_is_a_permanent_error(tmp_path: Path) -> None:
    client = make_client(lambda request: httpx.Response(302))
    with pytest.raises(DocumentDownloadError, match="senza destinazione") as excinfo:
        download_document(client, PDF_URL, tmp_path / "a.pdf", MB)
    assert excinfo.value.temporary is False


def test_unresolvable_host_is_a_temporary_error(tmp_path: Path) -> None:
    def failing(host: str, port: int, *args: object, **kwargs: object) -> list[tuple]:
        raise socket.gaierror(socket.EAI_NONAME, "nome sconosciuto")

    with pytest.raises(DocumentDownloadError, match="risolvere") as excinfo:
        download_document(
            make_client(forbidden_handler), PDF_URL, tmp_path / "a.pdf", MB, resolver=failing
        )
    assert excinfo.value.temporary is True
    assert not isinstance(excinfo.value, UnsafeUrlError)


def test_resolver_is_injectable(tmp_path: Path) -> None:
    seen: list[str] = []

    def resolver(host: str, port: int, *args: object, **kwargs: object) -> list[tuple]:
        seen.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", port))]

    with pytest.raises(UnsafeUrlError):
        download_document(
            make_client(forbidden_handler), PDF_URL, tmp_path / "a.pdf", MB, resolver=resolver
        )
    assert seen == ["ente.example.invalid"]


def test_unsafe_redirect_in_process_marks_document_not_accessible(
    session: Session, tmp_path: Path, config: DocumentsConfig
) -> None:
    requests: list[str] = []
    client = redirecting_client("http://127.0.0.1:8000/admin.pdf", requests)
    tender = add_tender(session, url="https://ente.example.invalid/Atti.pdf")
    docs = process_tender_documents(session, tender, client, config=config, documents_dir=tmp_path)
    assert docs[0].status == DocumentStatus.NOT_ACCESSIBLE  # permanente: non si riprova
    assert requests == ["https://ente.example.invalid/Atti.pdf"]


# --- Classificazione degli errori di httpx ---


@pytest.mark.parametrize(
    ("error", "temporary"),
    [
        (httpx.InvalidURL("URL non valido"), False),
        (httpx.UnsupportedProtocol("protocollo non supportato"), False),
        (httpx.TooManyRedirects("troppi reindirizzamenti"), False),
        (httpx.DecodingError("gzip rotto"), False),
        (httpx.ReadTimeout("lettura lenta"), True),
        (httpx.ConnectTimeout("connessione lenta"), True),
        (httpx.ConnectError("rete assente"), True),
        (httpx.ReadError("connessione interrotta"), True),
        (httpx.RemoteProtocolError("risposta malformata"), True),
    ],
    ids=lambda v: type(v).__name__ if isinstance(v, Exception) else str(v),
)
def test_httpx_errors_are_classified(tmp_path: Path, error: Exception, temporary: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(DocumentDownloadError) as excinfo:
        download_document(make_client(handler), PDF_URL, tmp_path / "a.pdf", MB)
    assert excinfo.value.temporary is temporary
    assert not (tmp_path / "a.pdf.part").exists()


def test_invalid_url_does_not_stop_the_job(
    session: Session, tmp_path: Path, config: DocumentsConfig
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.InvalidURL("URL non valido")

    tender = add_tender(session)
    docs = process_tender_documents(
        session, tender, make_client(handler), config=config, documents_dir=tmp_path
    )
    assert docs[0].status == DocumentStatus.NOT_ACCESSIBLE


def test_gzip_body_is_limited_after_decompression(tmp_path: Path) -> None:
    payload = gzip.compress(b"%PDF-" + b"0" * 200_000)  # piccolo compresso, grande decompresso

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=payload, headers={"content-encoding": "gzip", "content-length": "50"}
        )

    destination = tmp_path / "a.pdf"
    with pytest.raises(DocumentTooLargeError):
        download_document(make_client(handler), PDF_URL, destination, 10_000)
    assert not destination.exists()
    assert download_document(make_client(handler), PDF_URL, destination, 1_000_000) > 200_000


# --- Tempo complessivo ---


def test_total_timeout_is_a_temporary_error(tmp_path: Path) -> None:
    ticks = iter(range(0, 10_000, 100))  # ogni lettura dell'orologio avanza di 100 s

    def clock() -> float:
        return float(next(ticks))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-" + b"x" * 10)

    destination = tmp_path / "a.pdf"
    with pytest.raises(DocumentDownloadError, match="Tempo massimo") as excinfo:
        download_document(
            make_client(handler), PDF_URL, destination, MB, total_timeout=150, clock=clock
        )
    assert excinfo.value.temporary is True
    assert not destination.exists() and not list(tmp_path.glob("*.part"))


def test_total_timeout_not_exceeded_downloads_normally(tmp_path: Path) -> None:
    destination = tmp_path / "a.pdf"
    download_document(
        make_client(pdf_handler), PDF_URL, destination, MB, total_timeout=10, clock=lambda: 0.0
    )
    assert destination.exists()


def test_timeout_in_process_leaves_document_pending(
    session: Session, tmp_path: Path, config: DocumentsConfig
) -> None:
    ticks = iter(range(0, 100_000, 1000))
    tender = add_tender(session)
    docs = process_tender_documents(
        session,
        tender,
        make_client(pdf_handler),
        config=config,
        documents_dir=tmp_path,
        clock=lambda: float(next(ticks)),
    )
    assert docs[0].status == DocumentStatus.PENDING


# --- Nomi di file ---


def test_truncate_filename_keeps_extension() -> None:
    result = truncate_filename("a" * 300 + ".pdf")
    assert len(result) == 200 and result.endswith(".pdf")
    assert truncate_filename("breve.pdf") == "breve.pdf"
    assert len(truncate_filename("b" * 300)) == 200
    assert len(truncate_filename("c" * 300 + "." + "d" * 50)) == 200


def test_long_file_name_is_truncated_and_downloaded(
    session: Session, tmp_path: Path, config: DocumentsConfig
) -> None:
    tender = add_tender(session, url="https://ente.example.invalid/" + "x" * 400 + ".pdf")
    doc = process_tender_documents(
        session, tender, make_client(pdf_handler), config=config, documents_dir=tmp_path
    )[0]
    assert doc.status == DocumentStatus.DOWNLOADED
    assert len(doc.name) <= 200 and doc.name.endswith(".pdf")
    assert len(Path(doc.local_path or "").name) <= 200


def test_files_of_documents_with_the_same_name_do_not_collide(
    session: Session, tmp_path: Path
) -> None:
    tender = add_tender(session)
    first = Document(tender=tender, name="Bando.pdf", url="https://a.example.invalid/Bando.pdf")
    second = Document(tender=tender, name="Bando.pdf", url="https://b.example.invalid/Bando.pdf")
    session.add_all([first, second])
    session.flush()
    path_a = document_file_path(first, tender, tmp_path)
    path_b = document_file_path(second, tender, tmp_path)
    assert path_a != path_b
    assert path_a.parent == path_b.parent == tmp_path / "000001-2026"


# --- Errori di archiviazione ---


@pytest.mark.parametrize(
    ("error", "temporary"),
    [
        (OSError(errno.ENOSPC, "Disco pieno"), True),
        (PermissionError(errno.EACCES, "Permesso negato"), True),
        (OSError(errno.EIO, "Errore di I/O"), False),
    ],
)
def test_storage_errors_are_classified_and_logged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: OSError,
    temporary: bool,
) -> None:
    def failing(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(documents_module, "_save_response", failing)
    with caplog.at_level(logging.ERROR, logger="backend.domain.documents"):
        with pytest.raises(DocumentDownloadError) as excinfo:
            download_document(make_client(pdf_handler), PDF_URL, tmp_path / "a.pdf", MB)
    assert excinfo.value.temporary is temporary
    assert "Errore di archiviazione" in caplog.text


def test_disk_full_leaves_document_pending_in_process(
    session: Session,
    tmp_path: Path,
    config: DocumentsConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing(*args: object, **kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "Disco pieno")

    monkeypatch.setattr(documents_module, "_save_response", failing)
    tender = add_tender(session)
    docs = process_tender_documents(
        session, tender, make_client(pdf_handler), config=config, documents_dir=tmp_path
    )
    assert docs[0].status == DocumentStatus.PENDING


# --- Contenuto del file ---


def test_content_that_is_not_a_pdf_is_rejected(tmp_path: Path) -> None:
    client = make_client(lambda request: httpx.Response(200, content=b"<html>Accedi</html>"))
    destination = tmp_path / "a.pdf"
    with pytest.raises(DocumentDownloadError, match="non è un file PDF") as excinfo:
        download_document(client, PDF_URL, destination, MB)
    assert excinfo.value.temporary is False
    assert not destination.exists() and not list(tmp_path.glob("*.part"))


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    client = make_client(lambda request: httpx.Response(200, content=b""))
    with pytest.raises(DocumentDownloadError, match="non è un file PDF"):
        download_document(client, PDF_URL, tmp_path / "a.pdf", MB)


def test_zip_signature_is_checked(tmp_path: Path) -> None:
    ok = make_client(lambda request: httpx.Response(200, content=b"PK\x03\x04resto"))
    download_document(ok, PDF_URL, tmp_path / "a.zip", MB)
    bad = make_client(lambda request: httpx.Response(200, content=b"%PDF-1.7"))
    with pytest.raises(DocumentDownloadError, match="ZIP"):
        download_document(bad, PDF_URL, tmp_path / "b.zip", MB)


def test_xhtml_page_is_rejected(tmp_path: Path) -> None:
    client = make_client(
        lambda request: httpx.Response(
            200, content=b"%PDF-", headers={"content-type": "application/xhtml+xml"}
        )
    )
    with pytest.raises(DocumentDownloadError, match="pagina web"):
        download_document(client, PDF_URL, tmp_path / "a.pdf", MB)


# --- Riscaricare un file sparito ---


def test_downloaded_document_whose_file_disappeared_is_downloaded_again(
    session: Session, tmp_path: Path, config: DocumentsConfig
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return pdf_handler(request)

    tender = add_tender(session)
    client = make_client(handler)
    doc = process_tender_documents(session, tender, client, config=config, documents_dir=tmp_path)[
        0
    ]
    path = Path(doc.local_path or "")
    path.unlink()
    docs = process_tender_documents(session, tender, client, config=config, documents_dir=tmp_path)
    assert len(calls) == 2 and len(docs) == 1
    assert docs[0].status == DocumentStatus.DOWNLOADED and path.read_bytes() == PDF_BYTES
    process_tender_documents(session, tender, client, config=config, documents_dir=tmp_path)
    assert len(calls) == 2  # il file c'è: nessun nuovo download
