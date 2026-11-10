"""Excel tables, currency rates, web pages, attached files and Word/Excel reading; pasting in the Russian layout."""

import tkinter as tk
import zipfile
from pathlib import Path

import pytest

from deyla_desktop import actions as actions_module
from deyla_desktop import editing, readers, xlsx
from deyla_desktop.actions import ActionError, Actions

CBR = """<?xml version="1.0" encoding="windows-1251"?><ValCurs Date="04.11.2026" name="Foreign Currency Market">
<Valute ID="R01235"><NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal><Name>Доллар США</Name><Value>81,6699</Value></Valute>
<Valute ID="R01820"><NumCode>392</NumCode><CharCode>JPY</CharCode><Nominal>100</Nominal><Name>Японских иен</Name><Value>53,1000</Value></Valute>
</ValCurs>""".encode("cp1251")


@pytest.fixture
def sandbox(tmp_path):
    roots = {"Desktop": tmp_path / "Desktop", "Documents": tmp_path / "Documents"}
    for folder in roots.values():
        folder.mkdir()
    return Actions(roots, launch=lambda _: None), tmp_path


def test_rates_come_from_the_central_bank_per_one_unit(sandbox, monkeypatch):
    actions, _ = sandbox
    asked = []
    monkeypatch.setattr(actions_module, "_fetch", lambda url: asked.append(url) or (CBR, url, "application/xml"))
    found = actions.run("currency_rates", {"codes": ["usd", "JPY", "XXX"], "date": "2026-11-04"})
    assert asked == ["https://www.cbr.ru/scripts/XML_daily.asp?date_req=04/11/2026"]
    assert found["date"] == "04.11.2026" and found["not_found"] == ["XXX"]
    assert found["rates"]["USD"]["rub_per_unit"] == 81.6699 and found["rates"]["JPY"]["rub_per_unit"] == 0.531


def test_a_spreadsheet_is_a_real_xlsx_that_is_never_overwritten(sandbox):
    actions, tmp = sandbox
    rows = [["Код", "Валюта", "Рублей за 1"], ["USD", "Доллар <США> & co", 81.6699], ["EUR", "Евро", 91.601]]
    assert actions.run("write_spreadsheet", {"path": "Desktop/Курсы валют", "rows": rows})["file"] == "Desktop/Курсы валют.xlsx"
    file = tmp / "Desktop" / "Курсы валют.xlsx"
    assert zipfile.ZipFile(file).testzip() is None
    assert readers.xlsx_text(file) == "[Лист 1]\nКод | Валюта | Рублей за 1\nUSD | Доллар <США> & co | 81.6699\nEUR | Евро | 91.601"
    with pytest.raises(ActionError, match="перезаписывать"):
        actions.run("write_spreadsheet", {"path": "Desktop/Курсы валют.xlsx", "rows": rows})
    actions.run("write_spreadsheet", {"path": "Documents/курсы.csv", "rows": rows})
    assert (tmp / "Documents" / "курсы.csv").read_text(encoding="utf-8-sig").splitlines()[1] == "USD;Доллар <США> & co;81.6699"
    for bad in ({"path": "Desktop/x.exe", "rows": rows}, {"path": "Desktop/y.xlsx", "rows": "нет"}, {"path": "C:/Windows/z.xlsx", "rows": rows}):
        with pytest.raises(ActionError):
            actions.run("write_spreadsheet", bad)
    assert "write_spreadsheet" in actions_module.CONFIRM


def test_web_pages_only_from_the_internet(sandbox, monkeypatch):
    actions, _ = sandbox
    for url in ["http://127.0.0.1:8000/", "http://localhost/", "http://192.168.0.1/", "http://10.0.0.5/admin", "file:///C:/Windows/win.ini", "ftp://example.com/"]:
        with pytest.raises(ActionError):
            actions.run("read_web_page", {"url": url})
    page = b"<html><head><title>t</title></head><script>steal()</script><body><h1>Rates</h1><table><tr><td>USD</td><td>81,67</td></tr></table></body></html>"
    monkeypatch.setattr(actions_module, "_fetch", lambda url: (page, url, "text/html; charset=utf-8"))
    text = actions.run("read_web_page", {"url": "https://example.com/rates"})["text"]
    assert "steal" not in text and "Rates" in text and "USD | 81,67 |" in text
    monkeypatch.setattr(actions_module, "_fetch", lambda url: (b"\x89PNG", url, "image/png"))
    with pytest.raises(ActionError, match="не веб-страница"):
        actions.run("read_web_page", {"url": "https://example.com/a.png"})


def test_attached_files_are_readable_wherever_they_are_but_only_those(sandbox):
    actions, tmp = sandbox
    outside = tmp / "elsewhere"
    outside.mkdir()
    note, other = outside / "заметка.txt", outside / "другая.txt"
    note.write_text("секретный план", encoding="utf-8")
    other.write_text("не приложена", encoding="utf-8")
    with pytest.raises(ActionError):
        actions.run("read_text_file", {"path": str(note)})
    actions.attach(note)
    assert actions.run("read_text_file", {"path": str(note)})["text"] == "секретный план"
    with pytest.raises(ActionError):
        actions.run("read_text_file", {"path": str(other)})
    # Attached means readable, not writable or movable
    with pytest.raises(ActionError):
        actions.run("move_file", {"source": str(note), "destination": "Desktop"})


def test_word_and_excel_files_are_read(sandbox):
    actions, tmp = sandbox
    docx = tmp / "Documents" / "отчёт.docx"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                         "<w:p><w:r><w:t>Итоги</w:t></w:r></w:p><w:p><w:r><w:t>Выручка </w:t></w:r><w:r><w:t>выросла</w:t></w:r></w:p></w:body></w:document>")
    assert actions.run("read_text_file", {"path": "Documents/отчёт.docx"})["text"] == "Итоги\nВыручка выросла"
    xlsx.write(tmp / "Documents" / "t.xlsx", [["a", 1]])
    assert "a | 1" in actions.run("read_text_file", {"path": "Documents/t.xlsx"})["text"]
    (tmp / "Documents" / "fake.docx").write_text("not a zip")
    with pytest.raises(ActionError, match="повреждён"):
        actions.run("read_text_file", {"path": "Documents/fake.docx"})


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    # Shown once off screen: Tk drops events for a window that was never mapped
    window.geometry("+-3000+-3000")
    window.update()
    yield window
    window.destroy()


def test_ctrl_v_pastes_in_the_russian_layout(root):
    field = tk.Text(root)
    field.pack()
    root.update()
    editing.fix_shortcuts(field)
    root.clipboard_clear()
    root.clipboard_append("вставленный текст")
    root.update()
    field.focus_force()
    # Ctrl+М: the V key with the Russian layout, as Windows reports it — Tk alone does nothing here
    assert editing.shortcut(field, 86, "Cyrillic_em") == "break"
    root.update()
    assert field.get("1.0", "end-1c") == "вставленный текст"
    assert editing.shortcut(field, 65, "Cyrillic_ef") == "break"
    assert field.get("sel.first", "sel.last") == "вставленный текст"
    # The English layout is left to Tk, so nothing is pasted twice
    assert editing.shortcut(field, 86, "v") is None
