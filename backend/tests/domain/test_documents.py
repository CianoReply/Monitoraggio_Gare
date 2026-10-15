"""Test dei documenti di gara (T2.4): nessuna rete, solo httpx.MockTransport e tmp_path."""

import logging
import socket
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain import documents as documents_module
from backend.domain.config import (
    ConfigError,
    DocumentsConfig,
    load_documents_config,
)
from backend.domain.documents import (
    MISSING_LINK_DOCUMENT_NAME,
    PLATFORM_DOCUMENT_NAME,
    DocumentDownloadError,
    DocumentTooLargeError,
    LinkKind,
    classify_link,
    document_name_from_url,
    download_document,
    get_documents_dir,
    process_tender_documents,
    tender_documents_dir,
)
from backend.domain.models import Document, DocumentStatus, Tender
from backend.domain.repository import upsert_tender
from backend.domain.schemas import TenderEvaluation
from backend.tests.domain.conftest import make_tender

PDF_URL = "https://ente.example.invalid/gara/Disciplinare.pdf"
PLATFORM_URL = "https://pizzo.example.invalid/gare/dettaglio.php?codice=249"
PDF_BYTES = b"%PDF-1.7 contenuto di prova"
MB = 1024 * 1024


PUBLIC_IP = "93.184.216.34"
DNS: dict[str, list[str]] = {}


def fake_getaddrinfo(host: str, port: int, *args: object, **kwargs: object) -> list[tuple]:
    """DNS finto: ogni host è pubblico salvo quelli elencati in `DNS`."""
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in DNS.get(host, [PUBLIC_IP])
    ]


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    DNS.clear()
    monkeypatch.setattr(documents_module.socket, "getaddrinfo", fake_getaddrinfo)
    yield
    DNS.clear()


@pytest.fixture
def config() -> DocumentsConfig:
    return load_documents_config()


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def pdf_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=PDF_BYTES, headers={"content-type": "application/pdf"})


def forbidden_handler(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"nessuna richiesta di rete attesa, ricevuta {request.url}")


def add_tender(
    session: Session,
    *,
    relevant: bool = True,
    url: str | None = PDF_URL,
    number: str = "000001-2026",
) -> Tender:
    tender, _ = upsert_tender(
        session,
        make_tender(publication_number=number, documents_url=url),
        TenderEvaluation(4 if relevant else 1, relevant),
    )
    return tender


# --- Classificazione del link ---


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("https://x.example.invalid/a/Disciplinare.pdf", LinkKind.DIRECT_FILE),
        ("https://x.example.invalid/a/BANDO.PDF", LinkKind.DIRECT_FILE),
        ("http://x.example.invalid/a/atti.zip?download=1", LinkKind.DIRECT_FILE),
        ("https://pizzo.example.invalid/gare/dettaglio.php?codice=249", LinkKind.PLATFORM),
        ("https://x.example.invalid/download?file=a.pdf", LinkKind.PLATFORM),
        ("https://x.example.invalid/", LinkKind.PLATFORM),
        (None, LinkKind.MISSING),
        ("", LinkKind.MISSING),
        ("   ", LinkKind.MISSING),
        ("ftp://x.example.invalid/a.pdf", LinkKind.MISSING),
        ("non è un url", LinkKind.MISSING),
        ("file:///etc/passwd.pdf", LinkKind.MISSING),
    ],
)
def test_classify_link(config: DocumentsConfig, url: str | None, kind: LinkKind) -> None:
    assert classify_link(url, config) == kind


def test_document_name_is_safe() -> None:
    assert document_name_from_url(PDF_URL) == "Disciplinare.pdf"
    assert document_name_from_url("https://x.example.invalid/..%2F..%2Fevil.pdf") == "evil.pdf"
    assert document_name_from_url("https://x.example.invalid/a%20b%3F.pdf") == "a b_.pdf"
    assert document_name_from_url("https://x.example.invalid/") == "documento"


def test_tender_documents_dir_is_inside_root(tmp_path: Path) -> None:
    assert tender_documents_dir("707611-2026", tmp_path) == tmp_path / "707611-2026"
    assert tender_documents_dir("../../x", tmp_path).parent == tmp_path


def test_documents_dir_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCUMENTS_DIR", str(tmp_path))
    assert get_documents_dir() == tmp_path
    monkeypatch.setenv("DOCUMENTS_DIR", "  ")
    assert get_documents_dir() == Path("/data/documents")
    monkeypatch.delenv("DOCUMENTS_DIR")
    assert get_documents_dir() == Path("/data/documents")


