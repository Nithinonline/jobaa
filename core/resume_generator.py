"""Resume generation and refinement logic."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from core.ats_constants import CANONICAL_SECTIONS, reorder_and_normalize_markdown
from core.ats_scorer import score_resume, validate_ats_format
from core.config_loader import get_thresholds
from core.jd_parser import format_jd_for_prompt, get_priority_keywords
from core.llm_client import llm_client

if TYPE_CHECKING:
    from db.models import JobDescription


def _section_order_text(section_order: list[str] | None) -> str:
    order = section_order or CANONICAL_SECTIONS
    return " → ".join(order)


def _build_initial_prompt(
    profile_text: str,
    jd_prompt_text: str,
    priority_keywords: list[str],
    *,
    allowed_skills: list[str] | None = None,
    selected_experience_ids: list[str] | None = None,
    section_order: list[str] | None = None,
) -> str:
    priority_block = ""
    if priority_keywords:
        priority_block = f"\nPriority JD terms to incorporate where truthful: {', '.join(priority_keywords)}\n"

    constraint_block = ""
    if allowed_skills:
        constraint_block += (
            "\nAllowed skills (use only these unless listed in the profile): "
            + ", ".join(allowed_skills)
            + "\n"
        )
    if selected_experience_ids:
        constraint_block += (
            "\nOnly include experience entries with these ids (or matching titles): "
            + ", ".join(selected_experience_ids)
            + "\n"
        )

    order_text = _section_order_text(section_order)

    return f"""You are writing an ATS-optimized resume in Markdown format.

Profile:
{profile_text}

