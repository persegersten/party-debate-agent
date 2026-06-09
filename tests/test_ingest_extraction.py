import pytest

from ingest import ingest_party_sources


def test_extract_html_uses_trafilatura(monkeypatch) -> None:
    def fake_extract(
        html: str,
        url: str,
        include_comments: bool,
        include_tables: bool,
        output_format: str,
        favor_recall: bool,
    ) -> str:
        assert "html" in html
        assert url == "https://example.com"
        assert include_comments is False
        assert include_tables is False
        assert output_format == "txt"
        assert favor_recall is True
        return "Extraherad text"

    monkeypatch.setattr(ingest_party_sources.trafilatura, "extract", fake_extract)

    assert ingest_party_sources.extract_html(b"<html>Hej</html>", "https://example.com") == "Extraherad text"


def test_extract_html_accepts_str_input(monkeypatch) -> None:
    def fake_extract(html: str, **_kwargs) -> str:
        assert html == "<html>ÅÄÖ</html>"
        return "ÅÄÖ"

    monkeypatch.setattr(ingest_party_sources.trafilatura, "extract", fake_extract)

    assert ingest_party_sources.extract_html("<html>ÅÄÖ</html>", "https://example.com") == "ÅÄÖ"


def test_extract_html_bytes_input_decodes_with_replace(monkeypatch) -> None:
    def fake_extract(html: str, **_kwargs) -> str:
        assert "�" in html
        return "Text från trasig byte-sekvens"

    monkeypatch.setattr(ingest_party_sources.trafilatura, "extract", fake_extract)

    assert ingest_party_sources.extract_html(b"<html>\xff</html>", "https://example.com") == "Text från trasig byte-sekvens"


def test_extract_html_fallback_when_trafilatura_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(ingest_party_sources.trafilatura, "extract", lambda *_args, **_kwargs: None)

    html = """
    <html>
      <header>Sidhuvud</header>
      <nav>Meny</nav>
      <main><h1>Klimatpolitik</h1><p>Vi vill sänka utsläppen.</p></main>
      <footer>Sidfot</footer>
      <script>alert("x")</script>
    </html>
    """.encode("utf-8")

    text = ingest_party_sources.extract_html(html, "https://example.com")

    assert "Klimatpolitik" in text
    assert "Vi vill sänka utsläppen." in text
    assert "Meny" not in text
    assert "alert" not in text


def test_extract_html_fallback_when_trafilatura_raises(monkeypatch) -> None:
    def raising_extract(*_args, **_kwargs) -> str:
        raise RuntimeError("parserfel")

    monkeypatch.setattr(ingest_party_sources.trafilatura, "extract", raising_extract)

    html = "<html><body><article><p>Partiets politik i korthet.</p></article></body></html>"

    assert ingest_party_sources.extract_html(html, "https://example.com") == "Partiets politik i korthet."


def test_extract_html_empty_html_raises_clear_error(monkeypatch) -> None:
    monkeypatch.setattr(ingest_party_sources.trafilatura, "extract", lambda *_args, **_kwargs: "")

    with pytest.raises(ValueError, match="https://example.com/tom"):
        ingest_party_sources.extract_html("<html><script>ignored</script></html>", "https://example.com/tom")


def test_extract_pdf_reads_pages(monkeypatch) -> None:
    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    class FakeReader:
        def __init__(self, _buffer) -> None:
            self.pages = [FakePage("Sida ett"), FakePage("Sida två")]

    monkeypatch.setattr(ingest_party_sources, "PdfReader", FakeReader)

    assert ingest_party_sources.extract_pdf(b"%PDF") == "Sida ett\n\nSida två"
