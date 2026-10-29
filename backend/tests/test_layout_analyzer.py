from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.lib.styles import ParagraphStyle

from core.layout_analyzer import analyze_master_layout, extract_pdf_layout
from core.layout_schema import MasterLayoutProfile


def _create_sample_pdf() -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.4 * inch,
        bottomMargin=0.4 * inch,
    )
    title_style = ParagraphStyle(
        "Title",
        fontSize=20,
        textColor=colors.HexColor("#1f497d"),
    )
    heading_style = ParagraphStyle(
        "Heading",
        fontSize=12,
        textColor=colors.HexColor("#1f497d"),
        spaceAfter=4,
    )
    body_style = ParagraphStyle("Body", fontSize=9.5, spaceAfter=2)

    story = [
        Paragraph("Alex Developer", title_style),
        Paragraph("alex@example.com | 555-0100 | London, UK", body_style),
        Spacer(1, 0.1 * inch),
        Paragraph("EXPERIENCE", heading_style),
        Paragraph("Senior Engineer, TechCorp (2020 - Present)", body_style),
        Paragraph("- Architected scalable microservices using Python and FastAPI.", body_style),
        Paragraph("- Managed AWS Kubernetes deployments with 99.99% uptime.", body_style),
        Spacer(1, 0.1 * inch),
        Paragraph("SKILLS", heading_style),
        Paragraph("Python, FastAPI, Docker, Kubernetes, PostgreSQL", body_style),
        Spacer(1, 0.1 * inch),
        Paragraph("EDUCATION", heading_style),
        Paragraph("B.S. in Computer Science, University of London", body_style),
    ]
    doc.build(story)
    return buf.getvalue()


def test_pdf_layout_extraction():
    pdf_bytes = _create_sample_pdf()
    raw_text = """Alex Developer
alex@example.com | 555-0100 | London, UK

EXPERIENCE
Senior Engineer, TechCorp (2020 - Present)
- Architected scalable microservices using Python and FastAPI.
- Managed AWS Kubernetes deployments with 99.99% uptime.

SKILLS
Python, FastAPI, Docker, Kubernetes, PostgreSQL

EDUCATION
B.S. in Computer Science, University of London
"""
    profile = analyze_master_layout(pdf_bytes, "alex_resume.pdf", raw_text=raw_text)

    assert profile.file_format == "pdf"
    assert profile.page_count == 1
    assert 0.3 <= profile.spacing.margin_left_inches <= 0.8
    assert profile.name_font_size >= 16.0
    assert profile.body_font_size > 8.0
    assert profile.primary_color in ("#1f497d", "#1f497c")

    budget = profile.derive_layout_budget()
    assert budget.target_page_count == 1
    assert budget.max_summary_chars > 0
    assert len(budget.experience_budgets) >= 1
    exp_0 = budget.experience_budgets[0]
    assert exp_0.max_bullets >= 1


def test_txt_layout_fallback():
    raw_text = "Jane Doe\n\nEXPERIENCE\n- Bullet 1\n- Bullet 2"
    profile = analyze_master_layout(b"", "resume.txt", raw_text=raw_text)
    assert profile.file_format == "txt"
    assert profile.page_count == 1
    assert "Work Experience" in profile.section_order
