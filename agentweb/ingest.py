"""Dependency-light file ingestion for local AgentWeb knowledge sources."""

from __future__ import annotations

import csv
import html
import json
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IngestedDocument:
    path: str
    media_type: str
    text: str
    citation: str
    ok: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class FileIngestor:
    """Parse common local file formats into source-backed text."""

    allowed_extensions = {".pdf", ".txt", ".md", ".markdown", ".html", ".htm", ".csv", ".json", ".docx"}

    def __init__(self, *, max_bytes: int = 10_000_000) -> None:
        self.max_bytes = max_bytes

    def ingest(self, path: str | Path) -> IngestedDocument:
        file_path = Path(path)
        suffix = file_path.suffix.lower()
        if suffix not in self.allowed_extensions:
            return self._error(file_path, "unsupported_file_type")
        if not file_path.exists() or not file_path.is_file():
            return self._error(file_path, "file_not_found")
        if file_path.stat().st_size > self.max_bytes:
            return self._error(file_path, "file_too_large")
        try:
            if suffix in {".txt", ".md", ".markdown"}:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                media_type = "text/markdown" if suffix in {".md", ".markdown"} else "text/plain"
            elif suffix in {".html", ".htm"}:
                text = _html_to_text(file_path.read_text(encoding="utf-8", errors="replace"))
                media_type = "text/html"
            elif suffix == ".csv":
                text = _csv_to_text(file_path)
                media_type = "text/csv"
            elif suffix == ".json":
                text = json.dumps(json.loads(file_path.read_text(encoding="utf-8", errors="replace")), ensure_ascii=False, indent=2, sort_keys=True)
                media_type = "application/json"
            elif suffix == ".docx":
                text = _docx_to_text(file_path)
                media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            elif suffix == ".pdf":
                text = _pdf_to_text(file_path)
                media_type = "application/pdf"
            else:  # pragma: no cover - guarded by extension check
                return self._error(file_path, "unsupported_file_type")
        except Exception as exc:
            return self._error(file_path, "parse_error", detail=str(exc))
        return IngestedDocument(path=str(file_path), media_type=media_type, text=_normalize(text), citation=str(file_path), metadata={"bytes": file_path.stat().st_size})

    def _error(self, path: Path, code: str, *, detail: str = "") -> IngestedDocument:
        return IngestedDocument(path=str(path), media_type="application/octet-stream", text="", citation=str(path), ok=False, error=code, metadata={"detail": detail} if detail else {})


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return html.unescape(raw)


def _csv_to_text(path: Path) -> str:
    rows: list[str] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle)
        for row in reader:
            rows.append(" | ".join(row))
    return "\n".join(rows)


def _docx_to_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        raw = zf.read("word/document.xml").decode("utf-8", errors="replace")
    pieces = re.findall(r"<w:t[^>]*>(.*?)</w:t>", raw, flags=re.DOTALL)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", piece)) for piece in pieces)


def _pdf_to_text(path: Path) -> str:
    """Extract text from PDF files using multiple strategies.

    Strategy 1: pdftotext (poppler-utils) — best quality, fast.
    Strategy 2: pymupdf (import fitz) — good quality, handles complex PDFs.
    Strategy 3: regex-based fallback — minimal extraction from raw bytes.
    """
    # Strategy 1: pdftotext CLI
    pdftotext_exe = shutil.which("pdftotext")
    if pdftotext_exe:
        try:
            proc = subprocess.run(
                [pdftotext_exe, str(path), "-"],
                capture_output=True, text=True, timeout=30, check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except Exception:
            pass

    # Strategy 2: pymupdf
    try:
        import fitz  # type: ignore[import-untyped]

        doc = fitz.open(str(path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        result = "\n\n".join(pages).strip()
        if result:
            return result
    except ImportError:
        pass
    except Exception:
        pass

    # Strategy 3: Regex fallback from raw bytes
    raw = path.read_bytes().decode("latin-1", errors="ignore")
    strings = re.findall(r"\(([^()]{2,})\)", raw)
    return "\n".join(html.unescape(item.replace(r"\)", ")").replace(r"\(", "(")) for item in strings)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
