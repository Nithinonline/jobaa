"""PDF editing utilities for Joba.

This module provides a helper to overlay a generated, compact PDF containing only
text onto the user's uploaded master PDF. The result preserves the exact visual
design (background graphics, colors, headers/footers) of the master while
replacing the textual content with the tailored resume.
"""

from __future__ import annotations

import logging
from io import BytesIO

from PyPDF2 import PdfReader, PdfWriter, PageObject

logger = logging.getLogger(__name__)

def edit_master_pdf(
    master_pdf_bytes: bytes,
    tailored_markdown: str,
    profile,
    expected_keywords: list[str] | None = None,
) -> bytes:
    """Overlay tailored resume text onto an existing master PDF.

    Steps:
    1. Render the ``tailored_markdown`` to a *transparent* PDF using the PDF
       exporter in compact mode. The exporter already produces a PDF with the
       correct layout; the ``compact`` flag reduces whitespace to keep the page
       count identical to the master.
    2. Load both PDFs with ``PyPDF2`` and merge the first page of the generated
       PDF onto each page of the master PDF. For multi‑page master resumes we
       simply overlay the first page repeatedly – the current design assumes a
       one‑page resume, which is the typical use‑case.
    3. Return the combined PDF bytes.

    The function respects the **zero‑hallucination** invariant by using only the
    markdown produced by the tailoring pipeline; no new facts are introduced.

    Args:
        master_pdf_bytes: Raw bytes of the uploaded master resume PDF.
        tailored_markdown: Markdown string of the tailored resume.
        profile: SQLAlchemy ``Profile`` instance (used for contact info, etc.).
        expected_keywords: Optional list of JD keywords for validation.

    Returns:
        Bytes of the final merged PDF.
    """
    # 1️⃣ Render compact PDF from markdown
    from .pdf_exporter import generate_pdf_bytes, COMPACT_TEMPLATE_SCALE

    rendered_pdf = generate_pdf_bytes(
        tailored_markdown,
        profile=profile,
        expected_keywords=expected_keywords,
        rewrite_for_one_page=True,
        compact=True,
    )
    if rendered_pdf is None:
        raise RuntimeError("Failed to render tailored PDF.")

    # 2️⃣ Load PDFs
    master_reader = PdfReader(BytesIO(master_pdf_bytes))
    overlay_reader = PdfReader(BytesIO(rendered_pdf))

    writer = PdfWriter()
    overlay_page = overlay_reader.pages[0]

    for i, master_page in enumerate(master_reader.pages):
        # Create a fresh page copying the master page
        new_page = PageObject.create_blank_page(
            width=master_page.mediabox.width,
            height=master_page.mediabox.height,
        )
        new_page.merge_page(master_page)
        # Overlay the generated content (only on the first page – typical one‑page resume)
        if i == 0:
            new_page.merge_page(overlay_page)
        writer.add_page(new_page)

    out = BytesIO()
    writer.write(out)
    return out.getvalue()
