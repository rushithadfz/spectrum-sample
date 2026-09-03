"""
PDF rendering for reports.

Built straight from the same (columns, rows) a report builder returns, so a
downloaded PDF, the CSV and the table on screen are the same data by
construction - there is no second code path to fall out of step.

Laid out by hand rather than with a table flowable: these reports are wide
and the column widths have to come from the content, otherwise long agent
names collide with the figures next to them.
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

NAVY = colors.HexColor("#001b33")
BLUE = colors.HexColor("#0073d1")
GREY = colors.HexColor("#5b6b7b")
RULE = colors.HexColor("#d9e2ea")

PAGE = landscape(A4)
MARGIN = 14 * mm
ROW_H = 6.2 * mm
HEAD_H = 26 * mm
FONT = "Helvetica"
BOLD = "Helvetica-Bold"


def _column_widths(cols, rows, available):
    """
    Width by content: the widest cell in each column, then scaled to fit the
    page. A fixed split makes one column wrap on every row and leaves another
    two-thirds empty.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    widest = []
    for i, col in enumerate(cols):
        w = stringWidth(str(col), BOLD, 7.5)
        for row in rows[:400]:               # enough to be representative
            if i < len(row):
                w = max(w, stringWidth(str(row[i]), FONT, 7.5))
        widest.append(w + 8)

    total = sum(widest) or 1
    if total <= available:
        return widest
    scale = available / total
    # Nothing shrinks below a legible floor; the surplus comes off the rest.
    return [max(w * scale, 16 * mm) for w in widest]


def _truncate(c, text, width, font, size):
    from reportlab.pdfbase.pdfmetrics import stringWidth

    text = str(text)
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "\u2026", font, size) > width:
        text = text[:-1]
    return text + "\u2026"


def _header(c, title, blurb, meta, page_no):
    w, h = PAGE
    c.setFillColor(NAVY)
    c.rect(0, h - 18 * mm, w, 18 * mm, stroke=0, fill=1)

    c.setFillColor(colors.white)
    c.setFont(BOLD, 13)
    c.drawString(MARGIN, h - 11.5 * mm, title)

    c.setFillColor(colors.HexColor("#7fc4f2"))
    c.setFont(FONT, 8)
    c.drawRightString(w - MARGIN, h - 11.5 * mm, "Spectrum Incentive Portal")

    c.setFillColor(GREY)
    c.setFont(FONT, 8)
    c.drawString(MARGIN, h - 24 * mm, blurb)
    c.drawRightString(w - MARGIN, h - 24 * mm, meta)

    c.setStrokeColor(NAVY)
    c.setLineWidth(1)
    c.line(MARGIN, h - 27 * mm, w - MARGIN, h - 27 * mm)

    c.setFillColor(GREY)
    c.setFont(FONT, 7.5)
    c.drawRightString(w - MARGIN, 9 * mm, f"Page {page_no}")


def render_report(cols, rows, title, blurb, meta):
    """Return the PDF for one report as bytes."""
    import io

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=PAGE)
    c.setTitle(title)

    w, h = PAGE
    widths = _column_widths(cols, rows, w - 2 * MARGIN)
    top = h - HEAD_H - 6 * mm
    bottom = 16 * mm

    page_no = 1
    _header(c, title, blurb, meta, page_no)

    def column_heads(y):
        c.setFont(BOLD, 7.5)
        c.setFillColor(GREY)
        x = MARGIN
        for i, col in enumerate(cols):
            c.drawString(x, y, _truncate(c, str(col).upper(), widths[i], BOLD, 7.5))
            x += widths[i]
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(MARGIN, y - 2.2 * mm, w - MARGIN, y - 2.2 * mm)
        return y - 2.2 * mm - ROW_H

    y = column_heads(top)

    for n, row in enumerate(rows):
        if y < bottom:
            c.showPage()
            page_no += 1
            _header(c, title, blurb, meta, page_no)
            y = column_heads(top)

        if n % 2:                                   # a quiet band, not a grid
            c.setFillColor(colors.HexColor("#f4f8fc"))
            c.rect(MARGIN - 2, y - 1.6 * mm, w - 2 * MARGIN + 4, ROW_H, stroke=0, fill=1)

        c.setFont(FONT, 7.5)
        x = MARGIN
        for i, cell in enumerate(row):
            c.setFillColor(NAVY if i == 0 else colors.HexColor("#22384d"))
            if i == 0:
                c.setFont(BOLD, 7.5)
            c.drawString(x, y, _truncate(c, cell, widths[i] - 4, FONT, 7.5))
            if i == 0:
                c.setFont(FONT, 7.5)
            x += widths[i]
        y -= ROW_H

    if not rows:
        c.setFont(FONT, 9)
        c.setFillColor(GREY)
        c.drawString(MARGIN, top - 10 * mm, "No rows for this report in the current scope.")

    c.setFont(FONT, 7.5)
    c.setFillColor(BLUE)
    c.drawString(MARGIN, 9 * mm, f"{len(rows)} row(s)")

    c.showPage()
    c.save()
    return buf.getvalue()
