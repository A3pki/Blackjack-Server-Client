"""
Convert תיק_פרויקט.md  →  תיק_פרויקט.pdf
Uses fpdf2 + DejaVu fonts + python-bidi for proper Hebrew RTL.
"""
import pathlib, re, textwrap
from bidi.algorithm import get_display
from fpdf import FPDF

# ── paths ────────────────────────────────────────────────────────────────────
ROOT   = pathlib.Path(__file__).parent
SRC    = ROOT / "תיק_פרויקט.md"
OUT    = ROOT / "תיק_פרויקט.pdf"
FONT_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_M = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

# ── colour palette ────────────────────────────────────────────────────────────
GREEN_DARK  = (10,  77, 31)
GREEN_MED   = (20,  90, 46)
GREEN_LIGHT = (237, 248, 241)
GREEN_LINE  = (200, 222, 206)
WHITE       = (255, 255, 255)
GRAY        = (245, 245, 245)
DARK        = (26,  26,  26)
MID_GRAY    = (102, 102, 102)
CODE_BG     = (240, 244, 241)

# ── helper: bidi-reorder a Hebrew/mixed string for display ────────────────────
def bidi(text: str) -> str:
    return get_display(text)

def bidi_lines(text: str, width_chars: int = 90) -> list[str]:
    """Wrap and bidi-reorder each line."""
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        wrapped = textwrap.wrap(paragraph, width=width_chars) or [""]
        for l in wrapped:
            lines.append(bidi(l))
    return lines

