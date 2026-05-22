"""
Convert תיק_פרויקט.md  →  תיק_פרויקט.docx
Produces a Google-Docs-compatible Word file:
  • RTL Hebrew paragraphs
  • Heading 1/2/3/4 styles  (auto-TOC friendly)
  • Tables with header row
  • Bullet / numbered lists
  • Inline code and code blocks
  • Page header + footer
  • Cover page
"""
import re, pathlib
from copy import deepcopy
from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import lxml.etree as etree

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT = pathlib.Path(__file__).parent
SRC  = ROOT / "תיק_פרויקט.md"
OUT  = ROOT / "תיק_פרויקט.docx"

# ── colours ───────────────────────────────────────────────────────────────────
C_GREEN_DARK   = RGBColor(0x0a, 0x4d, 0x1f)
C_GREEN_MED    = RGBColor(0x14, 0x5a, 0x2e)
C_GREEN_LIGHT  = RGBColor(0xed, 0xf8, 0xf1)
C_WHITE        = RGBColor(0xff, 0xff, 0xff)
C_DARK         = RGBColor(0x1a, 0x1a, 0x1a)
C_GRAY_MID     = RGBColor(0x55, 0x55, 0x55)
C_CODE_BG      = RGBColor(0xf0, 0xf4, 0xf1)
C_CODE_FG      = RGBColor(0x1a, 0x33, 0x1f)
C_TABLE_HEADER = RGBColor(0x0a, 0x4d, 0x1f)
C_TABLE_ALT    = RGBColor(0xed, 0xf8, 0xf1)

HEX_GREEN_DARK  = "0A4D1F"
HEX_GREEN_LIGHT = "EDF8F1"
HEX_CODE_BG     = "F0F4F1"

FONT_HEB  = "Arial"
FONT_MONO = "Courier New"

# ── XML helpers ───────────────────────────────────────────────────────────────
def set_rtl_para(para):
    """Set paragraph to RTL and align right."""
    pPr = para._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    bidi.set(qn("w:val"), "1")
    pPr.insert(0, bidi)
    jc = OxmlElement("w:jc")
    jc.set(qn("w:val"), "right")
    # remove existing jc if present
    for old in pPr.findall(qn("w:jc")):
        pPr.remove(old)
    pPr.append(jc)

def set_rtl_run(run):
    rPr = run._r.get_or_add_rPr()
    rtl = OxmlElement("w:rtl")
    rtl.set(qn("w:val"), "1")
    rPr.append(rtl)
    cs = OxmlElement("w:cs")
    rPr.append(cs)

def set_cell_bg(cell, hex_color):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    for old in tcPr.findall(qn("w:shd")):
        tcPr.remove(old)
    tcPr.append(shd)

def set_para_shading(para, hex_color):
    pPr = para._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    for old in pPr.findall(qn("w:shd")):
        pPr.remove(old)
    pPr.append(shd)

def set_para_border_bottom(para, hex_color="0A4D1F", size="12"):
    pPr = para._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"),   "single")
    bottom.set(qn("w:sz"),    size)
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), hex_color)
    pBdr.append(bottom)
    for old in pPr.findall(qn("w:pBdr")):
        pPr.remove(old)
    pPr.append(pBdr)

def set_spacing(para, before=0, after=0, line=None):
    pPr = para._p.get_or_add_pPr()
    for old in pPr.findall(qn("w:spacing")):
        pPr.remove(old)
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:before"), str(before))
    spacing.set(qn("w:after"),  str(after))
    if line:
        spacing.set(qn("w:line"), str(line))
        spacing.set(qn("w:lineRule"), "auto")
    pPr.append(spacing)

def set_indent(para, right=None, left=None, hanging=None):
    pPr = para._p.get_or_add_pPr()
    for old in pPr.findall(qn("w:ind")):
        pPr.remove(old)
    ind = OxmlElement("w:ind")
    if right   is not None: ind.set(qn("w:right"),   str(right))
    if left    is not None: ind.set(qn("w:left"),    str(left))
    if hanging is not None: ind.set(qn("w:hanging"), str(hanging))
    pPr.append(ind)

def add_page_break(doc):
    p = OxmlElement("w:p")
    r = OxmlElement("w:r")
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    r.append(br)
    p.append(r)
    doc.element.body.append(p)

