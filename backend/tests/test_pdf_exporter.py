import json
import zipfile
from io import BytesIO
from unittest.mock import patch

import pdfplumber

from core.ats_constants import (
    DATE_PATTERN,
    normalize_section_heading,
    reorder_and_normalize_markdown,
)
from core.ats_scorer import validate_ats_format
from core.pdf_exporter import (
    build_contact_lines,
    build_resume_filename,
    _clean_generated_text,
    export_resume_docx,
    export_resume_pdf,
    generate_pdf_bytes,
    parse_markdown_blocks,
    sanitize_filename,
    strip_markdown_tables,
)
from core.resume_validator import validate_exported_resume
from db.models import Profile


SAMPLE_RESUME = """# Should be ignored as heading
## Professional Summary
Experienced software engineer with Python expertise.
## Skills
- Technical skill : Python, SQL, AWS, REST APIs
- Soft skill : Collaboration, Communication
## Work Experience
### Acme Corp — Engineer
Acme Corp, Austin, TX | January 2020 - Present
- Built REST APIs serving 1M requests/day
## Education
### B.S. Computer Science
State University, Austin, TX | May 2019
"""


LONG_AI_RESUME = """## Professional Summary
AI/ML Engineer with experience designing production-grade AI systems, LLM applications, RAG pipelines, computer vision workflows, MLOps practices, backend services, and distributed data pipelines for logistics technology.

## Skills
- AI/ML : Python, PyTorch, OpenAI, Hugging Face, LangChain, Generative AI, Machine Learning, AI/ML models, NLP, RAG, Vector Search, Embeddings
- Data Engineering & MLOps : Apache Airflow, Apache Kafka, ETL Pipelines, Data Pipelines, PostgreSQL, Redis, Model Serving, Experimentation, Production AI Systems, AI Infrastructure
- Backend Development : Python, Django, FastAPI, REST APIs, Microservices, API Design, Third-Party Integrations, Authentication, Background Processing, Production Backend Systems
- Frontend Development : React.js, Angular, JavaScript, HTML, CSS
- Databases & Storage : PostgreSQL, MongoDB, Redis, SQL, Data Modeling
- Software Engineering : System Design, Scalable Architecture, Distributed Systems, Performance Optimization, Debugging, Production Deployments, Agile Development, Version Control (Git), Cross-functional Collaboration
- Business Intelligence & Reporting : Business Intelligence, Reporting Automation, Logistics Technology, Third-Party API Integration, Scalable Systems, Model Monitoring, Data Pipelines, Innovation, Problem Solving

## Work Experience
## Software Engineer
QWY Software Pvt Ltd, Trivandrum, Kerala | April 2024 - Present
- Designed, developed, and delivered production-ready software features using Django, FastAPI, Angular, React, PostgreSQL, Redis, Docker, and related technologies.
- Developed statistical and machine learning models for forecasting, anomaly detection, and ranking, owning the end-to-end lifecycle including data pipeline development, preprocessing, feature engineering, model training, evaluation, and accuracy improvement.
- Built an end-to-end computer vision solution using PyTorch for automated proof-of-delivery validation, including preprocessing, model training, evaluation, and deployment.
- Built a production-grade AI chat agent using FastAPI, LangGraph, LangChain, PostgreSQL, pgvector, Groq, OpenAI, embeddings, and MCP-based tool shortcuts.
- Built automated data pipelines with Apache Airflow for transforming operational data into actionable business insights.
- Reduced manual operational effort by 70-80% through automation and analytics solutions that streamlined repetitive processes.
## Full Stack Developer Intern
Menterow Technologies, Ernakulam, Kerala | July 2023 - February 2024
- Developed backend applications using Node.js and MongoDB, building scalable RESTful APIs and data-driven features.
- Designed and implemented frontend components for internal and customer-facing applications.
- Strengthened API design and database architecture fundamentals now applied to agentic system design.

## Education
## Bachelor of Computer Application
St Thomas College, Pala, Kottayam | March 2023

## Certifications
- Advanced Learning Algorithms
- Supervised Machine Learning: Regression and Classification
- SQL for Data Analysis: Advanced SQL Querying Techniques
- The Ultimate Django Certification
"""


def _make_profile() -> Profile:
    return Profile(
        full_name="Jane Doe",
        email="jane@example.com",
        phone="555-0100",
        location="Austin, TX",
        linkedin="linkedin.com/in/janedoe",
    )


def test_strip_markdown_tables_removes_table_lines() -> None:
    content = "## Skills\n| Skill | Level |\n| --- | --- |\n| Python | Expert |"
    cleaned = strip_markdown_tables(content)
    assert "|" not in cleaned
    assert "## Skills" in cleaned


