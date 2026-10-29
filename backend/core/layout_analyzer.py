"""Deep layout DNA extractor for master resumes (PDF, DOCX, TXT)."""

from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import Any

import pdfplumber

from core.ats_constants import CANONICAL_SECTIONS, normalize_section_heading
from core.layout_schema import (
    FontSpec,
    MasterLayoutProfile,
    SectionSlot,
    SpacingSpec,
)

logger = logging.getLogger(__name__)

_DEFAULT_PRIMARY_COLOR = "#1f497d"


def _map_font_name(font_name: str | None) -> str:
    if not font_name:
        return "Helvetica"
    lower = font_name.lower()
    if any(k in lower for k in ("times", "serif", "georgia", "cambria", "garamond", "roman")):
        return "Times-Roman"
    if any(k in lower for k in ("courier", "mono", "consolas")):
        return "Courier"
    return "Helvetica"


def _color_tuple_to_hex(color: Any) -> str | None:
    if not color:
        return None
    try:
        if isinstance(color, (list, tuple)):
            if len(color) == 3:
                r, g, b = color
                # pdfplumber colors are often normalized 0.0 - 1.0 or 0 - 255
                if max(r, g, b) <= 1.0:
                    r, g, b = int(r * 255), int(g * 255), int(b * 255)
                else:
                    r, g, b = int(r), int(g), int(b)
                # Ignore near-black or pure white
                if r < 35 and g < 35 and b < 35:
                    return None
                if r > 240 and g > 240 and b > 240:
                    return None
                return f"#{r:02x}{g:02x}{b:02x}"
            if len(color) == 4:
                # CMYK to approximate RGB
                c, m, y, k = color
                r = int(255 * (1 - c) * (1 - k))
                g = int(255 * (1 - m) * (1 - k))
                b = int(255 * (1 - y) * (1 - k))
                if r < 35 and g < 35 and b < 35:
                    return None
                return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        pass
    return None


def _extract_section_slots_from_text(raw_text: str) -> tuple[list[str], dict[str, SectionSlot]]:
    order: list[str] = []
    slots: dict[str, SectionSlot] = {}
    current_section: str | None = None
    section_lines: dict[str, list[str]] = {}

    for line in (raw_text or "").splitlines():
        stripped = line.strip().rstrip(":")
        if not stripped or len(stripped) > 55:
            if current_section and stripped:
                section_lines[current_section].append(stripped)
            continue
        canonical = normalize_section_heading(stripped)
        if canonical:
            current_section = canonical
            if canonical not in order:
                order.append(canonical)
            section_lines.setdefault(canonical, [])
        elif current_section:
            section_lines[current_section].append(stripped)

    for sec in CANONICAL_SECTIONS:
        if sec not in order:
            order.append(sec)

    for sec, lines in section_lines.items():
        bullet_counts: list[int] = []
        char_counts: list[int] = []
        current_entry_bullets = 0

        for line in lines:
            is_bullet = line.startswith(("-", "•", "*", "–", "▸", "▪")) or (
                len(line) > 2 and line[0].isdigit() and line[1] in (".", ")")
            )
            if is_bullet:
                current_entry_bullets += 1
                char_counts.append(len(line))
            elif current_entry_bullets > 0:
                bullet_counts.append(current_entry_bullets)
                current_entry_bullets = 0

        if current_entry_bullets > 0:
            bullet_counts.append(current_entry_bullets)

        avg_chars = int(sum(char_counts) / len(char_counts)) if char_counts else 130
        slots[sec] = SectionSlot(
            canonical_section=sec,
            entry_count=max(1, len(bullet_counts)),
            bullets_per_entry=bullet_counts or [2, 2],
            avg_bullet_chars=avg_chars,
            max_bullet_chars=min(180, int(avg_chars * 1.3)),
        )

    return order, slots


