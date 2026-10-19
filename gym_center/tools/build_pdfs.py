"""Sinh 7 tài liệu PDF của Iron Việt Fitness từ nguồn Markdown trong tools/pdf_src/.

    python tools/build_pdfs.py            (chạy trong thư mục gym_center/)

Dùng font Unicode (Arial/DejaVu) và văn bản thật để lớp text của PDF giữ đúng dấu cách,
pipeline RAG trích xuất được nguyên văn. Sửa nội dung thì sửa file .md rồi chạy lại script.
"""
from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TOOLS = Path(__file__).resolve().parent
SRC = TOOLS / "pdf_src"
OUT = TOOLS.parent / "knowledge_base"
BRAND = colors.HexColor("#1F2A36")
ACCENT = colors.HexColor("#E8590C")
SOFT = colors.HexColor("#FFF1E6")
FOOTER = "Iron Việt Fitness · Q7: 123 Nguyễn Thị Thập · Q4: 456 Khánh Hội · Hotline 1900 8686 88 · ironvietfitness.vn"

DOCS = [
    ("branches_info", "Thông tin chi nhánh"),
    ("facility_rules", "Nội quy phòng tập"),
    ("policy_health_safety", "Chính sách sức khỏe & an toàn"),
    ("pricing_plans", "Bảng giá gói tập"),
    ("pricing_classes", "Bảng giá lớp học nhóm"),
    ("pricing_pt_packages", "Bảng giá gói PT"),
    ("promotions_current", "Chương trình khuyến mãi"),
]


def register_fonts() -> tuple[str, str]:
    candidates = [
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ]
    for regular, bold in candidates:
        if Path(regular).exists() and Path(bold).exists():
            pdfmetrics.registerFont(TTFont("VN", regular))
            pdfmetrics.registerFont(TTFont("VN-Bold", bold))
            pdfmetrics.registerFontFamily("VN", normal="VN", bold="VN-Bold", italic="VN", boldItalic="VN-Bold")
            return "VN", "VN-Bold"
    raise SystemExit("Không tìm thấy font Unicode (Arial/DejaVu) để in tiếng Việt.")


FONT, FONT_BOLD = register_fonts()
BASE = dict(fontName=FONT, textColor=colors.HexColor("#222222"))
STYLES = {
    "h1": ParagraphStyle("h1", fontName=FONT_BOLD, fontSize=17, leading=22, textColor=BRAND, spaceAfter=4),
    "h2": ParagraphStyle("h2", fontName=FONT_BOLD, fontSize=12.5, leading=17, textColor=ACCENT, spaceBefore=10, spaceAfter=4),
    "h3": ParagraphStyle("h3", fontName=FONT_BOLD, fontSize=11, leading=15, textColor=BRAND, spaceBefore=6, spaceAfter=2),
    "p": ParagraphStyle("p", fontSize=10, leading=14, spaceAfter=4, alignment=TA_LEFT, **BASE),
    "cell": ParagraphStyle("cell", fontSize=9, leading=11.5, **BASE),
    "cellh": ParagraphStyle("cellh", fontName=FONT_BOLD, fontSize=9, leading=11.5, textColor=colors.white),
    "note": ParagraphStyle("note", fontSize=9.5, leading=13, **BASE),
}
WIDTH = A4[0] - 36 * mm


def inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"`(.+?)`", r"<b>\1</b>", text)


def table(rows: list[list[str]]) -> Table:
    data = [[Paragraph(inline(c), STYLES["cellh" if r == 0 else "cell"]) for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=[WIDTH / len(rows[0])] * len(rows[0]), repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F8")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D1D9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def md_to_flowables(md: str) -> list:
    flow, para, lines = [], [], md.splitlines()
    i = 0

    def flush():
        if para:
            flow.append(Paragraph(inline(" ".join(para)), STYLES["p"]))
            para.clear()

    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            flush()
            i += 1
        elif line.startswith(("# ", "## ", "### ")):
            flush()
            level = len(line.split(" ", 1)[0])
            flow.append(Paragraph(inline(line[level + 1:]), STYLES[f"h{level}"]))
            i += 1
        elif line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            flow += [table(rows), Spacer(1, 6)]
        elif re.match(r"^(- |\d+\. )", line):
            flush()
            numbered = bool(re.match(r"^\d+\. ", line))
            items = []
            while i < len(lines) and re.match(r"^(  )?(- |\d+\. )", lines[i]):
                sub = lines[i].startswith("  ")
                text = re.sub(r"^(  )?(- |\d+\. )", "", lines[i])
                extra = {"value": "–", "leftIndent": 28} if sub else {"leftIndent": 14}
                items.append(ListItem(Paragraph(inline(text), STYLES["p"]), **extra))
                i += 1
            flow.append(ListFlowable(items, bulletType="1" if numbered else "bullet", bulletFontName=FONT,
                                     bulletFontSize=9, leftIndent=14, start="1" if numbered else "•"))
        elif line.startswith("> "):
            flush()
            note = []
            while i < len(lines) and lines[i].startswith("> "):
                note.append(lines[i][2:])
                i += 1
            box = Table([[Paragraph(inline(" ".join(note)), STYLES["note"])]], colWidths=[WIDTH])
            box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT),
                                     ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT),
                                     ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            flow += [box, Spacer(1, 6)]
        else:
            para.append(line.strip())
            i += 1
    flush()
    return flow


def render(name: str, title: str) -> None:
    md = (SRC / f"{name}.md").read_text(encoding="utf-8")
    path = OUT / f"{name}.pdf"

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(BRAND)
        canvas.rect(0, A4[1] - 12 * mm, A4[0], 12 * mm, fill=1, stroke=0)
        canvas.setFillColor(ACCENT)
        canvas.rect(0, A4[1] - 13 * mm, A4[0], 1 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont(FONT_BOLD, 10)
        canvas.drawString(18 * mm, A4[1] - 8 * mm, "IRON VIỆT FITNESS")
        canvas.setFont(FONT, 9)
        canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 8 * mm, title)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.setFont(FONT, 7.5)
        canvas.drawString(18 * mm, 10 * mm, FOOTER)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Trang {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm,
                            bottomMargin=18 * mm, title=f"{title} – Iron Việt Fitness", author="Iron Việt Fitness",
                            subject=title, creator="gym_center/tools/build_pdfs.py")
    doc.build(md_to_flowables(md), onFirstPage=decorate, onLaterPages=decorate)
    print(f"  {path.name}")


if __name__ == "__main__":
    print("Sinh PDF vào knowledge_base/:")
    for name, title in DOCS:
        render(name, title)
