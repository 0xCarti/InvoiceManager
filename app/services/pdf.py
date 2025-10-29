"""Helpers for rendering stand sheet templates into PDF documents."""

from __future__ import annotations

from io import BytesIO
from typing import Mapping, Sequence, Tuple

from flask import current_app, render_template
from pypdf import PdfMerger
from weasyprint import HTML

PDFPage = Tuple[str, Mapping[str, object]]


def _render_html_to_pdf(html: str) -> BytesIO:
    """Render an HTML string to a PDF byte stream."""
    pdf_stream = BytesIO()
    HTML(string=html, base_url=current_app.root_path).write_pdf(pdf_stream)
    pdf_stream.seek(0)
    return pdf_stream


def render_stand_sheet_pdf(pages: Sequence[PDFPage]) -> bytes:
    """Render one or more stand sheet templates into a merged PDF.

    Args:
        pages: A sequence of ``(template_name, context)`` tuples representing the
            Jinja templates and values that should be rendered into the
            resulting PDF.  Each template is rendered with ``render_template``
            and converted to PDF before the pages are combined.

    Returns:
        A ``bytes`` object containing the merged PDF document.

    Raises:
        ValueError: If ``pages`` is empty.
    """

    if not pages:
        raise ValueError("At least one template must be provided")

    pdf_streams = []
    for template_name, context in pages:
        html = render_template(template_name, **context)
        pdf_streams.append(_render_html_to_pdf(html))

    if len(pdf_streams) == 1:
        try:
            return pdf_streams[0].getvalue()
        finally:
            pdf_streams[0].close()

    merger = PdfMerger()
    try:
        for stream in pdf_streams:
            merger.append(stream)
        output = BytesIO()
        merger.write(output)
        data = output.getvalue()
        output.close()
        return data
    finally:
        merger.close()
        for stream in pdf_streams:
            stream.close()