def extract_pdf_layout(file_bytes: bytes, raw_text: str = "") -> MasterLayoutProfile:
    profile = MasterLayoutProfile(file_format="pdf")
    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            page_count = len(pdf.pages)
            profile.page_count = page_count

            if not pdf.pages:
                return profile

            first_page = pdf.pages[0]
            page_w = float(first_page.width)
            page_h = float(first_page.height)

            # Detect page size
            profile.page_size = "Letter" if abs(page_w - 612) < 20 else "A4"

            chars = first_page.chars
            if chars:
                # Text bounds for margins
                x0_vals = [float(c["x0"]) for c in chars if c.get("text", "").strip()]
                x1_vals = [float(c["x1"]) for c in chars if c.get("text", "").strip()]
                top_vals = [float(c["top"]) for c in chars if c.get("text", "").strip()]
                bottom_vals = [float(c["bottom"]) for c in chars if c.get("text", "").strip()]

                if x0_vals and x1_vals and top_vals and bottom_vals:
                    left_margin = max(0.3, min(0.85, min(x0_vals) / 72.0))
                    right_margin = max(0.3, min(0.85, (page_w - max(x1_vals)) / 72.0))
                    top_margin = max(0.3, min(0.85, min(top_vals) / 72.0))
                    bottom_margin = max(0.3, min(0.85, (page_h - max(bottom_vals)) / 72.0))

                    profile.spacing.margin_left_inches = round(left_margin, 2)
                    profile.spacing.margin_right_inches = round(right_margin, 2)
                    profile.spacing.margin_top_inches = round(top_margin, 2)
                    profile.spacing.margin_bottom_inches = round(bottom_margin, 2)

                # Typography analysis
                sizes = [float(c["size"]) for c in chars if c.get("size")]
                font_names = [str(c.get("fontname", "")) for c in chars if c.get("fontname")]

                if font_names:
                    dominant_font = max(set(font_names), key=font_names.count)
                    profile.body_font_family = _map_font_name(dominant_font)
                    profile.heading_font_family = profile.body_font_family

                if sizes:
                    sizes_sorted = sorted(sizes)
                    # Median size is body text
                    body_sz = sizes_sorted[int(len(sizes_sorted) * 0.45)]
                    profile.body_font_size = round(max(8.5, min(11.0, body_sz)), 1)
                    # Name size is maximum font size
                    max_sz = sizes_sorted[-1]
                    profile.name_font_size = round(max(16.0, min(24.0, max_sz)), 1)
                    # Heading size between body and max
                    heading_cands = [s for s in sizes if body_sz + 1.2 <= s < max_sz]
                    if heading_cands:
                        profile.heading_font_size = round(
                            max(set(heading_cands), key=heading_cands.count), 1
                        )
                    else:
                        profile.heading_font_size = round(profile.body_font_size + 2.0, 1)

                # Accent color analysis
                accent_candidates: list[str] = []
                for char in chars:
                    sz = float(char.get("size") or 0)
                    if sz >= profile.heading_font_size - 0.5:
                        c_hex = _color_tuple_to_hex(char.get("non_stroking_color"))
                        if c_hex:
                            accent_candidates.append(c_hex)

                # Check horizontal vector divider lines for color
                for line in first_page.lines:
                    l_hex = _color_tuple_to_hex(line.get("stroking_color")) or _color_tuple_to_hex(
                        line.get("non_stroking_color")
                    )
                    if l_hex:
                        accent_candidates.append(l_hex)

                if accent_candidates:
                    profile.primary_color = max(set(accent_candidates), key=accent_candidates.count)
                else:
                    profile.primary_color = _DEFAULT_PRIMARY_COLOR

    except Exception as exc:
        logger.warning("PDF layout extraction encountered an issue: %s", exc)

    # Section slot breakdown
    order, slots = _extract_section_slots_from_text(raw_text)
    profile.section_order = order
    profile.section_slots = slots
    return profile


def extract_docx_layout(file_bytes: bytes, raw_text: str = "") -> MasterLayoutProfile:
    profile = MasterLayoutProfile(file_format="docx")
    try:
        from docx import Document
        from docx.shared import Inches

        doc = Document(BytesIO(file_bytes))
        if doc.sections:
            sec = doc.sections[0]
            profile.spacing.margin_top_inches = round(sec.top_margin.inches, 2)
            profile.spacing.margin_bottom_inches = round(sec.bottom_margin.inches, 2)
            profile.spacing.margin_left_inches = round(sec.left_margin.inches, 2)
            profile.spacing.margin_right_inches = round(sec.right_margin.inches, 2)
            profile.page_size = "Letter" if abs(sec.page_width.inches - 8.5) < 0.2 else "A4"

        fonts: list[str] = []
        sizes: list[float] = []
        for p in doc.paragraphs[:80]:
            for r in p.runs:
                if r.font and r.font.name:
                    fonts.append(r.font.name)
                if r.font and r.font.size:
                    sizes.append(float(r.font.size.pt))

        if fonts:
            dominant = max(set(fonts), key=fonts.count)
            profile.body_font_family = _map_font_name(dominant)
            profile.heading_font_family = profile.body_font_family
        if sizes:
            sizes_sorted = sorted(sizes)
            profile.body_font_size = round(sizes_sorted[int(len(sizes_sorted) * 0.45)], 1)
            profile.name_font_size = round(min(22.0, max(sizes)), 1)
            profile.heading_font_size = round(profile.body_font_size + 2.0, 1)

    except Exception as exc:
        logger.warning("DOCX layout extraction encountered an issue: %s", exc)

    order, slots = _extract_section_slots_from_text(raw_text)
    profile.section_order = order
    profile.section_slots = slots
    return profile


def analyze_master_layout(
    file_bytes: bytes,
    filename: str,
    raw_text: str = "",
) -> MasterLayoutProfile:
    """Entry point: extracts layout DNA from any resume file."""
    lower_name = (filename or "").lower()
    if lower_name.endswith(".pdf"):
        return extract_pdf_layout(file_bytes, raw_text=raw_text)
    if lower_name.endswith(".docx"):
        return extract_docx_layout(file_bytes, raw_text=raw_text)
    order, slots = _extract_section_slots_from_text(raw_text)
    profile = MasterLayoutProfile(file_format="txt")
    profile.section_order = order
    profile.section_slots = slots
    return profile
