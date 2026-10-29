"""Post-export ATS validation for PDF and DOCX resume files."""

from __future__ import annotations

import re
from io import BytesIO
from typing import Literal

from core.ats_constants import (
    BAD_DATE_PATTERN,
    CANONICAL_SECTIONS,
    DATE_PATTERN,
    KEYWORD_COVERAGE_THRESHOLD,
    MONTH_NAMES,
    PDF_SECTION_SEARCH_TERMS,
    REQUIRED_SECTIONS,
    SINGLE_DATE_PATTERN,
    sections_in_reading_order,
)

FileType = Literal["pdf", "docx"]


def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        import pdfplumber
    except ImportError:
        return ""

    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        return ""


def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        from docx import Document as DocxDocument
    except ImportError:
        return ""

    try:
        doc = DocxDocument(BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception:
        return ""


def docx_contains_tables(file_bytes: bytes) -> bool:
    try:
        import zipfile

        with zipfile.ZipFile(BytesIO(file_bytes)) as zf:
            if "word/document.xml" not in zf.namelist():
                return False
            xml_content = zf.read("word/document.xml").decode("utf-8", errors="ignore")
            return "<w:tbl" in xml_content
    except Exception:
        return False


def _check_headings(text: str) -> list[str]:
    issues: list[str] = []
    lower = text.lower()
    for section in REQUIRED_SECTIONS:
        search_terms = PDF_SECTION_SEARCH_TERMS.get(section, [section.lower()])
        if not any(term in lower for term in search_terms):
            issues.append(f"Missing required section heading: {section}")
    return issues


def _check_reading_order(text: str) -> list[str]:
    if not sections_in_reading_order(text):
        return [
            "Section reading order is incorrect. Expected: "
            + " → ".join(CANONICAL_SECTIONS)
        ]
    return []


def _check_dates(text: str) -> list[str]:
    issues: list[str] = []
    month_indicator = re.compile(
        rf"\b(?:{MONTH_NAMES}|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b",
        re.IGNORECASE,
    )
    for line in text.splitlines():
        if "|" not in line:
            continue
        date_part = line.split("|", 1)[-1].strip()
        if not date_part or not month_indicator.search(date_part):
            continue
        if DATE_PATTERN.search(date_part) or SINGLE_DATE_PATTERN.search(date_part):
            continue
        if BAD_DATE_PATTERN.search(date_part) or re.search(r"\d{4}", date_part):
            issues.append(f"Date not in required format (Month Year - Month Year): {date_part}")
    return issues


def _check_keywords(text: str, expected_keywords: list[str]) -> list[str]:
    if not expected_keywords:
        return []

    lower = text.lower()
    hits = [kw for kw in expected_keywords if kw.lower() in lower]
    coverage = len(hits) / len(expected_keywords)
    if coverage < KEYWORD_COVERAGE_THRESHOLD:
        missing = [kw for kw in expected_keywords if kw.lower() not in lower]
        shown = ", ".join(missing[:8])
        suffix = "..." if len(missing) > 8 else ""
        return [
            f"Only {len(hits)}/{len(expected_keywords)} priority JD keywords found "
            f"(need {int(KEYWORD_COVERAGE_THRESHOLD * 100)}%). Missing: {shown}{suffix}"
        ]
    return []


def validate_exported_resume(
    file_bytes: bytes,
    file_type: FileType,
    expected_keywords: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Validate an exported PDF or DOCX resume for ATS compliance."""
    issues: list[str] = []

    if file_type == "pdf":
        text = extract_text_from_pdf(file_bytes)
    else:
        text = extract_text_from_docx(file_bytes)

    if not text.strip():
        return False, ["Could not extract text from exported file."]

    issues.extend(_check_headings(text))
    issues.extend(_check_reading_order(text))
    issues.extend(_check_dates(text))

    if expected_keywords:
        issues.extend(_check_keywords(text, expected_keywords))

    if file_type == "docx" and docx_contains_tables(file_bytes):
        issues.append("DOCX contains table elements, which are not ATS-friendly.")

    return not issues, issues
