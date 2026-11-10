"""Generate and reopen actual DOCX bytes; no Word process is needed to save a report."""
import zipfile

from docx import Document
import pytest

from deyla_desktop.actions import Actions, ActionError
from deyla_desktop.agent import Agent


def test_docx_contains_complete_code_headings_and_table(tmp_path):
    actions = Actions({"Desktop": tmp_path})
    lines = [f"    value_{index} = {index}  # проверка отступа" for index in range(160)]
    body = "# Результаты\n| Тест | Результат |\n| --- | --- |\n| Первый | Успех |\n\n# Листинг\n```python\ndef sample():\n" + "\n".join(lines) + "\n    return value_159\n```\n# Вывод\nКод сохранён полностью."
    assert len(body) > 5000
    result = actions.run("write_document", {"path": "Desktop/отчёт.docx", "title": "Проверочный отчёт", "content": body})
    file = tmp_path / "отчёт.docx"
    assert result["file"] == "Desktop/отчёт.docx" and result["bytes"] == file.stat().st_size
    with zipfile.ZipFile(file) as archive:
        assert archive.testzip() is None and "word/document.xml" in archive.namelist()
        assert "word/vbaProject.bin" not in archive.namelist()
    document = Document(file)
    assert document.paragraphs[0].text == "Проверочный отчёт"
    assert document.tables[0].cell(1, 1).text == "Успех"
    code = [paragraph.text for paragraph in document.paragraphs if paragraph.style.name == "Deyla Code"]
    assert code == ["def sample():", *lines, "    return value_159"]
    assert document.paragraphs[-1].text == "Код сохранён полностью."


def test_unclosed_code_and_unsafe_destination_leave_no_new_files(tmp_path):
    root = tmp_path / "Desktop"
    root.mkdir()
    actions = Actions({"Desktop": root})
    for path, content in (("Desktop/partial.docx", "```python\nprint("), (str(tmp_path / "outside.docx"), "report"), ("Desktop/report.docm", "report")):
        with pytest.raises(ActionError):
            actions.run("write_document", {"path": path, "content": content})
    assert not list(root.iterdir()) and not (tmp_path / "outside.docx").exists()


def test_report_requires_local_confirmation_and_cannot_overwrite(tmp_path):
    actions = Actions({"Desktop": tmp_path})
    args = {"path": "Desktop/report.docx", "content": "Full synthetic report"}
    class Api:
        def __init__(self): self.calls = 0
        def step(self, *_):
            self.calls += 1
            return {"action": {"name": "write_document", "arguments": args}, "confirm": False} if self.calls == 1 else {"content": "Not saved"}
    prompted = []
    agent = Agent(Api(), actions, confirm=lambda text: prompted.append(text) or False, log=lambda *_: None)
    assert agent.run("create report") == "Not saved"
    assert "Full synthetic report" in prompted[0] and not (tmp_path / "report.docx").exists()
    actions.run("write_document", args)
    original = (tmp_path / "report.docx").read_bytes()
    with pytest.raises(ActionError, match="перезапись"):
        actions.run("write_document", {**args, "content": "replacement"})
    assert (tmp_path / "report.docx").read_bytes() == original
