"""ATS-safe PDF and DOCX export for generated resumes."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from typing import TYPE_CHECKING, Optional

from core.ats_constants import (
    CANONICAL_SECTIONS,
    ContactInfo,
    PDF_SECTION_DISPLAY,
    normalize_linkedin_url,
    normalize_section_heading,
    reorder_and_normalize_markdown,
)

if TYPE_CHECKING:
    from db.models import Profile


def _validate_export(
    file_bytes: bytes,
    file_type: str,
    expected_keywords: list[str] | None = None,
) -> tuple[bool, list[str]]:
    from core.resume_validator import validate_exported_resume

    return validate_exported_resume(file_bytes, file_type, expected_keywords)  # type: ignore[arg-type]

logger = logging.getLogger(__name__)

MARGIN_INCHES = 0.75
BODY_FONT_SIZE = 11
HEADING_FONT_SIZE = 12
NAME_FONT_SIZE = 18
CONTACT_FONT_SIZE = 10
SUBTITLE_FONT_SIZE = 10.5


class BlockType(str, Enum):
    HEADING1 = "heading1"
    HEADING2 = "heading2"
    HEADING3 = "heading3"
    PARAGRAPH = "paragraph"
    BULLET = "bullet"
    SPACER = "spacer"


@dataclass
class DocumentBlock:
    block_type: BlockType
    text: str = ""


@dataclass
class ExportResult:
    file_bytes: bytes
    validation_ok: bool
    validation_issues: list[str]


@dataclass
class ResumeEntry:
    title: str
    organization: str = ""
    location: str = ""
    date: str = ""
    extra_lines: list[str] | None = None
    bullets: list[str] | None = None


@dataclass
class TemplateResume:
    summary: str = ""
    skills: list[tuple[str, str]] | None = None
    experience: list[ResumeEntry] | None = None
    education: list[ResumeEntry] | None = None
    certifications: list[str] | None = None


@dataclass
class TemplateScale:
    name_size: float = 20
    title_size: float = 14
    heading_size: float = 14
    body_size: float = 10.4
    body_leading: float = 11.2
    skill_size: float = 10.1
    skill_leading: float = 10.8
    contact_size: float = 9.2
    entry_size: float = 10.4
    org_size: float = 10.0
    right_size: float = 9.9
    bullet_size: float = 9.8
    bullet_leading: float = 10.5
    cert_size: float = 9.7
    section_gap_inches: float = 0.045


DEFAULT_TEMPLATE_SCALE = TemplateScale()
COMPACT_TEMPLATE_SCALE = TemplateScale(
    name_size=18.5,
    title_size=12.7,
    heading_size=12.8,
    body_size=9.4,
    body_leading=10.0,
    skill_size=9.1,
    skill_leading=9.7,
    contact_size=8.4,
    entry_size=9.5,
    org_size=9.2,
    right_size=8.9,
    bullet_size=8.9,
    bullet_leading=9.4,
    cert_size=8.9,
    section_gap_inches=0.025,
)


def _escape_xml(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return "|" in stripped and (stripped.count("|") >= 2 or "---" in stripped)


def strip_markdown_tables(markdown_content: str) -> str:
    """Remove markdown table lines; ATS systems cannot parse tables."""
    return "\n".join(
        line for line in markdown_content.splitlines()
        if not _is_table_line(line)
    )


def parse_markdown_blocks(markdown_content: str) -> list[DocumentBlock]:
    """Parse Markdown into a structured document model."""
    content = strip_markdown_tables(markdown_content)
    blocks: list[DocumentBlock] = []

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            blocks.append(DocumentBlock(BlockType.SPACER))
        elif stripped.startswith("### "):
            blocks.append(DocumentBlock(BlockType.HEADING3, stripped[4:].strip()))
        elif stripped.startswith("## "):
            blocks.append(DocumentBlock(BlockType.HEADING2, stripped[3:].strip()))
        elif stripped.startswith("# "):
            blocks.append(DocumentBlock(BlockType.HEADING1, stripped[2:].strip()))
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append(DocumentBlock(BlockType.BULLET, stripped[2:].strip()))
        else:
            blocks.append(DocumentBlock(BlockType.PARAGRAPH, stripped))

    return blocks


def build_contact_info(profile: Optional["Profile"]) -> ContactInfo:
    """Build structured contact info from profile."""
    if profile is None:
        return ContactInfo()

    return ContactInfo(
        name=profile.full_name or "",
        location=profile.location or "",
        phone=profile.phone or "",
        email=profile.email or "",
        linkedin=profile.linkedin or "",
        github=profile.github or "",
        portfolio=profile.portfolio or "",
    )


def build_contact_lines(profile: Optional["Profile"]) -> list[str]:
    """Build contact info lines from profile (legacy helper for tests)."""
    info = build_contact_info(profile)
    lines: list[str] = []
    if info.name:
        lines.append(info.name)

    parts: list[str] = []
    if info.location:
        parts.append(info.location)
    if info.phone:
        parts.append(info.phone)
    if info.email:
        parts.append(info.email)
    if info.linkedin:
        parts.append(info.linkedin)
    if info.github:
        parts.append(info.github)
    if info.portfolio:
        parts.append(info.portfolio)
    if parts:
        lines.append(" | ".join(parts))

    return lines


def _build_contact_line_parts(info: ContactInfo) -> list[tuple[str, str | None]]:
    """Return (display_text, url) tuples for contact line. url=None for plain text."""
    parts: list[tuple[str, str | None]] = []
    if info.location:
        parts.append((info.location, None))
    if info.phone:
        parts.append((info.phone, None))
    if info.email:
        parts.append((info.email, f"mailto:{info.email}"))
    if info.linkedin:
        url = normalize_linkedin_url(info.linkedin)
        display = info.linkedin.replace("https://", "").replace("http://", "")
        parts.append((display, url))
    if info.github:
        parts.append((info.github, None))
    if info.portfolio:
        parts.append((info.portfolio, None))
    return parts


def _pdf_font_name() -> str:
    """Return serif font for classic resume layout."""
    return "Times-Roman"


def _pdf_font_bold(base: str) -> str:
    if base == "Times-Roman":
        return "Times-Bold"
    if base == "Arial":
        return "Arial-Bold"
    return "Helvetica-Bold"


def _split_meta_line(line: str) -> tuple[str, str]:
    if "|" in line:
        left, right = line.rsplit("|", 1)
        return left.strip(), right.strip()
    return line.strip(), ""


def _split_org_location(text: str) -> tuple[str, str]:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) >= 2:
        return parts[0], ", ".join(parts[1:])
    return text, ""


def _parse_markdown_sections(markdown_content: str) -> list[tuple[str, list[DocumentBlock]]]:
    """Split normalized markdown into canonical sections and blocks."""
    normalized = reorder_and_normalize_markdown(markdown_content)
    sections: list[tuple[str, list[DocumentBlock]]] = []
    current_section: str | None = None
    current_blocks: list[DocumentBlock] = []

    for block in parse_markdown_blocks(normalized):
        if block.block_type == BlockType.HEADING2:
            canonical = normalize_section_heading(block.text)
            if canonical is None and current_section is not None:
                current_blocks.append(DocumentBlock(BlockType.HEADING3, block.text))
                continue
            if current_section is not None:
                sections.append((current_section, current_blocks))
            current_section = canonical or block.text
            current_blocks = []
        elif current_section is not None:
            current_blocks.append(block)

    if current_section is not None:
        sections.append((current_section, current_blocks))

    return sections


def _group_entry_blocks(blocks: list[DocumentBlock]) -> list[dict[str, object]]:
    """Group heading3-led blocks into structured entries."""
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for block in blocks:
        if block.block_type == BlockType.HEADING3:
            if current is not None:
                entries.append(current)
            current = {"title": block.text, "meta_line": "", "extra_lines": [], "bullets": []}
        elif current is None:
            continue
        elif block.block_type == BlockType.PARAGRAPH and not current["meta_line"]:
            current["meta_line"] = block.text
        elif block.block_type == BlockType.PARAGRAPH:
            extra_lines = current["extra_lines"]
            assert isinstance(extra_lines, list)
            extra_lines.append(block.text)
        elif block.block_type == BlockType.BULLET:
            bullets = current["bullets"]
            assert isinstance(bullets, list)
            bullets.append(block.text)

    if current is not None:
        entries.append(current)

    return entries


def _two_column_table(
    left_text: str,
    right_text: str,
    left_style,
    right_style,
    content_width: float,
    *,
    left_bold: bool = False,
):
    from reportlab.platypus import Paragraph, Table, TableStyle

    left_xml = f"<b>{_escape_xml(left_text)}</b>" if left_bold else _escape_xml(left_text)
    left_para = Paragraph(left_xml, left_style)
    right_para = Paragraph(_escape_xml(right_text), right_style) if right_text else Paragraph("", right_style)
    table = Table(
        [[left_para, right_para]],
        colWidths=[content_width * 0.62, content_width * 0.38],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    return table


def _append_section_heading(elements: list, title: str, heading_style, hr_args: dict) -> None:
    from reportlab.platypus import HRFlowable, Paragraph

    elements.append(Paragraph(_escape_xml(title), heading_style))
    elements.append(HRFlowable(**hr_args))


def _build_pdf_body_elements(
    markdown_content: str,
    styles: dict[str, object],
    content_width: float,
) -> list:
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, Spacer

    elements: list = []
    body_style = styles["body"]
    bullet_style = styles["bullet"]
    subtitle_style = styles["subtitle"]
    right_style = styles["right"]
    heading_style = styles["heading"]
    hr_args = styles["hr_args"]

    section_map = dict(_parse_markdown_sections(markdown_content))

    for section_name in CANONICAL_SECTIONS:
        blocks = section_map.get(section_name, [])
        content_blocks = [
            block for block in blocks
            if block.block_type != BlockType.SPACER or block.text
        ]
        if not content_blocks:
            if section_name == "Certifications":
                continue
            continue

        display_title = PDF_SECTION_DISPLAY.get(section_name, section_name.upper())
        _append_section_heading(elements, display_title, heading_style, hr_args)

        if section_name == "Professional Summary":
            paragraphs = [
                block.text for block in content_blocks
                if block.block_type == BlockType.PARAGRAPH and block.text.strip()
            ]
            if paragraphs:
                elements.append(Paragraph(_escape_xml(" ".join(paragraphs)), body_style))
            continue

        if section_name == "Skills":
            bullets = [
                block.text for block in content_blocks
                if block.block_type == BlockType.BULLET and block.text.strip()
            ]
            if bullets:
                for bullet in bullets:
                    elements.append(Paragraph(f"• {_escape_xml(bullet)}", bullet_style))
            else:
                paragraphs = [
                    block.text for block in content_blocks
                    if block.block_type == BlockType.PARAGRAPH and block.text.strip()
                ]
                if paragraphs:
                    elements.append(Paragraph(_escape_xml(" ".join(paragraphs)), body_style))
            continue

        if section_name in ("Work Experience", "Education"):
            entries = _group_entry_blocks(content_blocks)
            for index, entry in enumerate(entries):
                title = str(entry.get("title", ""))
                meta_line = str(entry.get("meta_line", ""))
                left, right = _split_meta_line(meta_line)
                org, location = _split_org_location(left)

                if section_name == "Work Experience":
                    elements.append(
                        _two_column_table(
                            org or title,
                            location,
                            body_style,
                            right_style,
                            content_width,
                            left_bold=True,
                        )
                    )
                    elements.append(
                        _two_column_table(
                            title if org else "",
                            right,
                            subtitle_style,
                            right_style,
                            content_width,
                        )
                    )
                else:
                    elements.append(
                        _two_column_table(
                            org or title,
                            location,
                            body_style,
                            right_style,
                            content_width,
                            left_bold=True,
                        )
                    )
                    elements.append(
                        _two_column_table(
                            title if org else "",
                            right,
                            subtitle_style,
                            right_style,
                            content_width,
                        )
                    )

                extra_lines = entry.get("extra_lines", [])
                if isinstance(extra_lines, list):
                    for line in extra_lines:
                        if line:
                            elements.append(Paragraph(_escape_xml(str(line)), body_style))

                bullets = entry.get("bullets", [])
                if isinstance(bullets, list):
                    for bullet in bullets:
                        if bullet:
                            elements.append(Paragraph(f"• {_escape_xml(str(bullet))}", bullet_style))

                if index < len(entries) - 1:
                    elements.append(Spacer(1, 0.06 * inch))
            continue

        for block in content_blocks:
            if block.block_type == BlockType.BULLET and block.text:
                elements.append(Paragraph(f"• {_escape_xml(block.text)}", bullet_style))
            elif block.block_type == BlockType.PARAGRAPH and block.text:
                elements.append(Paragraph(_escape_xml(block.text), body_style))

    return elements


def _contact_line_pdf_xml(info: ContactInfo) -> str:
    """Build ReportLab paragraph XML for contact line with hyperlinks."""
    parts = _build_contact_line_parts(info)
    segments: list[str] = []
    for i, (text, url) in enumerate(parts):
        if i > 0:
            segments.append(" | ")
        escaped = _escape_xml(text)
        if url:
            segments.append(f'<a href="{_escape_xml(url)}" color="#000000">{escaped}</a>')
        else:
            segments.append(escaped)
    return "".join(segments)


def _clean_generated_text(text: str) -> str:
    """Normalize common encoding artifacts from generated content."""
    if not text:
        return ""
    replacements = {
        "â€”": "-",
        "â€“": "-",
        "â€¢": "",
        "â†’": "->",
        "\u2014": "-",
        "\u2013": "-",
        "\u2022": "",
    }
    cleaned = text
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    return re.sub(r"\s+", " ", cleaned).strip()


def _parse_skill_line(text: str) -> tuple[str, str]:
    cleaned = _clean_generated_text(text)
    if ":" in cleaned:
        category, items = cleaned.split(":", 1)
        return category.strip(), items.strip()
    if " : " in cleaned:
        category, items = cleaned.split(" : ", 1)
        return category.strip(), items.strip()
    return "", cleaned


def _entry_from_group(entry: dict[str, object]) -> ResumeEntry:
    title = _clean_generated_text(str(entry.get("title", "")))
    meta_line = _clean_generated_text(str(entry.get("meta_line", "")))
    left, date = _split_meta_line(meta_line)
    organization, location = _split_org_location(left)
    extra_lines = [
        _clean_generated_text(str(line))
        for line in entry.get("extra_lines", [])
        if str(line).strip()
    ]
    bullets = [
        _clean_generated_text(str(line))
        for line in entry.get("bullets", [])
        if str(line).strip()
    ]
    return ResumeEntry(
        title=title,
        organization=organization,
        location=location,
        date=date,
        extra_lines=extra_lines,
        bullets=bullets,
    )


def parse_template_resume(markdown_content: str) -> TemplateResume:
    """Convert generated Markdown into the structured fields needed by the template."""
    section_map = dict(_parse_markdown_sections(markdown_content))
    parsed = TemplateResume(skills=[], experience=[], education=[], certifications=[])

    summary_blocks = section_map.get("Professional Summary", [])
    summary_parts = [
        _clean_generated_text(block.text)
        for block in summary_blocks
        if block.block_type in (BlockType.PARAGRAPH, BlockType.BULLET) and block.text.strip()
    ]
    parsed.summary = " ".join(summary_parts)

    skill_blocks = section_map.get("Skills", [])
    skills: list[tuple[str, str]] = []
    for block in skill_blocks:
        if block.block_type in (BlockType.BULLET, BlockType.PARAGRAPH) and block.text.strip():
            skills.append(_parse_skill_line(block.text))
    parsed.skills = skills

    parsed.experience = [
        _entry_from_group(entry)
        for entry in _group_entry_blocks(section_map.get("Work Experience", []))
    ]
    parsed.education = [
        _entry_from_group(entry)
        for entry in _group_entry_blocks(section_map.get("Education", []))
    ]

    certs: list[str] = []
    for block in section_map.get("Certifications", []):
        if block.block_type in (BlockType.BULLET, BlockType.PARAGRAPH) and block.text.strip():
            certs.append(_clean_generated_text(block.text))
    parsed.certifications = certs
    return parsed


def _limit_words(text: str, max_words: int) -> str:
    words = _clean_generated_text(text).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(".,;:") + "."


def _keyword_score(text: str, keywords: list[str] | None) -> int:
    if not keywords:
        return 0
    lower = text.lower()
    return sum(1 for keyword in keywords if keyword.lower() in lower)


def _limit_skill_items(value: str, keywords: list[str] | None, max_items: int) -> str:
    items = [_clean_generated_text(item) for item in value.split(",") if item.strip()]
    if len(items) <= max_items:
        return ", ".join(items)
    ranked = sorted(
        enumerate(items),
        key=lambda item: (-_keyword_score(item[1], keywords), item[0]),
    )
    chosen_indexes = sorted(index for index, _item in ranked[:max_items])
    return ", ".join(items[index] for index in chosen_indexes)


def _compact_entry(entry: ResumeEntry, index: int, *, aggressive: bool) -> ResumeEntry:
    max_bullets = 4 if index == 0 else 1
    max_words = 22 if aggressive else 28
    if not aggressive:
        max_bullets = 5 if index == 0 else 2

    bullets = [
        _limit_words(bullet, max_words)
        for bullet in (entry.bullets or [])[:max_bullets]
    ]
    return ResumeEntry(
        title=_limit_words(entry.title, 8),
        organization=_limit_words(entry.organization, 8),
        location=_limit_words(entry.location, 5),
        date=entry.date,
        extra_lines=[],
        bullets=bullets,
    )


def compact_template_resume(
    resume: TemplateResume,
    keywords: list[str] | None = None,
    *,
    aggressive: bool = False,
) -> TemplateResume:
    """Apply one-page content budgets without removing required populated sections."""
    skill_limit = 4 if aggressive else 5
    skill_item_limit = 7 if aggressive else 9
    skills = [
        (category, _limit_skill_items(value, keywords, skill_item_limit))
        for category, value in (resume.skills or [])[:skill_limit]
        if (category or value)
    ]

    experience = [
        _compact_entry(entry, index, aggressive=aggressive)
        for index, entry in enumerate((resume.experience or [])[:2])
    ]
    education = [
        ResumeEntry(
            title=_limit_words(entry.title, 10),
            organization=_limit_words(entry.organization, 8),
            location=_limit_words(entry.location, 5),
            date=entry.date,
            extra_lines=[],
            bullets=[],
        )
        for entry in (resume.education or [])[:1]
    ]
    cert_limit = 3 if aggressive else 4
    certifications = [
        _limit_words(certification, 8)
        for certification in (resume.certifications or [])[:cert_limit]
    ]

    return TemplateResume(
        summary=_limit_words(resume.summary, 45 if aggressive else 60),
        skills=skills,
        experience=experience,
        education=education,
        certifications=certifications,
    )


def _template_resume_to_markdown(resume: TemplateResume) -> str:
    parts: list[str] = []
    if resume.summary:
        parts.extend(["## Professional Summary", resume.summary, ""])
    if resume.skills:
        parts.append("## Skills")
        for category, value in resume.skills:
            prefix = f"{category} : " if category else ""
            parts.append(f"- {prefix}{value}")
        parts.append("")
    if resume.experience:
        parts.append("## Work Experience")
        for entry in resume.experience:
            parts.append(f"### {entry.title}")
            meta_left = ", ".join(part for part in [entry.organization, entry.location] if part)
            parts.append(f"{meta_left} | {entry.date}".strip(" |"))
            for bullet in entry.bullets or []:
                parts.append(f"- {bullet}")
        parts.append("")
    if resume.education:
        parts.append("## Education")
        for entry in resume.education:
            parts.append(f"### {entry.title}")
            meta_left = ", ".join(part for part in [entry.organization, entry.location] if part)
            parts.append(f"{meta_left} | {entry.date}".strip(" |"))
        parts.append("")
    if resume.certifications:
        parts.append("## Certifications")
        for certification in resume.certifications:
            parts.append(f"- {certification}")
    return "\n".join(parts).strip() + "\n"


def _has_required_template_sections(resume: TemplateResume) -> bool:
    return bool(resume.summary and resume.skills and resume.experience and resume.education)


def _rewrite_one_page_markdown(
    markdown_content: str,
    profile_text: str | None,
    keywords: list[str] | None,
) -> str | None:
    """Ask the configured LLM to compact the tailored resume for a one-page PDF."""
    try:
        from core.llm_client import llm_client
    except Exception:
        return None

    keyword_text = ", ".join(keywords or [])
    prompt = f"""Rewrite this tailored resume Markdown so it fits a one-page PDF template.

