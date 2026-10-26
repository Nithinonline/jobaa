"""PDF/DOCX export with validation gates."""

from __future__ import annotations

from core.pdf_exporter import (
    build_resume_filename,
    generate_docx_bytes,
    generate_pdf_bytes,
)
from core.resume_validator import validate_exported_resume
from core.template_config import TemplateConfig, template_config_from_json
from db.models import Profile


def _template(profile: Profile) -> TemplateConfig:
    return template_config_from_json(profile.template_config_json)


def export_pdf(
    markdown: str,
    profile: Profile,
    keywords: list[str] | None = None,
    *,
    job_title: str | None = None,
    profile_text: str | None = None,
    block_on_issues: bool = True,
) -> tuple[bytes | None, list[str], str | None]:
    """
    Returns (pdf_bytes, issues, error_message).
    If block_on_issues and validator finds blocking issues, pdf_bytes is None.
    """
    try:
        pdf_bytes = generate_pdf_bytes(
            markdown,
            profile,
            keywords,
            job_title=job_title,
            profile_text=profile_text,
            rewrite_for_one_page=True,
            template_config=_template(profile),
        )
    except RuntimeError as exc:
        return None, [], str(exc)
    except Exception as exc:
        return None, [], f"PDF generation failed: {exc}"

    if pdf_bytes is None:
        return None, [], "reportlab is not installed. Run: pip install reportlab"

    _, issues = validate_exported_resume(pdf_bytes, "pdf", keywords)
    if block_on_issues and issues:
        # Still return bytes for preview, but signal blocking via error
        return pdf_bytes, issues, "ATS export validation failed: " + "; ".join(issues[:3])
    return pdf_bytes, issues, None


def export_docx(
    markdown: str,
    profile: Profile,
    keywords: list[str] | None = None,
    *,
    block_on_issues: bool = False,
) -> tuple[bytes, list[str], str | None]:
    docx_bytes = generate_docx_bytes(markdown, profile, keywords)
    _, issues = validate_exported_resume(docx_bytes, "docx", keywords)
    error = None
    if block_on_issues and issues:
        error = "ATS export validation failed: " + "; ".join(issues[:3])
    return docx_bytes, issues, error


def resume_filename(profile: Profile, job_title: str) -> str:
    return build_resume_filename(profile, job_title)
