"""Excel and PDF downloads."""
import io
import os
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ACCENT = "2543C8"


def fmt_ms(ms):
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000).strftime("%d %b %Y %H:%M")


def _event_table(cols, rows, with_turn):
    head = (["Turn"] if with_turn else []) + cols + ["Came", "Checked in", "Times submitted"]
    body = []
    for r in rows:
        f = r["fields"]
        body.append(([r["turn"]] if with_turn else []) + [f.get(c, "") for c in cols]
                    + ["Yes" if r["came"] else "No", fmt_ms(r["came_at"]), r["n"]])
    return head, body


def _all_table(rows):
    head = ["Name", "College", "Email", "Phone", "Events", "Times submitted"]
    body = []
    for r in rows:
        evs = "\n".join("• %s (%s)" % (t["name"], ("came, turn %s" % t["turn"]) if t["came"] else "not yet") for t in r["events"])
        body.append([r["name"], r["college"], r["email"], r["phone"], evs, r["n"]])
    return head, body


def _sheet(wb, title, head, body, first=False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title[:31]
    ws.append(head)
    for row in body:
        ws.append(row)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=ACCENT)
        c.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"
    for i, h in enumerate(head, 1):
        width = max([len(str(h))] + [max(len(x) for x in str(r[i - 1]).split("\n")) for r in body[:300]] + [4])
        ws.column_dimensions[get_column_letter(i)].width = min(48, width + 2)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    return ws


def build_xlsx(ev_name, cols, rows, all_events=False):
    wb = Workbook()
    if all_events:
        head, body = _all_table(rows)
        _sheet(wb, "People", head, body, first=True)
    else:
        came = sorted((r for r in rows if r["came"]), key=lambda r: r["turn"] or 0)
        wait = [r for r in rows if not r["came"]]
        h, b = _event_table(cols, rows, False)
        _sheet(wb, "Everyone", h, b, first=True)
        h, b = _event_table(cols, came, True)
        _sheet(wb, "Came (turn order)", h, b)
        h, b = _event_table(cols, wait, False)
        _sheet(wb, "Not yet", h, b)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ------------------------------------------------------------------ PDF

def _find_font():
    """A font that can draw Hindi/other scripts if one is installed; otherwise None (Helvetica)."""
    cands = [os.environ.get("FONT_PATH", ""),
             r"C:\Windows\Fonts\Nirmala.ttf", r"C:\Windows\Fonts\arial.ttf",
             "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]
    for p in cands:
        if p and os.path.exists(p):
            return p
    return None


def build_pdf(title, subtitle, sections):
    """sections: list of (heading, head, body). Returns PDF bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    font, bold = "Helvetica", "Helvetica-Bold"
    fp = _find_font()
    if fp:
        try:
            pdfmetrics.registerFont(TTFont("EDFont", fp))
            font = bold = "EDFont"
        except Exception:
            pass
    widest = max((len(h) for _, h, _ in sections), default=4)
    page = landscape(A4) if widest > 5 else A4
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=30, rightMargin=30, topMargin=34, bottomMargin=34, title=title)
    h1 = ParagraphStyle("h1", fontName=bold, fontSize=17, leading=21)
    sub = ParagraphStyle("sub", fontName=font, fontSize=9, leading=12, textColor=colors.HexColor("#586979"))
    h2 = ParagraphStyle("h2", fontName=bold, fontSize=12, leading=16, spaceBefore=12, spaceAfter=4)
    cell = ParagraphStyle("cell", fontName=font, fontSize=8, leading=10)
    cellh = ParagraphStyle("cellh", fontName=bold, fontSize=8, leading=10, textColor=colors.white)
    story = [Paragraph(escape(title), h1), Paragraph(escape(subtitle), sub)]
    avail = page[0] - 60
    for heading, head, body in sections:
        story.append(Paragraph(escape(heading), h2))
        if not body:
            story.append(Paragraph("No one here.", sub))
            continue
        data = [[Paragraph(escape(str(x)), cellh) for x in head]]
        for r in body:
            data.append([Paragraph(escape(str(x)).replace("\n", "<br/>"), cell) for x in r])
        lens = [max([len(str(head[i]))] + [min(40, len(str(r[i]))) for r in body[:60]]) + 3 for i in range(len(head))]
        total = float(sum(lens))
        t = Table(data, colWidths=[avail * l / total for l in lens], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + ACCENT)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6FA")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D4DAE2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story += [t, Spacer(1, 6)]

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#8A97A5"))
        canvas.drawRightString(page[0] - 30, 18, "Page %d" % d.page)
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def pdf_sections(cols, rows, view, status_label):
    """view 'split' -> Came (turn order) + Not yet; otherwise one table."""
    if view == "split":
        came = sorted((r for r in rows if r["came"]), key=lambda r: r["turn"] or 0)
        wait = [r for r in rows if not r["came"]]
        h, b = _event_table(cols, came, True)
        h2, b2 = _event_table(cols, wait, False)
        return [("Came, in turn order (%d)" % len(came), h, b), ("Not yet (%d)" % len(wait), h2, b2)]
    h, b = _event_table(cols, rows, False)
    return [("%s (%d)" % (status_label, len(rows)), h, b)]
