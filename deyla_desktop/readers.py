"""The text of Word (.docx) and Excel (.xlsx) files, read with the standard library only."""

import re
import zipfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
MAX_CHARS = 200_000


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for paragraph in root.iter(f"{W}p"):
        text = "".join(node.text or "" for node in paragraph.iter() if node.tag in (f"{W}t", f"{W}tab") and (node.text or node.tag == f"{W}tab"))
        paragraphs.append(text)
    return "\n".join(paragraphs).strip()[:MAX_CHARS]


def xlsx_text(path: Path, max_rows: int = 300) -> str:
    """Each sheet as rows of cells separated by " | "."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            for item in ElementTree.fromstring(archive.read("xl/sharedStrings.xml")).iter(f"{S}si"):
                shared.append("".join(node.text or "" for node in item.iter(f"{S}t")))
        sheets = sorted((name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)), key=lambda name: int(re.findall(r"\d+", name)[0]))
        parts = []
        for number, name in enumerate(sheets, 1):
            rows = []
            for row in ElementTree.fromstring(archive.read(name)).iter(f"{S}row"):
                cells = []
                for cell in row.iter(f"{S}c"):
                    kind, value = cell.get("t"), cell.findtext(f"{S}v")
                    if kind == "s" and value is not None and value.isdigit() and int(value) < len(shared):
                        value = shared[int(value)]
                    elif kind == "inlineStr":
                        value = "".join(node.text or "" for node in cell.iter(f"{S}t"))
                    cells.append(value or "")
                rows.append(" | ".join(cells).rstrip(" |"))
                if len(rows) >= max_rows:
                    rows.append("…")
                    break
            parts.append(f"[Лист {number}]\n" + "\n".join(rows))
    return "\n\n".join(parts).strip()[:MAX_CHARS]
