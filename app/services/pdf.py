"""Helpers for rendering stand sheet templates into PDF documents."""

from __future__ import annotations

from io import BytesIO
from typing import Mapping, Sequence, Tuple

from flask import current_app, render_template
from pypdf import PdfWriter
from weasyprint import HTML

PDFPage = Tuple[str, Mapping[str, object]]


def _render_html_to_pdf(html: str) -> bytes:
    """Render an HTML string to a PDF byte string."""
    output = BytesIO()
    try:
        HTML(string=html, base_url=current_app.root_path).write_pdf(output)
        return output.getvalue()
    finally:
        output.close()


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

    pdf_pages = []
    for template_name, context in pages:
        html = render_template(template_name, **context)
        pdf_pages.append(_render_html_to_pdf(html))

    if len(pdf_pages) == 1:
        return pdf_pages[0]

    writer = PdfWriter()
    streams = []
    try:
        for pdf_bytes in pdf_pages:
            stream = BytesIO(pdf_bytes)
            streams.append(stream)
            writer.append(stream)
        output = BytesIO()
        writer.write(output)
        data = output.getvalue()
        output.close()
        return data
    finally:
        writer.close()
        for stream in streams:
            stream.close()