Job Description:
{jd_prompt_text}
{priority_block}{constraint_block}
Requirements:
- Use EXACTLY these ## section headings in this order: {order_text}
- Omit Certifications section only if profile has no certifications
- Do NOT include a contact header — contact info is added separately in the exported document
- Match keywords from the JD naturally; use exact JD terminology where truthful
- Map required JD skills into Skills and Work Experience bullets
- Quantify achievements where possible
- Reorder skills to match JD priority
- Markdown ONLY: plain headings (# ## ###), bullet lists (- item) for experience and skills
- Skills section: 3-5 bullet lines using "Category : item, item" format (see structure below)
- NO tables, NO multi-column layouts, NO icons, NO skill rating bars
- Do not invent experience or skills — only use content from the profile and explicitly allowed skills

Date format (required on every role and education entry):
- Use full month names: "January 2022 - Present" or "March 2019 - June 2021"
- Never use abbreviations like Jan, Mar, or year-only ranges like 2020-2023

Work Experience structure:
## Work Experience
### Job Title
Company Name, City, State | January 2022 - Present
- Accomplishment bullet with JD keyword naturally included

Education structure:
## Education
### Degree Name, Major
University Name, City, State | Graduation Month Year

Skills structure:
## Skills
- Technical skill : Python, SQL, AWS, REST APIs
- Soft skill : Collaboration, Communication, Problem solving
- Language : English (Fluent)
"""


def _build_refinement_prompt(
    markdown_content: str,
    jd_prompt_text: str,
    iteration: int,
    max_iterations: int,
    missing_keywords: list[str],
    format_issues: list[str],
    priority_keywords: list[str],
    *,
    allowed_skills: list[str] | None = None,
    section_order: list[str] | None = None,
) -> str:
    missing_block = ""
    if missing_keywords:
        missing_block = (
            "\nNaturally incorporate these JD terms if supported by the profile: "
            + ", ".join(missing_keywords)
        )

    issues_block = ""
    if format_issues:
        issues_block = "\nFix these ATS format issues: " + "; ".join(format_issues)

    priority_block = ""
    if priority_keywords:
        priority_block = "\nEmphasize these priority skills: " + ", ".join(priority_keywords)

    skill_block = ""
    if allowed_skills:
        skill_block = "\nOnly use these skills: " + ", ".join(allowed_skills)

    order_text = _section_order_text(section_order)

    return f"""Improve the following resume so it better matches the job description and is more ATS-friendly.
Iteration {iteration}/{max_iterations}

Current Resume:
{markdown_content}

Job Description:
{jd_prompt_text}
{missing_block}{issues_block}{priority_block}{skill_block}

Focus on:
- Using exact section headings: {order_text}
- Emphasizing high-impact keywords from the JD using exact terminology
- Skills as categorized bullet lines ("Category : item, item"); experience bullets with - prefix
- Dates in "Month Year - Month Year" format with full month names
- Reorganizing skills section with most relevant at the top
- Improving readability for ATS systems
- Keeping all content truthful — do not invent experience
"""


def generate_resume(
    profile_text: str,
    jd_text: str,
    max_iterations: Optional[int] = None,
    jd: Optional["JobDescription"] = None,
    *,
    allowed_skills: list[str] | None = None,
    selected_experience_ids: list[str] | None = None,
    section_order: list[str] | None = None,
) -> dict:
    """
    Generate and iteratively refine a resume.

    Args:
        profile_text: Combined profile information
        jd_text: Job description text (raw or formatted)
        max_iterations: Maximum number of refinement iterations
        jd: Optional structured JobDescription for weighted scoring
        allowed_skills: Optional skill whitelist from agent approvals
        selected_experience_ids: Optional experience ids to include
        section_order: Optional section order from master template

    Returns:
        Dictionary with markdown_content, ats_score, improvements, missing_keywords
    """
    thresholds = get_thresholds()
    target_ats_score = thresholds["ats_score"]
    if max_iterations is None:
        max_iterations = int(thresholds["max_iterations"])

    jd_prompt_text = format_jd_for_prompt(jd) if jd is not None else jd_text
    priority_keywords = get_priority_keywords(jd) if jd is not None else []
    order_text = _section_order_text(section_order)

    initial_prompt = _build_initial_prompt(
        profile_text,
        jd_prompt_text,
        priority_keywords,
        allowed_skills=allowed_skills,
        selected_experience_ids=selected_experience_ids,
        section_order=section_order,
    )

    markdown_content = ""
    final_ats_score = 0.0
    final_summary = ""
    final_missing_keywords: list[str] = []
    last_format_issues: list[str] = []

    for iteration in range(1, max_iterations + 1):
        if iteration == 1:
            prompt = initial_prompt
        else:
            prompt = _build_refinement_prompt(
                markdown_content,
                jd_prompt_text,
                iteration,
                max_iterations,
                final_missing_keywords,
                last_format_issues,
                priority_keywords,
                allowed_skills=allowed_skills,
                section_order=section_order,
            )

        candidate_resume = llm_client.generate(prompt)
        if not candidate_resume or not candidate_resume.strip():
            raise ValueError(f"No resume content generated at iteration {iteration}")

        is_valid, issues = validate_ats_format(candidate_resume)
        last_format_issues = issues
        if not is_valid:
            repair_prompt = f"""Rewrite the resume so it is ATS-friendly:
- Use exact ## headings: {order_text}
- NO tables, NO multi-column layouts
- Skills as categorized bullet lines (not a comma-separated paragraph)
- Dates: full month name format (January 2022 - Present)
- Keep all original content truthful

Issues to fix: {"; ".join(issues)}

Current Resume:
{candidate_resume}
"""
            candidate_resume = llm_client.generate(repair_prompt)
            is_valid, last_format_issues = validate_ats_format(candidate_resume)

        markdown_content = reorder_and_normalize_markdown(
            candidate_resume,
            section_order=section_order,
        )
        ats_score, summary, missing_keywords = score_resume(markdown_content, jd_text, jd=jd)
        final_ats_score = ats_score
        final_summary = summary
        final_missing_keywords = missing_keywords

        if ats_score >= target_ats_score:
            break

    return {
        "markdown_content": markdown_content,
        "ats_score": final_ats_score,
        "improvements": final_summary,
        "missing_keywords": final_missing_keywords,
    }