# ── main PDF class ────────────────────────────────────────────────────────────
class PortfolioPDF(FPDF):
    def __init__(self):
        super().__init__("P", "mm", "A4")
        self.set_auto_page_break(auto=True, margin=25)
        self.add_font("heb",  "",  FONT_R, uni=True)
        self.add_font("heb",  "B", FONT_B, uni=True)
        self.add_font("mono", "",  FONT_M, uni=True)
        self.add_font("mono", "B", FONT_M, uni=True)
        self._section_title = ""

    # ── header / footer ──────────────────────────────────────────────────────
    def header(self):
        if self.page_no() <= 1:
            return
        self.set_font("heb", "", 8)
        self.set_text_color(*MID_GRAY)
        self.cell(0, 6, bidi("בלאק‑ג'ק רב‑משתתפים  |  תיק פרויקט"),
                  align="R")
        self.ln(2)
        self.set_draw_color(*GREEN_LINE)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def footer(self):
        if self.page_no() <= 1:
            return
        self.set_y(-18)
        self.set_draw_color(*GREEN_LINE)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)
        self.set_font("heb", "", 8)
        self.set_text_color(*MID_GRAY)
        self.cell(0, 6, str(self.page_no()), align="C")

    # ── primitives ───────────────────────────────────────────────────────────
    def set_body(self):
        self.set_font("heb", "", 10)
        self.set_text_color(*DARK)

    def rtl_cell(self, h, txt, ln=True, fill=False, align="R"):
        self.cell(0, h, bidi(txt), new_x="LMARGIN" if ln else "RIGHT",
                  new_y="NEXT" if ln else "TOP", align=align, fill=fill)

    def rtl_multicell(self, h, txt, fill=False):
        """Multi-cell with bidi reordering per line."""
        lines = bidi_lines(txt, width_chars=85)
        for line in lines:
            self.cell(0, h, line, new_x="LMARGIN", new_y="NEXT",
                      align="R", fill=fill)

    def spacer(self, h=3):
        self.ln(h)

    # ── cover page ───────────────────────────────────────────────────────────
    def cover_page(self):
        self.add_page()
        # background strip
        self.set_fill_color(*GREEN_DARK)
        self.rect(0, 0, 210, 70, "F")
        # title block
        self.set_y(18)
        self.set_font("heb", "B", 26)
        self.set_text_color(*WHITE)
        self.rtl_cell(12, "בלאק‑ג'ק רב‑משתתפים")
        self.set_font("heb", "", 13)
        self.rtl_cell(8, "משחק קלפים מאובטח בארכיטקטורת לקוח‑שרת")
        self.ln(5)
        # meta block
        self.set_y(90)
        meta = [
            ("שם העבודה",  "בלאק‑ג'ק רב‑משתתפים"),
            ("שם התלמיד",  "_______________"),
            ("ת.ז. התלמיד","_______________"),
            ("שם המנחה",   "_______________"),
            ("שם בית הספר","_______________"),
            ("שם החלופה",  "הגנת סייבר ומערכות הפעלה"),
            ("תאריך הגשה", "_______________"),
        ]
        self.set_draw_color(*GREEN_LINE)
        self.set_line_width(0.4)
        for label, value in meta:
            x = self.l_margin
            y = self.get_y()
            self.set_fill_color(*GREEN_LIGHT)
            self.rect(x, y, 190, 9.5, "FD")
            self.set_font("heb", "B", 10)
            self.set_text_color(*GREEN_DARK)
            self.set_xy(x, y + 0.5)
            self.cell(50, 8.5, bidi(label + ":"), align="R")
            self.set_font("heb", "", 10)
            self.set_text_color(*DARK)
            self.cell(0, 8.5, bidi(value), align="R",
                      new_x="LMARGIN", new_y="NEXT")
            self.ln(1)
        # decorative bottom strip
        self.set_y(260)
        self.set_fill_color(*GREEN_MED)
        self.rect(0, 270, 210, 27, "F")
        self.set_y(274)
        self.set_font("heb", "", 9)
        self.set_text_color(*WHITE)
        self.rtl_cell(6, "הגנת סייבר ומערכות הפעלה  ·  הנדסת תוכנה 883589")
        self.rtl_cell(6, "Python 3.11  ·  TCP Sockets  ·  RSA-2048 + Fernet  ·  Tkinter GUI")

    # ── chapter heading ──────────────────────────────────────────────────────
    def h1(self, txt):
        self.add_page()
        # coloured banner
        self.set_fill_color(*GREEN_DARK)
        self.rect(self.l_margin, self.get_y(), 190, 14, "F")
        self.set_font("heb", "B", 16)
        self.set_text_color(*WHITE)
        self.set_x(self.l_margin)
        self.cell(190, 14, bidi(txt), align="R", fill=False,
                  new_x="LMARGIN", new_y="NEXT")
        self.spacer(4)
        self.set_text_color(*DARK)

    def h2(self, txt):
        self.spacer(4)
        self.set_font("heb", "B", 13)
        self.set_text_color(*GREEN_DARK)
        y = self.get_y()
        self.line(self.l_margin, y + 6.5, self.w - self.r_margin, y + 6.5)
        self.set_draw_color(*GREEN_MED)
        self.set_line_width(0.6)
        self.set_x(self.l_margin)
        self.cell(190, 8, bidi(txt), align="R",
                  new_x="LMARGIN", new_y="NEXT")
        self.set_line_width(0.3)
        self.spacer(2)
        self.set_text_color(*DARK)

    def h3(self, txt):
        self.spacer(3)
        self.set_font("heb", "B", 11)
        self.set_text_color(*GREEN_MED)
        self.rtl_cell(7, txt)
        self.spacer(1)
        self.set_text_color(*DARK)

    def h4(self, txt):
        self.spacer(2)
        self.set_font("heb", "B", 10)
        self.set_text_color(*GREEN_MED)
        self.rtl_cell(6, "◆ " + txt)
        self.set_text_color(*DARK)

    # ── body text ────────────────────────────────────────────────────────────
    def body(self, txt):
        if not txt.strip():
            return
        self.set_body()
        # process inline bold (**...**)
        parts = re.split(r"\*\*(.+?)\*\*", txt)
        if len(parts) > 1:
            # line with bold fragments — render whole line, bold the pieces
            line = ""
            for i, part in enumerate(parts):
                if i % 2 == 1:
                    line += part  # bold content
                else:
                    line += part
            self.set_font("heb", "", 10)
            self.rtl_multicell(5.5, txt.replace("**", ""))
        else:
            self.rtl_multicell(5.5, txt)
        self.spacer(1)

    def bullet(self, txt, level=0):
        indent = level * 5
        marker = "•" if level == 0 else "–"
        self.set_body()
        self.set_x(self.l_margin + indent)
        w = 190 - indent
        lines = bidi_lines(txt, width_chars=80 - indent // 2)
        first = True
        for line in lines:
            self.set_x(self.l_margin + indent)
            prefix = f"  {marker}  " if first else "      "
            self.cell(w, 5.5, prefix + line, new_x="LMARGIN", new_y="NEXT", align="R")
            first = False

    def hr(self):
        self.spacer(2)
        self.set_draw_color(*GREEN_LINE)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.spacer(2)

    # ── code block ───────────────────────────────────────────────────────────
    def code_block(self, lines_list):
        self.spacer(2)
        line_h = 4.2
        block_h = len(lines_list) * line_h + 6
        x = self.l_margin
        y = self.get_y()
        if y + block_h > self.h - self.b_margin - 10:
            self.add_page()
            y = self.get_y()
        self.set_fill_color(*CODE_BG)
        self.set_draw_color(*GREEN_LINE)
        self.set_line_width(0.4)
        self.rect(x, y, 190, block_h, "FD")
        self.set_y(y + 3)
        self.set_font("mono", "", 7.5)
        self.set_text_color(*DARK)
        for line in lines_list:
            display = line.replace("\t", "    ")
            self.set_x(self.l_margin + 3)
            self.cell(184, line_h, display[:110],
                      new_x="LMARGIN", new_y="NEXT", align="L")
        self.spacer(3)
        self.set_text_color(*DARK)

    # ── table ────────────────────────────────────────────────────────────────
    def table(self, rows):
        """rows: list of lists of str. First row = header."""
        if not rows:
            return
        self.spacer(2)
        col_n = max(len(r) for r in rows)
        col_w = 190 / col_n
        row_h = 6

        for ri, row in enumerate(rows):
            if self.get_y() + row_h > self.h - self.b_margin - 5:
                self.add_page()
            x = self.l_margin
            y = self.get_y()
            # background
            if ri == 0:
                self.set_fill_color(*GREEN_DARK)
                self.set_text_color(*WHITE)
                self.set_font("heb", "B", 8.5)
            elif ri % 2 == 0:
                self.set_fill_color(*WHITE)
                self.set_text_color(*DARK)
                self.set_font("heb", "", 8.5)
            else:
                self.set_fill_color(*GREEN_LIGHT)
                self.set_text_color(*DARK)
                self.set_font("heb", "", 8.5)

            self.set_draw_color(*GREEN_LINE)
            self.set_line_width(0.3)
            for ci, cell_txt in enumerate(row):
                cx = x + ci * col_w
                self.set_xy(cx, y)
                self.cell(col_w, row_h, bidi(cell_txt[:38]),
                          border=1, fill=True, align="R")
            self.set_xy(self.l_margin, y + row_h)
        self.spacer(3)
        self.set_text_color(*DARK)

# ── Markdown parser ───────────────────────────────────────────────────────────

def strip_inline(text):
    """Remove **bold**, _italic_, `code` markers for plain text rendering."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",    r"\1", text)
    text = re.sub(r"`(.+?)`",      r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    return text

def parse_and_render(pdf: PortfolioPDF, md_text: str):
    lines = md_text.split("\n")
    i = 0
    in_code = False
    code_buf = []
    in_table = False
    table_rows = []

    def flush_table():
        nonlocal in_table, table_rows
        if table_rows:
            pdf.table(table_rows)
        in_table = False
        table_rows = []

    while i < len(lines):
        raw = lines[i]
        stripped = raw.rstrip()

        # ── fenced code block ──
        if stripped.startswith("```"):
            if not in_code:
                if in_table:
                    flush_table()
                in_code = True
                code_buf = []
            else:
                in_code = False
                pdf.code_block(code_buf)
                code_buf = []
            i += 1
            continue

        if in_code:
            code_buf.append(raw.rstrip("\n"))
            i += 1
            continue

        # ── tables ──
        if stripped.startswith("|"):
            if not in_table:
                in_table = True
                table_rows = []
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            # skip separator rows like |---|---|
            if not all(re.match(r"^[-: ]+$", c) for c in cells):
                table_rows.append(cells)
            i += 1
            continue
        else:
            if in_table:
                flush_table()

        # ── blank ──
        if not stripped:
            pdf.spacer(2)
            i += 1
            continue

        # ── headings ──
        if stripped.startswith("#### "):
            pdf.h4(strip_inline(stripped[5:]))
            i += 1; continue
        if stripped.startswith("### "):
            pdf.h3(strip_inline(stripped[4:]))
            i += 1; continue
        if stripped.startswith("## "):
            pdf.h2(strip_inline(stripped[3:]))
            i += 1; continue
        if stripped.startswith("# "):
            txt = strip_inline(stripped[2:])
            # first H1 is the document title → skip (cover page already done)
            if txt and txt != "בלאק‑ג'ק רב‑משתתפים – תיק פרויקט":
                pdf.h1(txt)
            i += 1; continue

        # ── hr ──
        if re.match(r"^-{3,}$", stripped):
            pdf.hr()
            i += 1; continue

        # ── blockquote ──
        if stripped.startswith("> "):
            txt = strip_inline(stripped[2:])
            pdf.set_font("heb", "", 9.5)
            pdf.set_fill_color(*GREEN_LIGHT)
            pdf.set_text_color(*GREEN_DARK)
            pdf.set_x(pdf.l_margin + 8)
            pdf.cell(182, 6, bidi("  ❝  " + txt), fill=True,
                     new_x="LMARGIN", new_y="NEXT", align="R")
            pdf.set_text_color(*DARK)
            i += 1; continue

        # ── bullets ──
        m = re.match(r"^(\s*)[*\-]\s+(.+)", stripped)
        if m:
            level = len(m.group(1)) // 2
            txt = strip_inline(m.group(2))
            pdf.bullet(txt, level)
            i += 1; continue

        # ── numbered list ──
        m = re.match(r"^\s*\d+\.\s+(.+)", stripped)
        if m:
            pdf.bullet(strip_inline(m.group(1)), 0)
            i += 1; continue

        # ── cover separator line (---) already handled ──
        # ── regular paragraph ──
        pdf.body(strip_inline(stripped))
        i += 1

    if in_table:
        flush_table()
    if in_code and code_buf:
        pdf.code_block(code_buf)


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    md_text = SRC.read_text(encoding="utf-8")

    pdf = PortfolioPDF()
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(True, margin=22)

    # Cover page
    pdf.cover_page()

    # Rest of document
    parse_and_render(pdf, md_text)

    pdf.output(str(OUT))
    print(f"✓  Saved → {OUT}  ({OUT.stat().st_size // 1024} KB)")

if __name__ == "__main__":
    main()
