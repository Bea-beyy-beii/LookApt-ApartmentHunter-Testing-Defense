# core_landlords/export.py
# "Export Financials": the Monthly Receivables of one month as a PDF
# (text and tables only), built with ReportLab.
#
# Amounts are written as "PHP 8,000": the PDF's built-in fonts have no ₱ sign.
from io import BytesIO

from django.utils import timezone
from django.utils.html import escape   # Paragraph() reads <b>, &amp; ... as markup
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = colors.HexColor("#203a68")
LINE = colors.HexColor("#d9dee8")
STRIPE = colors.HexColor("#f4f6fa")
MUTED = colors.HexColor("#5f6b7f")

STATUS_LABELS = {"paid": "Paid", "overdue": "Overdue", "due_soon": "Due Soon", "not_due": "Upcoming"}


def php(amount):
    return f"PHP {amount:,.0f}"


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], alignment=0, textColor=NAVY, fontSize=19, spaceAfter=2),
        "sub": ParagraphStyle("sub", parent=base["Normal"], textColor=MUTED, fontSize=9.5, leading=13),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], textColor=NAVY, fontSize=12.5, spaceBefore=12, spaceAfter=5),
        "note": ParagraphStyle("note", parent=base["Normal"], textColor=MUTED, fontSize=8.5, spaceAfter=5),
        "body": ParagraphStyle("body", parent=base["Normal"], fontSize=9.5, leading=13),
        "big": ParagraphStyle("big", parent=base["Normal"], fontSize=12, leading=16, textColor=NAVY),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8.5, leading=11),
        "right": ParagraphStyle("right", parent=base["Normal"], fontSize=8.5, leading=11, alignment=TA_RIGHT),
    }


def _table(rows, widths, money_cols=(), total=False):
    """Header row in navy, striped body, money columns right-aligned."""
    table = Table(rows, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, STRIPE]),
    ]
    for col in money_cols:
        style.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    if total:
        style += [
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8edf6")),
            ("LINEABOVE", (0, -1), (-1, -1), 1, NAVY),
        ]
    table.setStyle(TableStyle(style))
    return table


def _due_table(rows, s, width):
    """Due Date | Unit | Property | Tenant | Amount | Status"""
    data = [["Due Date", "Unit", "Property", "Tenant", "Amount", "Status"]]
    for row in rows:
        data.append([
            row["due"].strftime("%b %d, %Y"),
            row["unit"].unit_name,
            Paragraph(escape(row["unit"].complex.complex_name), s["cell"]),
            Paragraph(escape(row["tenancy"].tenant_name or "-"), s["cell"]),
            php(row["amount"]),
            STATUS_LABELS.get(row["status"], row["status"]),
        ])
    return _table(data, [x * width for x in (0.14, 0.11, 0.25, 0.22, 0.15, 0.13)], money_cols=(4,))


def receivables_pdf(user, r):
    """r = core_landlords.services.receivables(). Returns the PDF bytes."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Monthly Receivables - {r['month_label']}", author="LookApt",
    )
    width = doc.width
    s = _styles()
    generated = timezone.localtime().strftime("%b %d, %Y %I:%M %p")
    story = []

    # ---------- Title ----------
    story += [
        Paragraph(f"Monthly Receivables: {r['month_label']}", s["title"]),
        Paragraph(f"{escape(user.display_name)} &middot; LookApt &middot; Generated {generated}", s["sub"]),
        Spacer(1, 10),
        Paragraph(
            f"<b>{php(r['paid']['amount'])}</b> of {php(r['expected']['amount'])} collected "
            f"(<b>{r['percent']}%</b>)", s["big"],
        ),
        Spacer(1, 4),
    ]

    # ---------- Summary ----------
    story.append(Paragraph("Summary", s["h2"]))
    summary = [["Status", "Due Dates", "Amount"]]
    for label, key in (("Paid", "paid"), ("Overdue", "overdue"), ("Due in the next 7 days", "due_soon"),
                       ("Not yet due", "not_due")):
        summary.append([label, r[key]["count"], php(r[key]["amount"])])
    summary.append(["Total expected", r["expected"]["count"], php(r["expected"]["amount"])])
    story.append(_table(summary, [width * 0.5, width * 0.2, width * 0.3], money_cols=(1, 2), total=True))

    # ---------- Expected income by rate ----------
    story += [
        Paragraph("Expected Rental Income", s["h2"]),
        Paragraph("From every unit with rent due this month, grouped by monthly rate.", s["note"]),
    ]
    if r["breakdown"]:
        breakdown = [["Monthly Rate", "Units", "Expected"]]
        breakdown += [[php(row["rate"]), row["units"], php(row["amount"])] for row in r["breakdown"]]
        breakdown.append(["Total", r["expected"]["count"], php(r["expected"]["amount"])])
        story.append(_table(breakdown, [width * 0.4, width * 0.25, width * 0.35], money_cols=(0, 1, 2), total=True))
    else:
        story.append(Paragraph("No rent is due this month.", s["body"]))

    # ---------- Due dates ----------
    sections = (
        ("Overdue", r["overdue_rows"], "Nothing overdue this month."),
        ("Upcoming", r["upcoming"], "No upcoming due dates this month."),
        ("Paid", r["paid_rows"], "No payments recorded for this month yet."),
    )
    for title, rows, empty in sections:
        story.append(Paragraph(f"{title} ({len(rows)})", s["h2"]))
        story.append(_due_table(rows, s, width) if rows else Paragraph(empty, s["body"]))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(doc.leftMargin, 9 * mm, f"LookApt - Monthly Receivables, {r['month_label']}")
        canvas.drawRightString(A4[0] - doc.rightMargin, 9 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
