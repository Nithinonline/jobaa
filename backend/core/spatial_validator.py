"""Deterministic spatial validation and compaction ladder for 1-page resume fit."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def count_pdf_pages(pdf_bytes: bytes) -> int:
    """Count pages in PDF bytes safely."""
    if not pdf_bytes:
        return 0
    try:
        import pdfplumber
        from io import BytesIO

        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            return len(pdf.pages)
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        from io import BytesIO

        return len(PdfReader(BytesIO(pdf_bytes)).pages)
    except Exception:
        return 1


class SpatialValidator:
    """
    Enforces that rendered resume documents strictly adhere to target page count (default 1 page)
    using a deterministic 4-step compaction ladder.
    """

    @classmethod
    def enforce_page_budget(
        cls,
        *,
        render_fn: Callable[[dict[str, Any]], bytes | None],
        target_page_count: int = 1,
        initial_params: dict[str, Any] | None = None,
        trim_bullet_fn: Callable[[], bool] | None = None,
    ) -> tuple[bytes | None, int, bool]:
        """
        Executes rendering with progressive compaction ladder until page count <= target_page_count.
        Returns (pdf_bytes, final_page_count, is_compacted).
        """
        params = dict(initial_params or {})
        pdf_bytes = render_fn(params)
        if not pdf_bytes:
            return None, 0, False

        pages = count_pdf_pages(pdf_bytes)
        if pages <= target_page_count:
            return pdf_bytes, pages, False

        logger.info(
            "Spatial validator: output has %d pages, target is %d. Starting compaction ladder.",
            pages,
            target_page_count,
        )

        # Pass 1: Tighten line spacing / section gap
        params["section_gap_factor"] = 0.8
        params["line_leading_offset"] = -0.4
        pdf_bytes = render_fn(params)
        pages = count_pdf_pages(pdf_bytes or b"")
        if pages <= target_page_count:
            logger.info("Spatial validator: passed at Pass 1 (gap tightening).")
            return pdf_bytes, pages, True

        # Pass 2: Tighten font size slightly (-0.3 pt)
        params["font_scale_offset"] = -0.3
        params["margin_squeeze_offset"] = -0.05
        pdf_bytes = render_fn(params)
        pages = count_pdf_pages(pdf_bytes or b"")
        if pages <= target_page_count:
            logger.info("Spatial validator: passed at Pass 2 (font scale & margin squeeze).")
            return pdf_bytes, pages, True

        # Pass 3: Deterministic bullet trimming if callback provided
        if trim_bullet_fn:
            for _ in range(3):
                if not trim_bullet_fn():
                    break
                pdf_bytes = render_fn(params)
                pages = count_pdf_pages(pdf_bytes or b"")
                if pages <= target_page_count:
                    logger.info("Spatial validator: passed at Pass 3 (bullet trimming).")
                    return pdf_bytes, pages, True

        # Pass 4: Maximum safe compaction
        params["font_scale_offset"] = -0.6
        params["line_leading_offset"] = -0.8
        params["margin_squeeze_offset"] = -0.1
        pdf_bytes = render_fn(params)
        pages = count_pdf_pages(pdf_bytes or b"")
        logger.info("Spatial validator: finalized at %d pages.", pages)
        return pdf_bytes, pages, True
