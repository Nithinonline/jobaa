"""File parsing utilities for extracting text from various formats."""

from __future__ import annotations

import re
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pdfplumber
from docx import Document as DocxDocument


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = True
        if tag in {"p", "br", "li", "div", "h1", "h2", "h3", "tr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False
        if tag in {"p", "li", "div"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and data:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def strip_html_to_text(raw: str) -> str:
    """Best-effort strip of LinkedIn/HTML-ish JD paste into plain text."""
    if not raw:
        return ""
    # Quick detect: if no tags, return as-is (still normalize whitespace a bit)
    if "<" not in raw or ">" not in raw:
        return raw.strip()
    parser = _HTMLTextExtractor()
    try:
        parser.feed(raw)
        parser.close()
        text = parser.text()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
    # Drop common LinkedIn chrome phrases
    noise = [
        r"Show more",
        r"Show less",
        r"Follow",
        r"Easy Apply",
        r"\d+\s+people clicked apply",
    ]
    for pattern in noise:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text.strip()


def parse_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF file bytes."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
        tmp_file.write(file_bytes)
        tmp_path = tmp_file.name

    try:
        text_parts = []
        with pdfplumber.open(tmp_path) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)
    finally:
        Path(tmp_path).unlink()


def parse_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX file bytes."""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_file:
        tmp_file.write(file_bytes)
        tmp_path = tmp_file.name

    try:
        doc = DocxDocument(tmp_path)
        return "\n".join(paragraph.text for paragraph in doc.paragraphs)
    finally:
        Path(tmp_path).unlink()


def parse_txt(file_bytes: bytes) -> str:
    """Decode text file bytes; strip HTML if present."""
    text = file_bytes.decode("utf-8", errors="replace")
    return strip_html_to_text(text)


def parse_uploaded_file(uploaded_file) -> str:
    """
    Parse uploaded file and extract text.

    Args:
        uploaded_file: Streamlit UploadedFile object

    Returns:
        Extracted text from the file
    """
    file_bytes = uploaded_file.read()
    file_name = uploaded_file.name.lower()

    if file_name.endswith(".pdf"):
        return parse_pdf(file_bytes)
    if file_name.endswith(".docx"):
        return parse_docx(file_bytes)
    if file_name.endswith((".txt", ".html", ".htm")):
        return parse_txt(file_bytes)
    raise ValueError(f"Unsupported file type: {file_name}")