def add_hf_text(section, position, text, font=FONT_HEB, size=8, color="555555"):
    """Add text to header or footer at given position (header/footer object)."""
    para = position.paragraphs[0]
    para.clear()
    run = para.add_run(text)
    run.font.name = font
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor(
        int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
    set_rtl_para(para)
    set_rtl_run(run)

# ── document styles ───────────────────────────────────────────────────────────
def configure_styles(doc):
    """Override built-in styles to match our theme."""
    styles = doc.styles

    # Normal
    n = styles["Normal"]
    n.font.name   = FONT_HEB
    n.font.size   = Pt(11)
    n.font.color.rgb = C_DARK
    n.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    # Heading 1 — chapter (full-width dark green)
    h1 = styles["Heading 1"]
    h1.font.name      = FONT_HEB
    h1.font.size      = Pt(18)
    h1.font.bold      = True
    h1.font.color.rgb = C_WHITE
    h1.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    h1.paragraph_format.space_before = Pt(18)
    h1.paragraph_format.space_after  = Pt(6)

    # Heading 2
    h2 = styles["Heading 2"]
    h2.font.name      = FONT_HEB
    h2.font.size      = Pt(14)
    h2.font.bold      = True
    h2.font.color.rgb = C_GREEN_DARK
    h2.paragraph_format.alignment    = WD_ALIGN_PARAGRAPH.RIGHT
    h2.paragraph_format.space_before = Pt(12)
    h2.paragraph_format.space_after  = Pt(4)

    # Heading 3
    h3 = styles["Heading 3"]
    h3.font.name      = FONT_HEB
    h3.font.size      = Pt(12)
    h3.font.bold      = True
    h3.font.color.rgb = C_GREEN_MED
    h3.paragraph_format.alignment    = WD_ALIGN_PARAGRAPH.RIGHT
    h3.paragraph_format.space_before = Pt(8)
    h3.paragraph_format.space_after  = Pt(2)

    # Heading 4
    h4 = styles["Heading 4"]
    h4.font.name      = FONT_HEB
    h4.font.size      = Pt(11)
    h4.font.bold      = True
    h4.font.color.rgb = C_GREEN_MED
    h4.paragraph_format.alignment    = WD_ALIGN_PARAGRAPH.RIGHT
    h4.paragraph_format.space_before = Pt(6)
    h4.paragraph_format.space_after  = Pt(1)

    # List Bullet
    lb = styles["List Bullet"]
    lb.font.name = FONT_HEB
    lb.font.size = Pt(11)
    lb.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    # List Number
    ln = styles["List Number"]
    ln.font.name = FONT_HEB
    ln.font.size = Pt(11)
    ln.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT

# ── inline markup parser ──────────────────────────────────────────────────────
def parse_inline(para, text, base_font=FONT_HEB, base_size=11, mono=False):
    """
    Splits *text* on **bold**, _italic_, `code`, and ‎[label](url).
    Adds appropriately formatted runs to *para*.
    Always sets RTL on every run.
    """
    pattern = re.compile(
        r"\*\*(.+?)\*\*"     # bold
        r"|(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"  # italic
        r"|`(.+?)`"          # inline code
        r"|\[(.+?)\]\((.+?)\)"  # link
        r"|(‎)"              # bidi mark – pass through
    )
    pos = 0
    for m in pattern.finditer(text):
        # plain text before match
        if m.start() > pos:
            chunk = text[pos:m.start()]
            if chunk:
                r = para.add_run(chunk)
                r.font.name = FONT_MONO if mono else base_font
                r.font.size = Pt(base_size)
                set_rtl_run(r)

        if m.group(1):    # bold
            r = para.add_run(m.group(1))
            r.bold = True
            r.font.name = base_font
            r.font.size = Pt(base_size)
            r.font.color.rgb = C_GREEN_DARK
            set_rtl_run(r)
        elif m.group(2):  # italic
            r = para.add_run(m.group(2))
            r.italic = True
            r.font.name = base_font
            r.font.size = Pt(base_size)
            set_rtl_run(r)
        elif m.group(3):  # inline code
            r = para.add_run(m.group(3))
            r.font.name = FONT_MONO
            r.font.size = Pt(9.5)
            r.font.color.rgb = C_CODE_FG
            set_rtl_run(r)
        elif m.group(4):  # link
            r = para.add_run(m.group(4))
            r.font.name = base_font
            r.font.size = Pt(base_size)
            r.font.color.rgb = C_GREEN_DARK
            r.underline = True
            set_rtl_run(r)
        pos = m.end()

    # trailing plain text
    tail = text[pos:]
    if tail:
        r = para.add_run(tail)
        r.font.name = FONT_MONO if mono else base_font
        r.font.size = Pt(base_size)
        set_rtl_run(r)

# ── builder helpers ───────────────────────────────────────────────────────────
def add_heading(doc, text, level):
    """Add heading with RTL, styling and optional shading for H1."""
    style_name = f"Heading {level}"
    para = doc.add_paragraph(style=style_name)
    set_rtl_para(para)
    if level == 1:
        set_para_shading(para, HEX_GREEN_DARK)
        set_spacing(para, before=240, after=100)
    elif level == 2:
        set_para_border_bottom(para, HEX_GREEN_DARK, "8")
        set_spacing(para, before=160, after=60)
    elif level == 3:
        set_spacing(para, before=100, after=40)
    elif level == 4:
        set_spacing(para, before=80, after=20)
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1",
           re.sub(r"`(.+?)`", r"\1", text))
    r = para.add_run(clean)
    r.font.name = FONT_HEB
    if level == 1:
        r.font.color.rgb = C_WHITE
    set_rtl_run(r)
    return para

