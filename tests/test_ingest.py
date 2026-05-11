from __future__ import annotations

import json
import zipfile

from agentweb.ingest import FileIngestor


def test_file_ingestor_parses_txt_markdown_html_csv_json_and_docx(tmp_path):
    (tmp_path / "note.txt").write_text("plain text", encoding="utf-8")
    (tmp_path / "doc.md").write_text("# Title\nmarkdown body", encoding="utf-8")
    (tmp_path / "page.html").write_text("<html><title>T</title><body><h1>Hello</h1><script>bad()</script><p>World</p></body></html>", encoding="utf-8")
    (tmp_path / "data.csv").write_text("name,score\nAda,10\n", encoding="utf-8")
    (tmp_path / "data.json").write_text(json.dumps({"name": "Ada", "score": 10}), encoding="utf-8")
    docx = tmp_path / "word.docx"
    with zipfile.ZipFile(docx, "w") as zf:
        zf.writestr("word/document.xml", "<w:document><w:t>Hello</w:t><w:t>DOCX</w:t></w:document>")

    ingestor = FileIngestor(max_bytes=100_000)
    outputs = {path.name: ingestor.ingest(path) for path in tmp_path.iterdir()}

    assert outputs["note.txt"].text == "plain text"
    assert "markdown body" in outputs["doc.md"].text
    assert "Hello" in outputs["page.html"].text and "bad()" not in outputs["page.html"].text
    assert "Ada" in outputs["data.csv"].text
    assert '"score": 10' in outputs["data.json"].text
    assert "Hello DOCX" in outputs["word.docx"].text
    assert outputs["word.docx"].citation.endswith("word.docx")


def test_file_ingestor_enforces_size_and_supported_extension(tmp_path):
    huge = tmp_path / "huge.txt"
    huge.write_text("x" * 11, encoding="utf-8")
    exe = tmp_path / "bad.exe"
    exe.write_text("nope", encoding="utf-8")
    ingestor = FileIngestor(max_bytes=10)

    assert ingestor.ingest(huge).ok is False
    assert ingestor.ingest(huge).error == "file_too_large"
    assert ingestor.ingest(exe).error == "unsupported_file_type"
