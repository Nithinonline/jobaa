"""File parsing utilities for extracting text from various formats."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pdfplumber
from docx import Document as DocxDocument


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
    """Decode text file bytes."""
    return file_bytes.decode("utf-8", errors="replace")


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
    elif file_name.endswith(".docx"):
        return parse_docx(file_bytes)
    elif file_name.endswith(".txt"):
        return parse_txt(file_bytes)
    else:
        raise ValueError(f"Unsupported file type: {file_name}")
