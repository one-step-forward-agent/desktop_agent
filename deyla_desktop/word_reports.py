"""Create a real DOCX from report text, without starting Word or executing embedded code."""
import io
import re

MAX_REPORT_CHARS = 24000


def build_report(content: str, title: str | None = None) -> bytes:
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    if not isinstance(content, str) or not content.strip() or len(content) > MAX_REPORT_CHARS:
        raise ValueError("Для отчёта нужен непустой текст до 24 000 символов")
    if title is not None and (not isinstance(title, str) or len(title) > 200):
        raise ValueError("Заголовок отчёта — до 200 символов")
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Cm(2)
    normal = document.styles["Normal"]
    normal.font.name, normal.font.size = "Times New Roman", Pt(12)
    normal.paragraph_format.space_after = Pt(6)
    for style_name in ("Title", "Heading 1", "Heading 2", "Heading 3"):
        style = document.styles[style_name]
        style.font.name, style.font.bold, style.font.color.rgb = "Times New Roman", True, RGBColor(0, 0, 0)
        style.font.size = Pt(18 if style_name == "Title" else 14)
    code = document.styles.add_style("Deyla Code", WD_STYLE_TYPE.PARAGRAPH)
    code.font.name, code.font.size = "Consolas", Pt(9)
    code.paragraph_format.space_after = Pt(0)
    code.paragraph_format.space_before = Pt(0)
    code.paragraph_format.left_indent = Cm(0.35)
    if title and title.strip():
        document.core_properties.title = title.strip()
        document.add_heading(title.strip(), 0).alignment = WD_ALIGN_PARAGRAPH.CENTER

    lines = content.splitlines()
    index, in_code = 0, False
    while index < len(lines):
        line = lines[index]
        index += 1
        if re.fullmatch(r"\s*```[\w+.-]*\s*", line) and (not in_code or line.strip() == "```"):
            in_code = not in_code
        elif in_code:
            document.add_paragraph(line, style=code)
        elif not line.strip():
            continue
        elif heading := re.fullmatch(r"\s*(#{1,3})\s+(.+)", line):
            document.add_heading(heading[2], len(heading[1]))
        elif bullet := re.fullmatch(r"\s*[-*]\s+(.+)", line):
            document.add_paragraph(bullet[1], style="List Bullet")
        elif index < len(lines) and (rows := _table(line, lines, index)):
            table = document.add_table(rows=len(rows), cols=len(rows[0]))
            table.style = "Table Grid"
            table.autofit = False
            width = (section.page_width - section.left_margin - section.right_margin) // len(rows[0])
            for column in table.columns:
                column.width = width
            for row_number, row in enumerate(rows):
                for column_number, value in enumerate(row):
                    cell = table.cell(row_number, column_number)
                    cell.width = width
                    cell.paragraphs[0].add_run(value).bold = row_number == 0
            index += len(rows)  # Separator plus data rows; header already consumed.
        else:
            document.add_paragraph(line)
    if in_code:
        raise ValueError("Блок кода не закрыт. Отчёт не сохранён: сначала завершите листинг")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _table(header: str, lines: list[str], index: int) -> list[list[str]] | None:
    def cells(line):
        return [part.strip() for part in line.strip().strip("|").split("|")]

    if "|" not in header or "|" not in lines[index]:
        return None
    first, separator = cells(header), cells(lines[index])
    if not 2 <= len(first) <= 8 or len(separator) != len(first) or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
        return None
    rows = [first]
    for line in lines[index + 1:]:
        if "|" not in line or len(cells(line)) != len(first):
            break
        rows.append(cells(line))
    return rows
