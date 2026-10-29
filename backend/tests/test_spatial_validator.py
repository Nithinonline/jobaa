from core.spatial_validator import SpatialValidator, count_pdf_pages
from tests.test_layout_analyzer import _create_sample_pdf


def test_count_pdf_pages():
    pdf_bytes = _create_sample_pdf()
    assert count_pdf_pages(pdf_bytes) == 1
    assert count_pdf_pages(b"") == 0


def test_spatial_validator_immediate_pass():
    pdf_bytes = _create_sample_pdf()
    result_bytes, pages, was_compacted = SpatialValidator.enforce_page_budget(
        render_fn=lambda params: pdf_bytes,
        target_page_count=1,
    )
    assert result_bytes == pdf_bytes
    assert pages == 1
    assert was_compacted is False


def test_spatial_validator_compaction_ladder():
    calls = []

    def mock_render(params: dict) -> bytes:
        calls.append(params.copy())
        if "font_scale_offset" in params:
            # Passes on Pass 2
            return _create_sample_pdf()
        # Return a dummy multi-page (simulated by 2 pages)
        from io import BytesIO
        from reportlab.platypus import PageBreak, SimpleDocTemplate, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet
        buf = BytesIO()
        doc = SimpleDocTemplate(buf)
        styles = getSampleStyleSheet()
        doc.build([Paragraph("Page 1", styles["Normal"]), PageBreak(), Paragraph("Page 2", styles["Normal"])])
        return buf.getvalue()

    result_bytes, pages, was_compacted = SpatialValidator.enforce_page_budget(
        render_fn=mock_render,
        target_page_count=1,
    )
    assert pages == 1
    assert was_compacted is True
    assert len(calls) >= 2