# --- Download ---


def test_download_saves_file(tmp_path: Path) -> None:
    destination = tmp_path / "gara" / "a.pdf"
    written = download_document(make_client(pdf_handler), PDF_URL, destination, 50 * MB)
    assert written == len(PDF_BYTES)
    assert destination.read_bytes() == PDF_BYTES
    assert not list(tmp_path.rglob("*.part"))


def test_download_follows_redirects(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old.pdf":
            return httpx.Response(302, headers={"location": "https://ente.example.invalid/new.pdf"})
        return pdf_handler(request)

    destination = tmp_path / "a.pdf"
    download_document(make_client(handler), "https://ente.example.invalid/old.pdf", destination, MB)
    assert destination.read_bytes() == PDF_BYTES


def test_download_rejects_file_over_limit_declared_in_content_length(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x", headers={"content-length": str(51 * MB)})

    destination = tmp_path / "a.pdf"
    with pytest.raises(DocumentTooLargeError, match=r"troppo grande: 51\.0 MB \(massimo 50 MB\)"):
        download_document(make_client(handler), PDF_URL, destination, 50 * MB)
    assert not destination.exists()
    assert not list(tmp_path.rglob("*.part"))


def test_download_rejects_file_over_limit_counted_while_streaming(tmp_path: Path) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(10):  # nessun Content-Length: 10 x 1 KB = 10 KB
            yield b"x" * 1024

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=chunks())

    destination = tmp_path / "a.pdf"
    with pytest.raises(DocumentTooLargeError, match="troppo grande"):
        download_document(make_client(handler), PDF_URL, destination, 5 * 1024)
    assert not destination.exists()
    assert not list(tmp_path.rglob("*.part"))


def test_download_accepts_file_exactly_at_limit(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1000)

    destination = tmp_path / "a.bin"
    assert download_document(make_client(handler), PDF_URL, destination, 1000) == 1000
    with pytest.raises(DocumentTooLargeError):
        download_document(make_client(handler), PDF_URL, tmp_path / "b.bin", 999)


@pytest.mark.parametrize(
    ("status", "temporary"),
    [
        (404, False),
        (403, False),
        (410, False),
        (204, False),
        (304, False),
        (408, True),
        (429, True),
        (500, True),
        (503, True),
    ],
)
def test_download_http_errors(tmp_path: Path, status: int, temporary: bool) -> None:
    client = make_client(lambda request: httpx.Response(status))
    with pytest.raises(DocumentDownloadError) as excinfo:
        download_document(client, PDF_URL, tmp_path / "a.pdf", MB)
    assert excinfo.value.temporary is temporary
    assert str(status) in str(excinfo.value)
    assert not isinstance(excinfo.value, DocumentTooLargeError)


def test_download_network_error_is_temporary(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("rete non raggiungibile", request=request)

    with pytest.raises(DocumentDownloadError) as excinfo:
        download_document(make_client(handler), PDF_URL, tmp_path / "a.pdf", MB)
    assert excinfo.value.temporary is True


def test_download_rejects_html_page_instead_of_file(tmp_path: Path) -> None:
    client = make_client(
        lambda request: httpx.Response(
            200, content=b"<html>login</html>", headers={"content-type": "text/html; charset=utf-8"}
        )
    )
    with pytest.raises(DocumentDownloadError, match="pagina web") as excinfo:
        download_document(client, PDF_URL, tmp_path / "a.pdf", MB)
    assert excinfo.value.temporary is False


def test_download_cannot_write_is_permanent_error(tmp_path: Path) -> None:
    blocker = tmp_path / "occupato"
    blocker.write_text("file, non cartella", encoding="utf-8")
    with pytest.raises(DocumentDownloadError, match="Impossibile salvare"):
        download_document(make_client(pdf_handler), PDF_URL, blocker / "a.pdf", MB)


# --- process_tender_documents ---


def test_not_relevant_tender_gets_no_documents_and_no_download(
    session: Session, tmp_path: Path, config: DocumentsConfig
) -> None:
    tender = add_tender(session, relevant=False)
    result = process_tender_documents(
        session, tender, make_client(forbidden_handler), config=config, documents_dir=tmp_path
    )
    assert result == []
    assert session.scalars(select(Document)).all() == []
    assert not any(tmp_path.iterdir())


def test_direct_pdf_is_downloaded_and_saved(
    session: Session, tmp_path: Path, config: DocumentsConfig
) -> None:
    tender = add_tender(session)
    docs = process_tender_documents(
        session, tender, make_client(pdf_handler), config=config, documents_dir=tmp_path
    )
    assert len(docs) == 1
    doc = docs[0]
    assert (doc.name, doc.url, doc.status) == (
        "Disciplinare.pdf",
        PDF_URL,
        DocumentStatus.DOWNLOADED,
    )
    assert doc.downloaded_at is not None
    assert Path(doc.local_path or "") == tmp_path / "000001-2026" / f"{doc.id}_Disciplinare.pdf"
    assert Path(doc.local_path or "").read_bytes() == PDF_BYTES
    assert doc.id is not None and doc.tender_id == tender.id


def test_platform_link_is_saved_as_not_accessible_without_download(
    session: Session, tmp_path: Path, config: DocumentsConfig
) -> None:
    tender = add_tender(session, url=PLATFORM_URL)
    docs = process_tender_documents(
        session, tender, make_client(forbidden_handler), config=config, documents_dir=tmp_path
    )
    assert [(d.name, d.url, d.status, d.local_path) for d in docs] == [
        (PLATFORM_DOCUMENT_NAME, PLATFORM_URL, DocumentStatus.NOT_ACCESSIBLE, None)
    ]
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize("url", [None, "", "ftp://x.example.invalid/a.pdf"])
def test_missing_link_still_creates_one_row(
    session: Session, tmp_path: Path, config: DocumentsConfig, url: str | None
) -> None:
    tender = add_tender(session, url=url)
    docs = process_tender_documents(
        session, tender, make_client(forbidden_handler), config=config, documents_dir=tmp_path
    )
    assert [(d.name, d.url, d.status) for d in docs] == [
        (MISSING_LINK_DOCUMENT_NAME, None, DocumentStatus.NOT_ACCESSIBLE)
    ]


def test_every_relevant_tender_has_at_least_one_document(
    session: Session, tmp_path: Path, config: DocumentsConfig
) -> None:
    urls = [PDF_URL, PLATFORM_URL, None, "https://x.example.invalid/atti.zip"]
    tenders = [add_tender(session, url=u, number=f"n{i}") for i, u in enumerate(urls)]
    client = make_client(pdf_handler)
    for tender in tenders:
        process_tender_documents(session, tender, client, config=config, documents_dir=tmp_path)
    for tender in tenders:
        assert len(tender.documents) >= 1


def test_processing_twice_does_not_duplicate_or_redownload(
    session: Session, tmp_path: Path, config: DocumentsConfig
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return pdf_handler(request)

    tender = add_tender(session)
    client = make_client(handler)
    process_tender_documents(session, tender, client, config=config, documents_dir=tmp_path)
    docs = process_tender_documents(session, tender, client, config=config, documents_dir=tmp_path)
    assert len(docs) == 1 and len(calls) == 1
    assert session.query(Document).count() == 1


def test_oversize_file_is_rejected_with_clear_message(
    session: Session, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x", headers={"content-length": str(60 * MB)})

    config = load_documents_config()
    tender = add_tender(session)
    with caplog.at_level(logging.WARNING, logger="backend.domain.documents"):
        docs = process_tender_documents(
            session, tender, make_client(handler), config=config, documents_dir=tmp_path
        )
    assert docs[0].status == DocumentStatus.NOT_ACCESSIBLE
    assert docs[0].local_path is None
    assert "File troppo grande: 60.0 MB (massimo 50 MB)" in caplog.text
    assert not list(tmp_path.rglob("*.pdf"))


def test_permanent_error_is_not_retried_but_temporary_error_is(
    session: Session, tmp_path: Path, config: DocumentsConfig
) -> None:
    state = {"status": 404, "calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["status"] == 200:
            return pdf_handler(request)
        return httpx.Response(state["status"])

    client = make_client(handler)
    tender = add_tender(session)

    docs = process_tender_documents(session, tender, client, config=config, documents_dir=tmp_path)
    assert docs[0].status == DocumentStatus.NOT_ACCESSIBLE
    process_tender_documents(session, tender, client, config=config, documents_dir=tmp_path)
    assert state["calls"] == 1  # 404: non si riprova

    other = add_tender(session, number="000002-2026")
    state.update(status=503, calls=0)
    docs = process_tender_documents(session, other, client, config=config, documents_dir=tmp_path)
    assert docs[0].status == DocumentStatus.PENDING
    state["status"] = 200
    docs = process_tender_documents(session, other, client, config=config, documents_dir=tmp_path)
    assert [d.status for d in docs] == [DocumentStatus.DOWNLOADED]
    assert state["calls"] == 2
    assert session.query(Document).filter_by(tender_id=other.id).count() == 1


def test_default_client_is_created_and_closed(
    session: Session, tmp_path: Path, config: DocumentsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[httpx.Client] = []
    real_client = httpx.Client

    def fake_client(**kwargs: object) -> httpx.Client:
        assert kwargs["follow_redirects"] is False
        assert kwargs["timeout"] == config.request_timeout_seconds
        client = real_client(transport=httpx.MockTransport(pdf_handler))
        created.append(client)
        return client

    monkeypatch.setattr(documents_module.httpx, "Client", fake_client)
    tender = add_tender(session)
    docs = process_tender_documents(session, tender, config=config, documents_dir=tmp_path)
    assert docs[0].status == DocumentStatus.DOWNLOADED
    assert len(created) == 1 and created[0].is_closed


def test_documents_dir_defaults_to_environment(
    session: Session, tmp_path: Path, config: DocumentsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCUMENTS_DIR", str(tmp_path))
    tender = add_tender(session)
    docs = process_tender_documents(session, tender, make_client(pdf_handler), config=config)
    assert Path(docs[0].local_path or "").parent == tmp_path / "000001-2026"


def test_process_uses_default_config_when_not_given(session: Session, tmp_path: Path) -> None:
    tender = add_tender(session, url=PLATFORM_URL)
    docs = process_tender_documents(
        session, tender, make_client(forbidden_handler), documents_dir=tmp_path
    )
    assert docs[0].status == DocumentStatus.NOT_ACCESSIBLE


# --- Configurazione [documents] ---


def test_default_documents_config() -> None:
    config = load_documents_config()
    assert config.direct_file_extensions == (".pdf", ".zip")
    assert config.max_file_bytes == 50 * MB
    assert config.request_timeout_seconds == 30.0
    assert config.total_timeout_seconds == 300.0
    assert config.max_redirects == 5


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(f"[documents]\n{body}\n", encoding="utf-8")
    return path


VALID = "\n".join(
    [
        'direct_file_extensions = [".PDF"]',
        "max_file_mb = 1.5",
        "request_timeout_seconds = 10",
        "total_timeout_seconds = 20",
        "max_redirects = 3",
    ]
)


def test_custom_documents_config(tmp_path: Path) -> None:
    config = load_documents_config(_write(tmp_path, VALID))
    assert config.direct_file_extensions == (".pdf",)
    assert config.max_file_bytes == int(1.5 * MB)
    assert config.request_timeout_seconds == 10.0
    assert (config.total_timeout_seconds, config.max_redirects) == (20.0, 3)


@pytest.mark.parametrize(
    "body",
    [
        VALID.replace('[".PDF"]', '["pdf"]'),
        VALID.replace('[".PDF"]', "[]"),
        VALID.replace('[".PDF"]', '"pdf"'),
        VALID.replace('[".PDF"]', '["."]'),
        VALID.replace("1.5", "0"),
        VALID.replace("1.5", "-1"),
        VALID.replace("1.5", '"tanto"'),
        VALID.replace("= 10", "= 0"),
        VALID.replace("= 10", "= true"),
        VALID.replace("max_file_mb = 1.5\n", ""),
        VALID.replace("request_timeout_seconds = 10", ""),
        VALID.replace("total_timeout_seconds = 20", ""),
        VALID.replace("total_timeout_seconds = 20", "total_timeout_seconds = 0"),
        VALID.replace("max_redirects = 3", ""),
        VALID.replace("max_redirects = 3", "max_redirects = -1"),
        VALID.replace("max_redirects = 3", "max_redirects = 2.5"),
        "",
    ],
)
def test_invalid_documents_config(tmp_path: Path, body: str) -> None:
    path = _write(tmp_path, body)
    with pytest.raises(ConfigError) as excinfo:
        load_documents_config(path)
    assert str(path) in str(excinfo.value)


def test_missing_documents_section(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[filters]\nx = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"\[documents\]"):
        load_documents_config(path)