def test_clean_generated_text_removes_markdown_and_encoding_artifacts() -> None:
    cleaned = _clean_generated_text("**LLM**■powered model → retrieval")
    assert cleaned == "LLM-powered model -> retrieval"
    assert "**" not in cleaned
    assert "■" not in cleaned


def test_parse_markdown_blocks() -> None:
    blocks = parse_markdown_blocks(SAMPLE_RESUME)
    types = [block.block_type.value for block in blocks]
    assert "heading2" in types
    assert "bullet" in types
    assert "paragraph" in types


def test_build_contact_lines_single_line() -> None:
    lines = build_contact_lines(_make_profile())
    assert lines[0] == "Jane Doe"
    assert "jane@example.com" in lines[1]
    assert "linkedin.com/in/janedoe" in lines[1]
    assert len(lines) == 2


def test_normalize_section_heading() -> None:
    assert normalize_section_heading("Summary") == "Professional Summary"
    assert normalize_section_heading("Work Experience") == "Work Experience"
    assert normalize_section_heading("Random") is None


def test_reorder_and_normalize_markdown() -> None:
    raw = """## Experience
Worked at Acme.
## Summary
Engineer.
## Skills
Python.
## Education
B.S. CS.
"""
    normalized = reorder_and_normalize_markdown(raw)
    summary_idx = normalized.index("## Professional Summary")
    skills_idx = normalized.index("## Skills")
    exp_idx = normalized.index("## Work Experience")
    edu_idx = normalized.index("## Education")
    assert summary_idx < skills_idx < exp_idx < edu_idx


def test_date_pattern_accepts_full_month() -> None:
    assert DATE_PATTERN.search("January 2022 - Present")
    assert DATE_PATTERN.search("March 2019 - June 2021")


def test_date_pattern_rejects_abbreviation() -> None:
    assert not DATE_PATTERN.search("Jan 2022 - Present")


def test_generate_pdf_bytes_contains_sections() -> None:
    result = export_resume_pdf(SAMPLE_RESUME, _make_profile())
    assert result is not None

    with pdfplumber.open(BytesIO(result.file_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages).lower()

    assert "jane doe" in text
    assert "professional summary" in text
    assert "skill" in text
    assert "experience" in text
    assert "education" in text
    assert "mailto:jane@example.com" in result.file_bytes.decode("latin-1", errors="ignore") or "jane@example.com" in text


def test_generate_docx_bytes_returns_content() -> None:
    result = export_resume_docx(SAMPLE_RESUME, _make_profile())
    assert result.file_bytes[:2] == b"PK"


def test_docx_contains_email_hyperlink() -> None:
    result = export_resume_docx(SAMPLE_RESUME, _make_profile())
    with zipfile.ZipFile(BytesIO(result.file_bytes)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
        rels = zf.read("word/_rels/document.xml.rels").decode("utf-8")
    assert "w:hyperlink" in xml
    assert "mailto:jane@example.com" in rels


def test_validate_exported_resume_reading_order() -> None:
    result = export_resume_pdf(SAMPLE_RESUME, _make_profile())
    assert result is not None
    ok, issues = validate_exported_resume(result.file_bytes, "pdf")
    assert ok, issues


def test_template_pdf_keeps_required_sections_for_oversized_content() -> None:
    pdf_bytes = generate_pdf_bytes(
        LONG_AI_RESUME,
        _make_profile(),
        ["Python", "FastAPI", "LangChain", "RAG"],
        job_title="AI Engineer",
    )
    assert pdf_bytes is not None

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        assert len(pdf.pages) == 1
        text = "\n".join(page.extract_text() or "" for page in pdf.pages).lower()

    assert "professional summary" in text
    assert "skills" in text
    assert "experience" in text
    assert "education" in text
    assert "certifications" in text


def test_one_page_rewrite_falls_back_when_llm_output_is_invalid() -> None:
    with patch("core.llm_client.llm_client.generate", return_value="## Skills\n- Python"):
        pdf_bytes = generate_pdf_bytes(
            LONG_AI_RESUME,
            _make_profile(),
            ["Python", "FastAPI", "LangChain", "RAG"],
            job_title="AI Engineer",
            profile_text="AI engineer profile",
            rewrite_for_one_page=True,
        )
    assert pdf_bytes is not None

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        assert len(pdf.pages) == 1
        text = "\n".join(page.extract_text() or "" for page in pdf.pages).lower()

    assert "experience" in text
    assert "education" in text
    assert "certifications" in text


def test_sanitize_filename() -> None:
    assert sanitize_filename("Senior SWE (Remote)") == "Senior_SWE_Remote"
    assert sanitize_filename("") == "Resume"


def test_build_resume_filename() -> None:
    filename = build_resume_filename(_make_profile(), "Backend Engineer")
    assert filename == "Jane_Doe_Backend_Engineer_Resume.pdf"