Hard rules:
- Output Markdown only.
- Use only these headings, in this exact order:
  ## Professional Summary
  ## Skills
  ## Work Experience
  ## Education
  ## Certifications
- Professional Summary: max 45 words.
- Skills: max 5 bullet lines, each "Category : item, item"; keep only JD-relevant skills.
- Work Experience: max 2 roles. Current/recent role max 5 bullets. Older role max 2 bullets.
- Education: one compact entry.
- Certifications: max 4 bullets. Omit Certifications only if the resume has no certifications.
- Do not create Projects or Achievements sections. Fold relevant project/achievement details into Work Experience.
- Keep claims truthful and preserve priority JD keywords where supported.

Priority JD keywords:
{keyword_text}

Profile context:
{profile_text or ""}

Resume to compact:
{markdown_content}
"""
    try:
        candidate = llm_client.generate(prompt)
    except Exception:
        return None
    if not candidate or not candidate.strip():
        return None
    if "api key is not configured" in candidate.lower() or "service is not available" in candidate.lower():
        return None

    parsed = compact_template_resume(parse_template_resume(candidate), keywords)
    if not _has_required_template_sections(parsed):
        return None
    return _template_resume_to_markdown(parsed)


def _template_job_title(job_title: str | None) -> str:
    cleaned = _clean_generated_text(job_title or "")
    if not cleaned:
        return "Software Engineer | AI Engineer"
    if "|" in cleaned:
        return cleaned
    if "software engineer" in cleaned.lower():
        return cleaned
    return f"Software Engineer | {cleaned}"


def _template_contact_items(info: ContactInfo) -> list[tuple[str, str, str | None]]:
    items: list[tuple[str, str, str | None]] = []
    if info.email:
        items.append(("E", info.email, f"mailto:{info.email}"))
    if info.phone:
        items.append(("P", info.phone, None))
    if info.location:
        items.append(("L", info.location, None))
    if info.linkedin:
        url = normalize_linkedin_url(info.linkedin)
        display = info.name.title() if info.name else info.linkedin.replace("https://", "").replace("http://", "")
        items.append(("in", display, url))
    elif info.portfolio:
        items.append(("W", info.portfolio, info.portfolio))
    return items


def _template_section_heading(title: str, heading_style, rule_color, gap_inches: float):
    from reportlab.lib.units import inch
    from reportlab.platypus import HRFlowable, Paragraph, Spacer

    return [
        Spacer(1, gap_inches * inch),
        Paragraph(_escape_xml(title), heading_style),
        HRFlowable(
            width="100%",
            thickness=1.8,
            color=rule_color,
            spaceBefore=1,
            spaceAfter=5,
            lineCap="square",
        ),
    ]


def _bold_prefix_paragraph(category: str, value: str, style):
    from reportlab.platypus import Paragraph

    if category:
        text = f"<b>{_escape_xml(category)}:</b> {_escape_xml(value)}"
    else:
        text = _escape_xml(value)
    return Paragraph(text, style)


def _template_two_col(left_xml: str, right_text: str, left_style, right_style, content_width: float):
    from reportlab.platypus import Paragraph, Table, TableStyle

    table = Table(
        [[Paragraph(left_xml, left_style), Paragraph(_escape_xml(right_text), right_style)]],
        colWidths=[content_width * 0.68, content_width * 0.32],
    )
    table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _append_template_entries(elements: list, entries: list[ResumeEntry], styles: dict[str, object], content_width: float) -> None:
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, Spacer

    title_style = styles["entry_title"]
    right_style = styles["right"]
    org_style = styles["org"]
    bullet_style = styles["bullet"]
    body_style = styles["body"]

    for entry_index, entry in enumerate(entries):
        location_suffix = f" | {entry.location}" if entry.location else ""
        right_text = f"{entry.date}{location_suffix}" if entry.date else entry.location
        elements.append(
            _template_two_col(
                f"<b>{_escape_xml(entry.title)}</b>",
                right_text,
                title_style,
                right_style,
                content_width,
            )
        )
        if entry.organization:
            elements.append(Paragraph(f"<i>{_escape_xml(entry.organization)}</i>", org_style))
        for line in entry.extra_lines or []:
            elements.append(Paragraph(_escape_xml(line), body_style))
        for bullet in entry.bullets or []:
            elements.append(Paragraph(_escape_xml(bullet), bullet_style, bulletText=chr(8226)))
        if entry_index < len(entries) - 1:
            elements.append(Spacer(1, 0.045 * inch))


def _append_template_certifications(elements: list, certifications: list[str], style, content_width: float) -> None:
    from reportlab.platypus import Paragraph, Table, TableStyle

    rows: list[list[Paragraph]] = []
    columns = 3
    for index in range(0, len(certifications), columns):
        row: list[Paragraph] = []
        for item in certifications[index:index + columns]:
            row.append(Paragraph(_escape_xml(item), style, bulletText=chr(8226)))
        while len(row) < columns:
            row.append(Paragraph("", style))
        rows.append(row)

    if not rows:
        return

    table = Table(rows, colWidths=[content_width / columns] * columns)
    table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    elements.append(table)


def sanitize_filename(value: str, fallback: str = "Resume") -> str:
    """Sanitize a string for use in a filename."""
    cleaned = re.sub(r"[^\w\s-]", "", value).strip()
    cleaned = re.sub(r"[\s_-]+", "_", cleaned)
    return cleaned[:50] if cleaned else fallback


def build_resume_filename(profile: Optional["Profile"], job_title: str = "") -> str:
    """Build a descriptive PDF filename."""
    name = sanitize_filename(profile.full_name if profile and profile.full_name else "", "Candidate")
    title = sanitize_filename(job_title, "Job")
    return f"{name}_{title}_Resume.pdf"


def _add_docx_hyperlink(paragraph, text: str, url: str) -> None:
    """Add a hyperlink run to a python-docx paragraph."""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "000000")
    r_pr.append(color)
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    r_pr.append(u)
    new_run.append(r_pr)
    text_elem = OxmlElement("w:t")
    text_elem.text = text
    new_run.append(text_elem)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


def _add_docx_contact_paragraph(doc, info: ContactInfo, font_name: str, font_size: int) -> None:
    """Add single-line contact paragraph with hyperlinks."""
    from docx.shared import Pt

    parts = _build_contact_line_parts(info)
    if not parts:
        return

    paragraph = doc.add_paragraph()
    for i, (text, url) in enumerate(parts):
        if i > 0:
            run = paragraph.add_run(" | ")
            run.font.name = font_name
            run.font.size = Pt(font_size)
        if url:
            _add_docx_hyperlink(paragraph, text, url)
        else:
            run = paragraph.add_run(text)
            run.font.name = font_name
            run.font.size = Pt(font_size)


def _configure_docx_styles(doc) -> None:
    """Set ATS-safe fonts and margins on a DOCX document."""
    from docx.shared import Inches, Pt

    section = doc.sections[0]
    margin = Inches(MARGIN_INCHES)
    section.top_margin = margin
    section.bottom_margin = margin
    section.left_margin = margin
    section.right_margin = margin

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(BODY_FONT_SIZE)

    for level in (1, 2, 3):
        style = doc.styles[f"Heading {level}"]
        style.font.name = "Calibri"
        style.font.size = Pt(HEADING_FONT_SIZE)
        style.font.bold = True


def _pdf_page_count(pdf_bytes: bytes) -> int:
    try:
        import pdfplumber

        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            return len(pdf.pages)
    except Exception:
        try:
            from pypdf import PdfReader

            return len(PdfReader(BytesIO(pdf_bytes)).pages)
        except Exception:
            return 0


def _trim_one_experience_bullet(resume: TemplateResume) -> bool:
    entries = resume.experience or []
    for entry in reversed(entries):
        if entry.bullets:
            entry.bullets.pop()
            return True
    return False


def _contact_col_widths(pair_count: int, content_width: float) -> list[float]:
    icon_width = 12
    text_width = max(40, (content_width - (icon_width * pair_count)) / max(1, pair_count))
    preferred = [150, 82, 92, 120]
    widths: list[float] = []
    for index in range(pair_count):
        widths.extend([icon_width, preferred[index] if index < len(preferred) else text_width])
    total = sum(widths)
    if total > content_width:
        scale = content_width / total
        widths = [width * scale for width in widths]
    return widths


def _render_template_pdf_bytes(
    resume: TemplateResume,
    contact: ContactInfo,
    job_title: str | None,
    scale: TemplateScale,
) -> bytes:
    """Render already-budgeted resume content into the visual template."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        logger.warning("reportlab is not installed; PDF export unavailable")
        return b""

    pdf_buffer = BytesIO()
    page_width, _page_height = A4
    left_margin = 0.63 * inch
    right_margin = 0.63 * inch
    top_margin = 0.38 * inch
    bottom_margin = 0.36 * inch
    content_width = page_width - left_margin - right_margin
    blue = colors.HexColor("#365f7f")
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=A4,
        topMargin=top_margin,
        bottomMargin=bottom_margin,
        leftMargin=left_margin,
        rightMargin=right_margin,
    )

    name_style = ParagraphStyle(
        "TemplateName",
        fontName="Times-Bold",
        fontSize=scale.name_size,
        leading=scale.name_size + 2,
        spaceAfter=2,
        textColor=blue,
    )
    title_style = ParagraphStyle(
        "TemplateTitle",
        fontName="Times-Italic",
        fontSize=scale.title_size,
        leading=scale.title_size + 2,
        spaceAfter=6,
        textColor=colors.black,
    )
    heading_style = ParagraphStyle(
        "TemplateHeading",
        fontName="Times-Bold",
        fontSize=scale.heading_size,
        leading=scale.heading_size + 1,
        spaceAfter=1,
        textColor=blue,
    )
    body_style = ParagraphStyle(
        "TemplateBody",
        fontName="Times-Roman",
        fontSize=scale.body_size,
        leading=scale.body_leading,
        spaceAfter=1,
        textColor=colors.black,
    )
    skill_style = ParagraphStyle(
        "TemplateSkill",
        parent=body_style,
        fontSize=scale.skill_size,
        leading=scale.skill_leading,
        spaceAfter=0,
    )
    contact_style = ParagraphStyle(
        "TemplateContact",
        fontName="Times-Roman",
        fontSize=scale.contact_size,
        leading=scale.contact_size + 1,
        textColor=colors.black,
        )
    icon_style = ParagraphStyle(
        "TemplateContactIcon",
        fontName="Times-Bold",
        fontSize=max(7.5, scale.contact_size - 0.5),
        leading=scale.contact_size + 1,
        textColor=blue,
    )
    entry_title_style = ParagraphStyle(
        "TemplateEntryTitle",
        fontName="Times-Bold",
        fontSize=scale.entry_size,
        leading=scale.entry_size + 1,
        textColor=colors.black,
    )
    org_style = ParagraphStyle(
        "TemplateOrg",
        fontName="Times-Italic",
        fontSize=scale.org_size,
        leading=scale.org_size + 0.8,
        spaceAfter=0,
        textColor=colors.black,
    )
    right_style = ParagraphStyle(
        "TemplateRight",
        fontName="Times-Roman",
        fontSize=scale.right_size,
        leading=scale.right_size + 1,
        alignment=TA_RIGHT,
        textColor=colors.black,
    )
    bullet_style = ParagraphStyle(
        "TemplateBullet",
        fontName="Times-Roman",
        fontSize=scale.bullet_size,
        leading=scale.bullet_leading,
        leftIndent=10,
        firstLineIndent=0,
        bulletIndent=0,
        spaceAfter=0,
        textColor=colors.black,
    )
    cert_style = ParagraphStyle(
        "TemplateCertification",
        parent=bullet_style,
        fontSize=scale.cert_size,
        leading=scale.cert_size + 1,
        leftIndent=10,
        rightIndent=6,
    )

    elements: list = []
    if contact.name:
        elements.append(Paragraph(_escape_xml(contact.name.upper()), name_style))
    elements.append(Paragraph(_escape_xml(_template_job_title(job_title)), title_style))

    contact_cells: list = []
    for icon, text, url in _template_contact_items(contact):
        contact_cells.append(Paragraph(_escape_xml(icon), icon_style))
        if url:
            contact_cells.append(
                Paragraph(
                    f'<a href="{_escape_xml(url)}" color="#000000">{_escape_xml(text)}</a>',
                    contact_style,
                )
            )
        else:
            contact_cells.append(Paragraph(_escape_xml(text), contact_style))
    if contact_cells:
        col_widths = _contact_col_widths(len(contact_cells) // 2, content_width)
        contact_table = Table([contact_cells], colWidths=col_widths)
        contact_table.hAlign = "LEFT"
        contact_table.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        elements.append(contact_table)

    if resume.summary:
        elements.extend(_template_section_heading("PROFESSIONAL SUMMARY", heading_style, colors.black, scale.section_gap_inches))
        elements.append(Paragraph(_escape_xml(resume.summary), body_style))

    if resume.skills:
        elements.extend(_template_section_heading("SKILLS", heading_style, colors.black, scale.section_gap_inches))
        for category, value in resume.skills:
            elements.append(_bold_prefix_paragraph(category, value, skill_style))

    if resume.experience:
        elements.extend(_template_section_heading("EXPERIENCE", heading_style, colors.black, scale.section_gap_inches))
        _append_template_entries(
            elements,
            resume.experience,
            {
                "entry_title": entry_title_style,
                "right": right_style,
                "org": org_style,
                "bullet": bullet_style,
                "body": body_style,
            },
            content_width,
        )

    if resume.education:
        elements.extend(_template_section_heading("EDUCATION", heading_style, colors.black, scale.section_gap_inches))
        _append_template_entries(
            elements,
            resume.education,
            {
                "entry_title": entry_title_style,
                "right": right_style,
                "org": org_style,
                "bullet": bullet_style,
                "body": body_style,
            },
            content_width,
        )

    if resume.certifications:
        elements.extend(_template_section_heading("CERTIFICATIONS", heading_style, colors.black, scale.section_gap_inches))
        _append_template_certifications(elements, resume.certifications, cert_style, content_width)

    if not elements:
        elements.append(Paragraph("Resume", body_style))

    try:
        doc.build(elements)
    except Exception as exc:
        logger.exception("PDF build failed: %s", exc)
        raise RuntimeError(f"PDF generation failed: {exc}") from exc

    return pdf_buffer.getvalue()


def generate_pdf_bytes(
    markdown_content: str,
    profile: Optional["Profile"] = None,
    expected_keywords: list[str] | None = None,
    job_title: str | None = None,
    *,
    profile_text: str | None = None,
    rewrite_for_one_page: bool = False,
) -> bytes | None:
    """Convert Markdown resume to a validated one-page visual PDF template."""
    contact = build_contact_info(profile)

    source_markdown = markdown_content
    if rewrite_for_one_page:
        rewritten = _rewrite_one_page_markdown(markdown_content, profile_text, expected_keywords)
        if rewritten:
            source_markdown = rewritten

    resume = compact_template_resume(parse_template_resume(source_markdown), expected_keywords)
    if not _has_required_template_sections(resume):
        resume = compact_template_resume(parse_template_resume(markdown_content), expected_keywords)

    if not _has_required_template_sections(resume):
        logger.warning("PDF export missing required template sections before render")

    try:
        pdf_bytes = _render_template_pdf_bytes(resume, contact, job_title, DEFAULT_TEMPLATE_SCALE)
    except RuntimeError:
        raise
    if not pdf_bytes:
        return None

    if _pdf_page_count(pdf_bytes) > 1:
        resume = compact_template_resume(resume, expected_keywords, aggressive=True)
        pdf_bytes = _render_template_pdf_bytes(resume, contact, job_title, COMPACT_TEMPLATE_SCALE)

    while _pdf_page_count(pdf_bytes) > 1 and _trim_one_experience_bullet(resume):
        pdf_bytes = _render_template_pdf_bytes(resume, contact, job_title, COMPACT_TEMPLATE_SCALE)

    ok, issues = _validate_export(pdf_bytes, "pdf", expected_keywords)
    if not ok:
        logger.warning("PDF export validation issues: %s", "; ".join(issues))

    return pdf_bytes


def generate_docx_bytes(
    markdown_content: str,
    profile: Optional["Profile"] = None,
    expected_keywords: list[str] | None = None,
) -> bytes:
    """Convert Markdown resume to DOCX bytes."""
    from docx import Document as DocxDocument
    from docx.shared import Pt

    normalized = reorder_and_normalize_markdown(markdown_content)
    contact = build_contact_info(profile)

    doc = DocxDocument()
    _configure_docx_styles(doc)

    if contact.name:
        name_para = doc.add_paragraph()
        name_run = name_para.add_run(contact.name)
        name_run.bold = True
        name_run.font.name = "Calibri"
        name_run.font.size = Pt(NAME_FONT_SIZE)

    _add_docx_contact_paragraph(doc, contact, "Calibri", CONTACT_FONT_SIZE)
    if contact.name or _build_contact_line_parts(contact):
        doc.add_paragraph("")

    for block in parse_markdown_blocks(normalized):
        if block.block_type == BlockType.SPACER:
            doc.add_paragraph("")
        elif block.block_type in (BlockType.HEADING1, BlockType.HEADING2):
            heading = doc.add_heading(block.text, level=1)
            for run in heading.runs:
                run.font.name = "Calibri"
                run.font.size = Pt(HEADING_FONT_SIZE)
                run.font.bold = True
        elif block.block_type == BlockType.HEADING3:
            heading = doc.add_heading(block.text, level=2)
            for run in heading.runs:
                run.font.name = "Calibri"
                run.font.size = Pt(BODY_FONT_SIZE + 1)
                run.font.bold = True
        elif block.block_type == BlockType.BULLET:
            doc.add_paragraph(block.text, style="List Bullet")
        elif block.block_type == BlockType.PARAGRAPH:
            para = doc.add_paragraph(block.text)
            for run in para.runs:
                run.font.name = "Calibri"
                run.font.size = Pt(BODY_FONT_SIZE)

    buffer = BytesIO()
    doc.save(buffer)
    docx_bytes = buffer.getvalue()

    ok, issues = _validate_export(docx_bytes, "docx", expected_keywords)
    if not ok:
        logger.warning("DOCX export validation issues: %s", "; ".join(issues))

    return docx_bytes


def export_resume_pdf(
    markdown_content: str,
    profile: Optional["Profile"] = None,
    expected_keywords: list[str] | None = None,
) -> ExportResult | None:
    """Generate PDF and return bytes with validation result."""
    file_bytes = generate_pdf_bytes(markdown_content, profile, expected_keywords)
    if file_bytes is None:
        return None
    ok, issues = _validate_export(file_bytes, "pdf", expected_keywords)
    return ExportResult(file_bytes=file_bytes, validation_ok=ok, validation_issues=issues)


def export_resume_docx(
    markdown_content: str,
    profile: Optional["Profile"] = None,
    expected_keywords: list[str] | None = None,
) -> ExportResult:
    """Generate DOCX and return bytes with validation result."""
    file_bytes = generate_docx_bytes(markdown_content, profile, expected_keywords)
    ok, issues = _validate_export(file_bytes, "docx", expected_keywords)
    return ExportResult(file_bytes=file_bytes, validation_ok=ok, validation_issues=issues)


__all__ = [
    "BlockType",
    "DocumentBlock",
    "ExportResult",
    "build_contact_info",
    "build_contact_lines",
    "build_resume_filename",
    "export_resume_docx",
    "export_resume_pdf",
    "generate_docx_bytes",
    "generate_pdf_bytes",
    "parse_markdown_blocks",
    "sanitize_filename",
    "strip_markdown_tables",
]
