"""
Convert תיק_פרויקט.md  →  תיק_פרויקט.pdf
Plain style: black text on white, no decorative colors.
Uses fpdf2 + DejaVu fonts + python-bidi for Hebrew RTL.
"""
import pathlib, re, textwrap
from bidi.algorithm import get_display
from fpdf import FPDF

ROOT  = pathlib.Path(__file__).parent
SRC   = ROOT / "תיק_פרויקט.md"
OUT   = ROOT / "תיק_פרויקט.pdf"
FONT_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_M = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def bidi(text: str) -> str:
    return get_display(text)


def bidi_lines(text: str, width_chars: int = 90) -> list:
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        wrapped = textwrap.wrap(paragraph, width=width_chars) or [""]
        for l in wrapped:
            lines.append(bidi(l))
    return lines


def strip_inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",    r"\1", text)
    text = re.sub(r"`(.+?)`",      r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    return text


class PortfolioPDF(FPDF):
    def __init__(self):
        super().__init__("P", "mm", "A4")
        self.set_auto_page_break(auto=True, margin=25)
        self.add_font("heb",  "",  FONT_R, uni=True)
        self.add_font("heb",  "B", FONT_B, uni=True)
        self.add_font("mono", "",  FONT_M, uni=True)

    def header(self):
        if self.page_no() <= 1:
            return
        self.set_font("heb", "", 8)
        self.set_text_color(80, 80, 80)
        self.cell(0, 6, bidi("בלאק‑ג'ק רב‑משתתפים  |  תיק פרויקט"), align="R")
        self.ln(2)
        self.set_draw_color(180, 180, 180)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)
        self.set_text_color(0, 0, 0)

    def footer(self):
        if self.page_no() <= 1:
            return
        self.set_y(-15)
        self.set_draw_color(180, 180, 180)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)
        self.set_font("heb", "", 8)
        self.set_text_color(80, 80, 80)
        self.cell(0, 5, str(self.page_no()), align="C")

    def rtl_cell(self, h, txt, ln=True):
        self.cell(0, h, bidi(txt),
                  new_x="LMARGIN" if ln else "RIGHT",
                  new_y="NEXT"    if ln else "TOP",
                  align="R")

    def rtl_multicell(self, h, txt):
        for line in bidi_lines(txt, width_chars=88):
            self.cell(0, h, line, new_x="LMARGIN", new_y="NEXT", align="R")

    def spacer(self, h=3):
        self.ln(h)

    # Headings
    def h1(self, txt):
        self.add_page()
        self.set_font("heb", "B", 16)
        self.set_text_color(0, 0, 0)
        self.rtl_cell(10, txt)
        self.set_draw_color(0, 0, 0)
        self.set_line_width(0.5)
        y = self.get_y()
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.spacer(4)

    def h2(self, txt):
        self.spacer(5)
        self.set_font("heb", "B", 13)
        self.set_text_color(0, 0, 0)
        self.rtl_cell(8, txt)
        self.set_draw_color(150, 150, 150)
        self.set_line_width(0.3)
        y = self.get_y()
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.spacer(2)

    def h3(self, txt):
        self.spacer(4)
        self.set_font("heb", "B", 11)
        self.set_text_color(0, 0, 0)
        self.rtl_cell(7, txt)
        self.spacer(1)

    def h4(self, txt):
        self.spacer(2)
        self.set_font("heb", "B", 10)
        self.set_text_color(0, 0, 0)
        self.rtl_cell(6, txt)

    def body(self, txt):
        if not txt.strip():
            return
        self.set_font("heb", "", 10)
        self.set_text_color(0, 0, 0)
        self.rtl_multicell(5.5, txt)
        self.spacer(1)

    def bullet(self, txt, level=0):
        indent = level * 5
        marker = "-"
        self.set_font("heb", "", 10)
        self.set_text_color(0, 0, 0)
        lines = bidi_lines(txt, width_chars=82 - indent // 2)
        first = True
        for line in lines:
            self.set_x(self.l_margin + indent)
            prefix = f"  {marker}  " if first else "       "
            self.cell(190 - indent, 5.5, prefix + line,
                      new_x="LMARGIN", new_y="NEXT", align="R")
            first = False

    def hr(self):
        self.spacer(2)
        self.set_draw_color(180, 180, 180)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.spacer(2)

    def code_block(self, lines_list):
        self.spacer(2)
        line_h = 4.2
        block_h = len(lines_list) * line_h + 6
        x = self.l_margin
        y = self.get_y()
        if y + block_h > self.h - self.b_margin - 10:
            self.add_page()
            y = self.get_y()
        self.set_fill_color(245, 245, 245)
        self.set_draw_color(180, 180, 180)
        self.set_line_width(0.3)
        self.rect(x, y, 190, block_h, "FD")
        self.set_y(y + 3)
        self.set_font("mono", "", 7.5)
        self.set_text_color(0, 0, 0)
        for line in lines_list:
            self.set_x(self.l_margin + 3)
            self.cell(184, line_h, line.replace("\t", "    ")[:110],
                      new_x="LMARGIN", new_y="NEXT", align="L")
        self.spacer(3)

    def table(self, rows):
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
            if ri == 0:
                self.set_fill_color(220, 220, 220)
                self.set_font("heb", "B", 8.5)
            elif ri % 2 == 0:
                self.set_fill_color(255, 255, 255)
                self.set_font("heb", "", 8.5)
            else:
                self.set_fill_color(245, 245, 245)
                self.set_font("heb", "", 8.5)

            self.set_text_color(0, 0, 0)
            self.set_draw_color(180, 180, 180)
            self.set_line_width(0.3)

            for ci, cell_txt in enumerate(row):
                cx = x + ci * col_w
                self.set_xy(cx, y)
                self.cell(col_w, row_h, bidi(cell_txt[:50]),
                          border=1, fill=True, align="R")
            self.set_xy(self.l_margin, y + row_h)
        self.spacer(3)

    def blockquote(self, txt):
        self.spacer(1)
        self.set_font("heb", "", 9.5)
        self.set_text_color(60, 60, 60)
        self.set_x(self.l_margin + 8)
        self.cell(182, 6, bidi("  " + txt), new_x="LMARGIN", new_y="NEXT", align="R")
        self.set_text_color(0, 0, 0)
        self.spacer(1)


def parse_and_render(pdf: PortfolioPDF, md_text: str):
    lines = md_text.split("\n")
    i = 0
    in_code = False
    code_buf = []
    in_table = False
    table_rows = []
    first_h1 = True

    def flush_table():
        nonlocal in_table, table_rows
        if table_rows:
            pdf.table(table_rows)
        in_table = False
        table_rows = []

    while i < len(lines):
        raw = lines[i]
        stripped = raw.rstrip()

        if stripped.startswith("```"):
            if in_table:
                flush_table()
            if not in_code:
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

        if stripped.startswith("|"):
            if not in_table:
                in_table = True
                table_rows = []
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if not all(re.match(r"^[-: ]+$", c) for c in cells):
                table_rows.append(cells)
            i += 1
            continue
        else:
            if in_table:
                flush_table()

        if not stripped:
            pdf.spacer(2)
            i += 1
            continue

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
            if first_h1:
                first_h1 = False
                pdf.add_page()
                pdf.set_font("heb", "B", 18)
                pdf.set_text_color(0, 0, 0)
                pdf.rtl_cell(12, txt)
                pdf.spacer(4)
            else:
                pdf.h1(txt)
            i += 1; continue

        if re.match(r"^-{3,}$", stripped):
            pdf.hr()
            i += 1; continue

        if stripped.startswith("> "):
            pdf.blockquote(strip_inline(stripped[2:]))
            i += 1; continue

        m = re.match(r"^(\s*)[*\-]\s+(.+)", stripped)
        if m:
            level = len(m.group(1)) // 2
            pdf.bullet(strip_inline(m.group(2)), level)
            i += 1; continue

        m = re.match(r"^\s*\d+\.\s+(.+)", stripped)
        if m:
            pdf.bullet(strip_inline(m.group(1)), 0)
            i += 1; continue

        pdf.body(strip_inline(stripped))
        i += 1

    if in_table:
        flush_table()
    if in_code and code_buf:
        pdf.code_block(code_buf)


def main():
    md_text = SRC.read_text(encoding="utf-8")
    pdf = PortfolioPDF()
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(True, margin=22)
    parse_and_render(pdf, md_text)
    pdf.output(str(OUT))
    print(f"Saved -> {OUT}  ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
