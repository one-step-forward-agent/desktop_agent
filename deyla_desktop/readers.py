"""The text of Word (.docx) and Excel (.xlsx) files, read with the standard library only."""

import re
import zipfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
MAX_CHARS = 200_000


def pdf_text(path: Path) -> str:
    """Extract text in a bounded worker, so a malformed PDF cannot hang the chat thread."""
    return _worker("read", path)["text"]


def legacy_word_text(path: Path) -> str:
    return _worker("read", path)["text"]


def convert_word(path: Path, destination: Path) -> None:
    _worker("convert", path, destination)


def export_pdf(path: Path, destination: Path) -> None:
    _worker("pdf", path, destination)


def _worker(operation: str, path: Path, destination: Path | None = None) -> dict:
    import json
    import os
    import shutil
    import subprocess
    import sys
    import tempfile
    with tempfile.TemporaryDirectory(prefix="deyla-document-") as temporary:
        folder = Path(temporary)
        result_file, converted = folder / "result.json", folder / ("converted.pdf" if operation == "pdf" else "converted.docx")
        command = [sys.executable]
        command += ["--document-worker"] if getattr(sys, "frozen", False) else ["-m", "deyla_desktop.document_worker"]
        command += [operation, str(path), str(result_file), str(converted)]
        try:
            subprocess.run(command, timeout=35, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           cwd=Path(__file__).resolve().parent.parent,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            # Only terminate a Word process the worker proved it created, never an existing instance.
            pid_file = folder / "word-process.json"
            if pid_file.exists():
                try:
                    import psutil
                    info = json.loads(pid_file.read_text(encoding="utf-8"))
                    process = psutil.Process(info["pid"])
                    if process.name().lower() == "winword.exe" and process.create_time() == info["created"]:
                        process.terminate()
                except Exception:
                    pass
            raise ValueError("Чтение документа заняло слишком много времени; обработка остановлена") from None
        except subprocess.CalledProcessError:
            raise ValueError("Не удалось запустить обработку документа") from None
        if not result_file.exists() or result_file.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Обработчик документа не вернул результат")
        result = json.loads(result_file.read_text(encoding="utf-8"))
        if not result.get("ok"):
            raise ValueError(result.get("error", "Документ не удалось прочитать"))
        if destination is not None:
            if not converted.exists() or converted.stat().st_size > 20 * 1024 * 1024:
                raise ValueError("Не удалось получить готовый файл до 20 МБ")
            if operation == "pdf":
                from pypdf import PdfReader
                try:
                    with converted.open("rb") as source:
                        if not PdfReader(source).pages:
                            raise ValueError
                except Exception:
                    raise ValueError("Word не создал корректный PDF") from None
            else:
                with zipfile.ZipFile(converted) as archive:
                    if "word/document.xml" not in archive.namelist():
                        raise ValueError("Word не создал корректный DOCX")
            with destination.open("xb") as output, converted.open("rb") as source:
                shutil.copyfileobj(source, output)
        return result


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