def add_body(doc, text):
    if not text.strip():
        return
    para = doc.add_paragraph(style="Normal")
    set_rtl_para(para)
    set_spacing(para, before=20, after=60, line=276)
    parse_inline(para, text)
    return para

def add_bullet(doc, text, level=0):
    style = "List Bullet"
    para = doc.add_paragraph(style=style)
    set_rtl_para(para)
    # increase indentation for sub-bullets
    if level > 0:
        set_indent(para, right=level * 360, left=0)
    set_spacing(para, before=20, after=20, line=252)
    parse_inline(para, text)
    return para

def add_numbered(doc, text):
    para = doc.add_paragraph(style="List Number")
    set_rtl_para(para)
    set_spacing(para, before=20, after=20, line=252)
    parse_inline(para, text)
    return para

def add_code_block(doc, lines):
    """Render code as a 1-column table with grey background."""
    if not lines:
        return
    tbl = doc.add_table(rows=len(lines), cols=1)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, line in enumerate(lines):
        cell = tbl.rows[i].cells[0]
        set_cell_bg(cell, HEX_CODE_BG)
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        set_spacing(para, before=0, after=0, line=220)
        r = para.add_run(line if line else " ")
        r.font.name = FONT_MONO
        r.font.size = Pt(8.5)
        r.font.color.rgb = C_CODE_FG
        # code is LTR
        pPr = para._p.get_or_add_pPr()
        for old in pPr.findall(qn("w:bidi")):
            pPr.remove(old)
    # set fixed column width
    for row in tbl.rows:
        row.cells[0].width = Cm(17)
    doc.add_paragraph()  # spacing after

def add_table(doc, rows):
    """rows[0] = header row. Alternating row colours."""
    if not rows:
        return
    col_n = max(len(r) for r in rows)
    tbl = doc.add_table(rows=len(rows), cols=col_n)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER

    col_width = Cm(17.0 / col_n)

    for ri, row_data in enumerate(rows):
        row = tbl.rows[ri]
        for ci in range(col_n):
            cell = row.cells[ci]
            cell.width = col_width
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

            # Background
            if ri == 0:
                set_cell_bg(cell, HEX_GREEN_DARK)
            elif ri % 2 == 1:
                set_cell_bg(cell, HEX_GREEN_LIGHT)

            para = cell.paragraphs[0]
            set_rtl_para(para)
            set_spacing(para, before=40, after=40)

            txt = row_data[ci] if ci < len(row_data) else ""
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1",
                   re.sub(r"`(.+?)`", r"\1", txt.replace("‎", "")))
            r = para.add_run(clean)
            r.font.name = FONT_HEB
            r.font.size = Pt(9.5)
            if ri == 0:
                r.bold = True
                r.font.color.rgb = C_WHITE
            else:
                r.font.color.rgb = C_DARK
            set_rtl_run(r)
    doc.add_paragraph()  # spacing after

