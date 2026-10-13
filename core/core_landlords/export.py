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


class ReceivablesPdf:
    """One month's ReceivablesReport as a PDF: ReceivablesPdf(report).render() -> bytes.

    render() builds the page from small parts (_title, _summary ...), each
    returning its list of ReportLab flowables.
    """

    NAVY = colors.HexColor("#203a68")
    LINE = colors.HexColor("#d9dee8")
    STRIPE = colors.HexColor("#f4f6fa")
    MUTED = colors.HexColor("#5f6b7f")

    STATUS_LABELS = {"paid": "Paid", "overdue": "Overdue", "due_soon": "Due Soon", "not_due": "Upcoming"}

    MARGINS = {"leftMargin": 18 * mm, "rightMargin": 18 * mm, "topMargin": 16 * mm, "bottomMargin": 16 * mm}

    def __init__(self, report):
        self.user = report.user
        self.r = report.as_dict()
        self.s = self._styles()
        self.width = A4[0] - self.MARGINS["leftMargin"] - self.MARGINS["rightMargin"]

    @staticmethod
    def _php(amount):
        return f"PHP {amount:,.0f}"

    def _styles(self):
        base = getSampleStyleSheet()
        navy, muted = self.NAVY, self.MUTED
        return {
            "title": ParagraphStyle("title", parent=base["Title"], alignment=0, textColor=navy, fontSize=19, spaceAfter=2),
            "sub": ParagraphStyle("sub", parent=base["Normal"], textColor=muted, fontSize=9.5, leading=13),
            "h2": ParagraphStyle("h2", parent=base["Heading2"], textColor=navy, fontSize=12.5, spaceBefore=12, spaceAfter=5),
            "note": ParagraphStyle("note", parent=base["Normal"], textColor=muted, fontSize=8.5, spaceAfter=5),
            "body": ParagraphStyle("body", parent=base["Normal"], fontSize=9.5, leading=13),
            "big": ParagraphStyle("big", parent=base["Normal"], fontSize=12, leading=16, textColor=navy),
            "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8.5, leading=11),
            "right": ParagraphStyle("right", parent=base["Normal"], fontSize=8.5, leading=11, alignment=TA_RIGHT),
        }

    def _table(self, rows, widths, money_cols=(), total=False):
        """Header row in navy, striped body, money columns right-aligned."""
        table = Table(rows, colWidths=widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), self.NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, self.LINE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, self.STRIPE]),
        ]
        for col in money_cols:
            style.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
        if total:
            style += [
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8edf6")),
                ("LINEABOVE", (0, -1), (-1, -1), 1, self.NAVY),
            ]
        table.setStyle(TableStyle(style))
        return table

    def _due_table(self, rows):
        """Due Date | Unit | Property | Tenant | Amount | Status"""
        data = [["Due Date", "Unit", "Property", "Tenant", "Amount", "Status"]]
        for row in rows:
            data.append([
                row["due"].strftime("%b %d, %Y"),
                row["unit"].unit_name,
                Paragraph(escape(row["unit"].complex.complex_name), self.s["cell"]),
                Paragraph(escape(row["tenancy"].tenant_name or "-"), self.s["cell"]),
                self._php(row["amount"]),
                self.STATUS_LABELS.get(row["status"], row["status"]),
            ])
        return self._table(data, [x * self.width for x in (0.14, 0.11, 0.25, 0.22, 0.15, 0.13)], money_cols=(4,))

    # ---------- the parts of the page ----------

    def _title(self):
        r, s, php = self.r, self.s, self._php
        generated = timezone.localtime().strftime("%b %d, %Y %I:%M %p")
        return [
            Paragraph(f"Monthly Receivables: {r['month_label']}", s["title"]),
            Paragraph(f"{escape(self.user.display_name)} &middot; LookApt &middot; Generated {generated}", s["sub"]),
            Spacer(1, 10),
            Paragraph(
                f"<b>{php(r['paid']['amount'])}</b> of {php(r['expected']['amount'])} collected "
                f"(<b>{r['percent']}%</b>)", s["big"],
            ),
            Spacer(1, 4),
        ]

    def _summary(self):
        r, php, width = self.r, self._php, self.width
        summary = [["Status", "Due Dates", "Amount"]]
        for label, key in (("Paid", "paid"), ("Overdue", "overdue"), ("Due in the next 7 days", "due_soon"),
                           ("Not yet due", "not_due")):
            summary.append([label, r[key]["count"], php(r[key]["amount"])])
        summary.append(["Total expected", r["expected"]["count"], php(r["expected"]["amount"])])
        return [
            Paragraph("Summary", self.s["h2"]),
            self._table(summary, [width * 0.5, width * 0.2, width * 0.3], money_cols=(1, 2), total=True),
        ]

    def _expected_income(self):
        r, s, php, width = self.r, self.s, self._php, self.width
        story = [
            Paragraph("Expected Rental Income", s["h2"]),
            Paragraph("From every unit with rent due this month, grouped by monthly rate.", s["note"]),
        ]
        if r["breakdown"]:
            breakdown = [["Monthly Rate", "Units", "Expected"]]
            breakdown += [[php(row["rate"]), row["units"], php(row["amount"])] for row in r["breakdown"]]
            breakdown.append(["Total", r["expected"]["count"], php(r["expected"]["amount"])])
            story.append(self._table(breakdown, [width * 0.4, width * 0.25, width * 0.35], money_cols=(0, 1, 2), total=True))
        else:
            story.append(Paragraph("No rent is due this month.", s["body"]))
        return story

    def _due_dates(self):
        story = []
        sections = (
            ("Overdue", self.r["overdue_rows"], "Nothing overdue this month."),
            ("Upcoming", self.r["upcoming"], "No upcoming due dates this month."),
            ("Paid", self.r["paid_rows"], "No payments recorded for this month yet."),
        )
        for title, rows, empty in sections:
            story.append(Paragraph(f"{title} ({len(rows)})", self.s["h2"]))
            story.append(self._due_table(rows) if rows else Paragraph(empty, self.s["body"]))
        return story

    def _footer(self, canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(self.MUTED)
        canvas.drawString(document.leftMargin, 9 * mm, f"LookApt - Monthly Receivables, {self.r['month_label']}")
        canvas.drawRightString(A4[0] - document.rightMargin, 9 * mm, f"Page {document.page}")
        canvas.restoreState()

    def render(self):
        """The PDF bytes."""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4, **self.MARGINS,
            title=f"Monthly Receivables - {self.r['month_label']}", author="LookApt",
        )
        story = self._title() + self._summary() + self._expected_income() + self._due_dates()
        doc.build(story, onFirstPage=self._footer, onLaterPages=self._footer)
        return buffer.getvalue()
