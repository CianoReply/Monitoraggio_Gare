"""Rafforzamenti del download dei documenti: NAT64, log senza query string, trust_env, ordine."""

import logging
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session

from backend.domain import documents as documents_module
from backend.domain.config import DocumentsConfig, load_documents_config
from backend.domain.documents import (
    DocumentDownloadError,
    UnsafeUrlError,
    download_document,
    process_tender_documents,
    safe_url,
)
from backend.domain.models import Document, DocumentStatus, Tender
from backend.tests.domain.test_documents import (
    DNS,
    MB,
    PDF_BYTES,
    add_tender,
    forbidden_handler,
    make_client,
    pdf_handler,
    public_dns,  # noqa: F401  (fixture autouse: DNS finto)
)

SECRET_URL = "https://ente.example.invalid/atti/Bando.pdf?token=SEGRETO&utente=mario#parte"


@pytest.fixture
def config() -> DocumentsConfig:
    return load_documents_config()


# --- NAT64 ---


@pytest.mark.parametrize(
    "url",
    [
        "http://[64:ff9b::7f00:1]/a.pdf",  # 127.0.0.1 via NAT64
        "http://[64:ff9b::a00:1]/a.pdf",  # 10.0.0.1
        "http://[64:ff9b::808:808]/a.pdf",  # anche un IPv4 pubblico: tutta la rete è bloccata
    ],
)
def test_nat64_literals_are_rejected(tmp_path: Path, url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        download_document(make_client(forbidden_handler), url, tmp_path / "a.pdf", MB)


def test_host_resolving_to_nat64_is_rejected(tmp_path: Path) -> None:
    DNS["nat64.example.invalid"] = ["64:ff9b::a00:1"]
    with pytest.raises(UnsafeUrlError, match="non pubblico"):
        download_document(
            make_client(forbidden_handler),
            "https://nat64.example.invalid/a.pdf",
            tmp_path / "a",
            MB,
        )


def test_public_ipv6_is_still_allowed(tmp_path: Path) -> None:
    DNS["v6.example.invalid"] = ["2606:2800:220:1:248:1893:25c8:1946"]
    destination = tmp_path / "a.pdf"
    download_document(make_client(pdf_handler), "https://v6.example.invalid/a.pdf", destination, MB)
    assert destination.read_bytes() == PDF_BYTES


# --- URL nei log e nei messaggi ---


def test_safe_url_drops_credentials_query_and_fragment() -> None:
    assert safe_url(SECRET_URL) == "https://ente.example.invalid/atti/Bando.pdf"
    assert safe_url("http://utente:password@host.example.invalid:8080/a/b.zip?x=1") == (
        "http://host.example.invalid:8080/a/b.zip"
    )
    assert safe_url("non un url") == "(indirizzo non valido)"
    assert safe_url("http://[::1") == "(indirizzo non valido)"
    assert safe_url("") == "(indirizzo non valido)"


def test_logs_and_errors_never_contain_the_query_string(
    session: Session, tmp_path: Path, config: DocumentsConfig, caplog: pytest.LogCaptureFixture
) -> None:
    client = make_client(lambda request: httpx.Response(404))
    tender = add_tender(session, url=SECRET_URL)
    with caplog.at_level(logging.DEBUG, logger="backend.domain.documents"):
        docs = process_tender_documents(
            session, tender, client, config=config, documents_dir=tmp_path
        )
    assert docs[0].status == DocumentStatus.NOT_ACCESSIBLE
    assert "Bando.pdf" in caplog.text and "404" in caplog.text
    assert "SEGRETO" not in caplog.text and "token" not in caplog.text
    assert "mario" not in caplog.text


@pytest.mark.parametrize(
    "handler_error",
    [httpx.ConnectError("rete"), httpx.ReadTimeout("lenta")],
)
def test_error_messages_do_not_include_the_query_string(
    tmp_path: Path, handler_error: Exception
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise handler_error

    with pytest.raises(DocumentDownloadError) as excinfo:
        download_document(make_client(handler), SECRET_URL, tmp_path / "a.pdf", MB)
    assert "SEGRETO" not in str(excinfo.value)


def test_error_messages_for_html_redirect_and_status_hide_the_query(tmp_path: Path) -> None:
    html = make_client(
        lambda request: httpx.Response(200, content=b"x", headers={"content-type": "text/html"})
    )
    with pytest.raises(DocumentDownloadError) as html_error:
        download_document(html, SECRET_URL, tmp_path / "a.pdf", MB)
    no_location = make_client(lambda request: httpx.Response(302))
    with pytest.raises(DocumentDownloadError) as redirect_error:
        download_document(no_location, SECRET_URL, tmp_path / "b.pdf", MB)
    not_found = make_client(lambda request: httpx.Response(404))
    with pytest.raises(DocumentDownloadError) as status_error:
        download_document(not_found, SECRET_URL, tmp_path / "c.pdf", MB)
    loop = make_client(lambda request: httpx.Response(302, headers={"location": SECRET_URL}))
    with pytest.raises(DocumentDownloadError) as loop_error:
        download_document(loop, SECRET_URL, tmp_path / "d.pdf", MB, max_redirects=1)
    for error in (html_error, redirect_error, status_error, loop_error):
        assert "SEGRETO" not in str(error.value)
    with pytest.raises(UnsafeUrlError) as scheme_error:
        download_document(
            make_client(forbidden_handler),
            "ftp://h.example.invalid/a?k=SEGRETO",
            tmp_path / "e",
            MB,
        )
    assert "SEGRETO" not in str(scheme_error.value)


# --- Client creato dal dominio ---


def test_default_client_ignores_proxy_and_certificates_from_the_environment(
    session: Session, tmp_path: Path, config: DocumentsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    real_client = httpx.Client

    def fake_client(**kwargs: object) -> httpx.Client:
        captured.update(kwargs)
        return real_client(transport=httpx.MockTransport(pdf_handler))

    monkeypatch.setattr(documents_module.httpx, "Client", fake_client)
    tender = add_tender(session)
    process_tender_documents(session, tender, config=config, documents_dir=tmp_path)
    assert captured["trust_env"] is False
    assert captured["follow_redirects"] is False


# --- Ordine dei documenti ---


def test_tender_documents_are_ordered_by_id(session: Session) -> None:
    tender = add_tender(session)
    session.add_all(
        [
            Document(id=7, tender=tender, name="c.pdf", url="https://c.example.invalid/c.pdf"),
            Document(id=2, tender=tender, name="a.pdf", url="https://a.example.invalid/a.pdf"),
            Document(id=5, tender=tender, name="b.pdf", url="https://b.example.invalid/b.pdf"),
        ]
    )
    session.flush()
    session.expire_all()
    reloaded = session.get(Tender, tender.id)
    assert reloaded is not None
    assert [d.id for d in reloaded.documents] == [2, 5, 7]