def add_blockquote(doc, text):
    para = doc.add_paragraph(style="Normal")
    set_rtl_para(para)
    set_para_shading(para, HEX_GREEN_LIGHT)
    set_indent(para, right=360, left=360)
    set_spacing(para, before=60, after=60)
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1",
           re.sub(r"`(.+?)`", r"\1", text))
    r = para.add_run("❝  " + clean)
    r.font.name = FONT_HEB
    r.font.size = Pt(10)
    r.italic = True
    r.font.color.rgb = C_GREEN_DARK
    set_rtl_run(r)
    return para

def add_hr(doc):
    para = doc.add_paragraph()
    set_para_border_bottom(para, HEX_GREEN_DARK, "6")
    set_spacing(para, before=60, after=60)

# ── cover page ────────────────────────────────────────────────────────────────
def build_cover(doc):
    # Title
    p = doc.add_paragraph()
    set_rtl_para(p)
    set_para_shading(p, HEX_GREEN_DARK)
    set_spacing(p, before=400, after=120)
    r = p.add_run("בלאק‑ג'ק רב‑משתתפים")
    r.font.name = FONT_HEB
    r.font.size = Pt(32)
    r.bold = True
    r.font.color.rgb = C_WHITE
    set_rtl_run(r)

    p2 = doc.add_paragraph()
    set_rtl_para(p2)
    set_para_shading(p2, HEX_GREEN_DARK)
    set_spacing(p2, before=0, after=280)
    r2 = p2.add_run("משחק קלפים מאובטח בארכיטקטורת לקוח‑שרת")
    r2.font.name = FONT_HEB
    r2.font.size = Pt(14)
    r2.font.color.rgb = C_WHITE
    set_rtl_run(r2)

    # Meta table
    meta = [
        ("שם העבודה",   "בלאק‑ג'ק רב‑משתתפים"),
        ("שם התלמיד",   "_______________"),
        ("ת.ז. התלמיד", "_______________"),
        ("שם המנחה",    "_______________"),
        ("שם בית הספר", "_______________"),
        ("שם החלופה",   "הגנת סייבר ומערכות הפעלה"),
        ("תאריך הגשה",  "_______________"),
    ]
    tbl = doc.add_table(rows=len(meta), cols=2)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, (label, value) in enumerate(meta):
        row = tbl.rows[i]
        # label cell
        lc = row.cells[0]
        lc.width = Cm(6)
        set_cell_bg(lc, HEX_GREEN_DARK)
        lp = lc.paragraphs[0]
        set_rtl_para(lp)
        set_spacing(lp, before=80, after=80)
        lr = lp.add_run(label)
        lr.font.name = FONT_HEB
        lr.font.size = Pt(11)
        lr.bold = True
        lr.font.color.rgb = C_WHITE
        set_rtl_run(lr)
        # value cell
        vc = row.cells[1]
        vc.width = Cm(11)
        set_cell_bg(vc, HEX_GREEN_LIGHT if i % 2 == 0 else "FFFFFF")
        vp = vc.paragraphs[0]
        set_rtl_para(vp)
        set_spacing(vp, before=80, after=80)
        vr = vp.add_run(value)
        vr.font.name = FONT_HEB
        vr.font.size = Pt(11)
        vr.font.color.rgb = C_DARK
        set_rtl_run(vr)

    doc.add_paragraph()
    p3 = doc.add_paragraph()
    set_rtl_para(p3)
    set_para_shading(p3, HEX_GREEN_DARK)
    set_spacing(p3, before=200, after=80)
    r3 = p3.add_run("Python 3.11  ·  TCP Sockets  ·  RSA-2048 + Fernet  ·  Tkinter GUI")
    r3.font.name = FONT_HEB
    r3.font.size = Pt(10)
    r3.font.color.rgb = C_WHITE
    set_rtl_run(r3)

    add_page_break(doc)

