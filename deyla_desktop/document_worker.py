"""Fixed document parsing/conversion subprocess; no commands or code supplied by the model."""
import json
import os
from pathlib import Path
import sys

MAX_CHARS = 200_000


class DocumentError(ValueError):
    """Only these curated messages may be shown to the user."""


def read_pdf(path):
    from pypdf import PdfReader
    with path.open("rb") as source:
        reader = PdfReader(source)
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentError("PDF защищён паролем; приложите доступную для чтения копию")
        parts, size = [], 0
        for number, page in enumerate(reader.pages):
            if number >= 100 or size >= MAX_CHARS:
                break
            content = page.get_contents()
            if content is not None and len(content.get_data()) > 4 * 1024 * 1024:
                raise DocumentError("Страница PDF слишком сложная для безопасного извлечения текста")
            text = (page.extract_text() or "")[:MAX_CHARS - size]
            if text.strip():
                parts.append(f"[Страница {number + 1}]\n{text}")
                size += len(text)
        if not parts:
            raise DocumentError("В PDF нет извлекаемого текста: вероятно, это скан. Для такого файла нужен OCR")
        return {"ok": True, "text": "\n\n".join(parts)[:MAX_CHARS], "pages": len(reader.pages)}


def word_document(path, converted, result_folder, operation):
    if os.name != "nt":
        raise DocumentError("Для старого формата .doc требуется установленный Microsoft Word в Windows")
    import pythoncom
    import psutil
    import win32com.client
    import win32process
    existing = {process.pid for process in psutil.process_iter(["name"]) if (process.info["name"] or "").lower() == "winword.exe"}
    pythoncom.CoInitialize()
    word = document = None
    owned = False
    try:
        try:
            word = win32com.client.DispatchEx("Word.Application")
        except Exception:
            raise DocumentError("Для этой операции нужен установленный Microsoft Word. Создание нового DOCX доступно без Word") from None
        probe = None
        try:
            try:
                handle = word.Hwnd
            except AttributeError:
                # Word exposes HWND on Window, not Application, in some installations.
                if word.Documents.Count:
                    raise DocumentError("Не удалось создать отдельный Word; существующий сеанс не будет изменён") from None
                probe = word.Documents.Add(Visible=False)
                handle = probe.ActiveWindow.Hwnd
            pid = win32process.GetWindowThreadProcessId(handle)[1]
            if pid <= 0 or pid in existing:
                raise DocumentError("Не удалось создать отдельный Word; существующий сеанс пользователя не будет изменён")
            owned = True
            process = psutil.Process(pid)
            (result_folder / "word-process.json").write_text(json.dumps({"pid": pid, "created": process.create_time()}), encoding="utf-8")
        finally:
            if probe is not None:
                probe.Close(SaveChanges=0)
        word.Visible = False
        word.DisplayAlerts = 0
        word.AutomationSecurity = 3  # msoAutomationSecurityForceDisable, before opening untrusted documents.
        old_links = word.Options.UpdateLinksAtOpen
        word.Options.UpdateLinksAtOpen = False
        try:
            document = word.Documents.Open(FileName=str(path), ConfirmConversions=False, ReadOnly=True,
                                           AddToRecentFiles=False, PasswordDocument="", WritePasswordDocument="", Visible=False, NoEncodingDialog=True)
            text = "" if operation == "pdf" else document.Content.Text[:MAX_CHARS]
            if operation == "convert":
                document.SaveAs2(FileName=str(converted), FileFormat=12, AddToRecentFiles=False)  # wdFormatXMLDocument
            elif operation == "pdf":
                document.ExportAsFixedFormat(OutputFileName=str(converted), ExportFormat=17, OpenAfterExport=False)  # wdExportFormatPDF
            return {"ok": True, "text": text}
        finally:
            word.Options.UpdateLinksAtOpen = old_links
    finally:
        if document is not None:
            try:
                document.Close(SaveChanges=0)
            except Exception:
                pass
        if word is not None and owned:
            try:
                word.Quit(SaveChanges=0)
            except Exception:
                pass
        pythoncom.CoUninitialize()


def main(arguments=None):
    operation, filename, result_name, converted_name = arguments or sys.argv[1:]
    result_file = Path(result_name)
    try:
        path = Path(filename).resolve(strict=True)
        if operation not in {"read", "convert", "pdf"} or path.stat().st_size > 20 * 1024 * 1024:
            raise DocumentError("Неподдерживаемая операция или документ больше 20 МБ")
        if path.suffix.lower() == ".pdf" and operation == "read":
            result = read_pdf(path)
        elif (path.suffix.lower() == ".doc" and operation in {"read", "convert"}) or (path.suffix.lower() == ".docx" and operation == "pdf"):
            result = word_document(path, Path(converted_name), result_file.parent, operation)
        else:
            raise DocumentError("Неподдерживаемый формат документа")
    except DocumentError as error:
        result = {"ok": False, "error": str(error)}
    except Exception:
        result = {"ok": False, "error": "Документ повреждён, защищён или недоступен для чтения"}
    result_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
