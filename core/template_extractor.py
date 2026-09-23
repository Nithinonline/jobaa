"""Extract visual/structural template config from a master resume."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from core.ats_constants import CANONICAL_SECTIONS, normalize_section_heading
from core.llm_client import llm_client
from core.template_config import TemplateConfig

_DEFAULT_HEADINGS = {
    "Professional Summary": "PROFESSIONAL SUMMARY",
    "Skills": "SKILLS",
    "Work Experience": "EXPERIENCE",
    "Education": "EDUCATION",
    "Certifications": "CERTIFICATIONS",
}

_HEX_COLOR = re.compile(r"#([0-9a-fA-F]{6})")


def _extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def _normalize_section_order(raw_order: list[Any]) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()
    for item in raw_order:
        canonical = normalize_section_heading(str(item))
        if canonical and canonical not in seen:
            order.append(canonical)
            seen.add(canonical)
    for section in CANONICAL_SECTIONS:
        if section not in seen:
            order.append(section)
            seen.add(section)
    return order


def _infer_order_from_text(raw_text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for line in (raw_text or "").splitlines():
        stripped = line.strip().rstrip(":")
        if not stripped or len(stripped) > 60:
            continue
        canonical = normalize_section_heading(stripped)
        if canonical and canonical not in seen:
            found.append(canonical)
            seen.add(canonical)
    for section in CANONICAL_SECTIONS:
        if section not in seen:
            found.append(section)
    return found


def extract_docx_style_hints(file_bytes: bytes) -> dict[str, Any]:
    """Read font/color hints from a DOCX file when available."""
    hints: dict[str, Any] = {}
    try:
        from docx import Document as DocxDocument
        from docx.shared import RGBColor
    except ImportError:
        return hints

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_file:
        tmp_file.write(file_bytes)
        tmp_path = tmp_file.name

    try:
        doc = DocxDocument(tmp_path)
        fonts: list[str] = []
        sizes: list[float] = []
        colors: list[str] = []
        for paragraph in doc.paragraphs[:80]:
            for run in paragraph.runs:
                if run.font and run.font.name:
                    fonts.append(run.font.name)
                if run.font and run.font.size:
                    try:
                        sizes.append(float(run.font.size.pt))
                    except Exception:
                        pass
                try:
                    color = run.font.color.rgb if run.font.color else None
                    if isinstance(color, RGBColor):
                        colors.append(f"#{str(color)}")
                except Exception:
                    pass
        if fonts:
            hints["font_family"] = max(set(fonts), key=fonts.count)
        if sizes:
            hints["body_font_size"] = sorted(sizes)[len(sizes) // 2]
            hints["name_font_size"] = max(sizes)
            hints["heading_font_size"] = sorted(sizes)[int(len(sizes) * 0.7)]
        if colors:
            hints["primary_color"] = colors[0]
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return hints


def _map_font_to_reportlab(font_name: str | None) -> str:
    if not font_name:
        return "Times-Roman"
    lower = font_name.lower()
    if "arial" in lower or "helvetica" in lower or "sans" in lower:
        return "Helvetica"
    if "courier" in lower or "mono" in lower:
        return "Courier"
    return "Times-Roman"


def extract_template_config(
    raw_text: str,
    *,
    docx_bytes: bytes | None = None,
) -> TemplateConfig:
    """Infer section order, headings, and style cues from the master resume."""
    config = TemplateConfig()
    config.section_order = _infer_order_from_text(raw_text)

    if docx_bytes:
        hints = extract_docx_style_hints(docx_bytes)
        if hints.get("font_family"):
            config.font_family = _map_font_to_reportlab(str(hints["font_family"]))
        if hints.get("primary_color") and _HEX_COLOR.fullmatch(str(hints["primary_color"])):
            config.primary_color = str(hints["primary_color"])
        if hints.get("body_font_size"):
            config.body_font_size = float(hints["body_font_size"])
        if hints.get("name_font_size"):
            config.name_font_size = min(float(hints["name_font_size"]), 22.0)
        if hints.get("heading_font_size"):
            config.heading_font_size = float(hints["heading_font_size"])

    prompt = f"""Analyze this resume and return ONLY JSON describing its template structure:
- section_order: array of section names in top-to-bottom order (use names like Professional Summary, Skills, Work Experience, Education, Certifications, Projects)
- section_headings: object mapping canonical names to the exact heading text used in the resume (uppercase ok)
- primary_color: hex color like #365f7f if you can infer a brand color, else empty string
- font_family: "Times-Roman" or "Helvetica" or "Courier"

Resume text (excerpt):
{raw_text[:8000]}
"""
    try:
        response = llm_client.generate(prompt)
        payload = _extract_json_object(response)
    except Exception:
        payload = {}

    if payload.get("section_order"):
        config.section_order = _normalize_section_order(list(payload["section_order"]))

    headings = payload.get("section_headings")
    if isinstance(headings, dict):
        mapped: dict[str, str] = dict(_DEFAULT_HEADINGS)
        for key, value in headings.items():
            canonical = normalize_section_heading(str(key)) or normalize_section_heading(str(value))
            if canonical and value:
                mapped[canonical] = str(value).strip().upper()
        config.section_headings = mapped
    else:
        config.section_headings = dict(_DEFAULT_HEADINGS)

    color = str(payload.get("primary_color") or "").strip()
    if _HEX_COLOR.fullmatch(color):
        config.primary_color = color

    font = str(payload.get("font_family") or "").strip()
    if font:
        config.font_family = _map_font_to_reportlab(font)

    return config