# ── Markdown parser / renderer ────────────────────────────────────────────────
def strip_inline_markers(text):
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`",       r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    return text

def parse_md(doc, md_text):
    lines = md_text.split("\n")
    i = 0
    in_code  = False
    code_buf = []
    in_table = False
    table_rows = []
    first_h1_seen = False

    def flush_table():
        nonlocal in_table, table_rows
        if table_rows:
            add_table(doc, table_rows)
        in_table = False
        table_rows = []

    def flush_code():
        nonlocal in_code, code_buf
        add_code_block(doc, code_buf)
        in_code  = False
        code_buf = []

    while i < len(lines):
        raw     = lines[i]
        stripped = raw.rstrip()

        # ── fenced code ──────────────────────────────────────────────────────
        if stripped.startswith("```"):
            if in_table: flush_table()
            if not in_code:
                in_code  = True
                code_buf = []
            else:
                flush_code()
            i += 1
            continue

        if in_code:
            code_buf.append(raw.rstrip("\n"))
            i += 1
            continue

        # ── table rows ───────────────────────────────────────────────────────
        if stripped.startswith("|"):
            in_table = True
            cells = [c.strip() for c in stripped.split("|")
                     if c.strip() and c.strip() != ""]
            # skip separator rows  |---|---|
            if not all(re.match(r"^[-: ]+$", c) for c in cells):
                table_rows.append(cells)
            i += 1
            continue
        else:
            if in_table:
                flush_table()

        # ── blank line ───────────────────────────────────────────────────────
        if not stripped:
            i += 1
            continue

        # ── headings ─────────────────────────────────────────────────────────
        if stripped.startswith("#### "):
            add_heading(doc, stripped[5:], 4)
            i += 1; continue
        if stripped.startswith("### "):
            add_heading(doc, stripped[4:], 3)
            i += 1; continue
        if stripped.startswith("## "):
            add_heading(doc, stripped[3:], 2)
            i += 1; continue
        if stripped.startswith("# "):
            txt = stripped[2:]
            if not first_h1_seen:
                first_h1_seen = True   # skip the document title (cover already has it)
            else:
                add_heading(doc, txt, 1)
            i += 1; continue

        # ── horizontal rule ───────────────────────────────────────────────────
        if re.match(r"^-{3,}$", stripped):
            add_hr(doc)
            i += 1; continue

        # ── blockquote ────────────────────────────────────────────────────────
        if stripped.startswith("> "):
            add_blockquote(doc, stripped[2:])
            i += 1; continue

        # ── bullet list ───────────────────────────────────────────────────────
        m = re.match(r"^(\s*)[*\-]\s+(.+)", stripped)
        if m:
            level = len(m.group(1)) // 2
            add_bullet(doc, m.group(2), level)
            i += 1; continue

        # ── numbered list ─────────────────────────────────────────────────────
        m = re.match(r"^\s*\d+\.\s+(.+)", stripped)
        if m:
            add_numbered(doc, m.group(1))
            i += 1; continue

        # ── plain paragraph ───────────────────────────────────────────────────
        add_body(doc, stripped)
        i += 1

    if in_table: flush_table()
    if in_code and code_buf: flush_code()

# ── header / footer ───────────────────────────────────────────────────────────
def setup_header_footer(doc):
    section = doc.sections[0]
    section.page_width  = Cm(21)
    section.page_height = Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.5)
    section.top_margin  = Cm(2.2)
    section.bottom_margin = Cm(2.2)
    section.different_first_page_header_footer = True

    # Header (not first page)
    header = section.header
    hp = header.paragraphs[0]
    hp.clear()
    set_rtl_para(hp)
    r = hp.add_run("בלאק‑ג'ק רב‑משתתפים  |  תיק פרויקט")
    r.font.name  = FONT_HEB
    r.font.size  = Pt(8)
    r.font.color.rgb = C_GRAY_MID
    set_rtl_run(r)
    set_para_border_bottom(hp, HEX_GREEN_DARK, "4")

    # Footer with page number
    footer = section.footer
    fp = footer.paragraphs[0]
    fp.clear()
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = fp.add_run()
    fr.font.name  = FONT_HEB
    fr.font.size  = Pt(8)
    fr.font.color.rgb = C_GRAY_MID
    # page number field
    fldChar1 = OxmlElement("w:fldChar")
    fldChar1.set(qn("w:fldCharType"), "begin")
    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = " PAGE "
    fldChar2 = OxmlElement("w:fldChar")
    fldChar2.set(qn("w:fldCharType"), "end")
    fr._r.append(fldChar1)
    fr._r.append(instrText)
    fr._r.append(fldChar2)

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    md_text = SRC.read_text(encoding="utf-8")
    doc = Document()
    configure_styles(doc)
    setup_header_footer(doc)
    build_cover(doc)
    parse_md(doc, md_text)
    doc.save(str(OUT))
    size_kb = OUT.stat().st_size // 1024
    print(f"✓  Saved → {OUT}  ({size_kb} KB)")

if __name__ == "__main__":
    main()
