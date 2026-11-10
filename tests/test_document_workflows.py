"""Regression cases from attached PDFs outside Desktop and blocked search pages."""
import json
import zipfile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from deyla_desktop.actions import Actions, ActionError
from deyla_desktop.agent import Agent
from deyla_desktop.api import DeylaApi


def make_pdf(path, text=None, password=None):
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    if text is not None:
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        content = DecodedStreamObject()
        content.set_data(("BT /F1 12 Tf 10 700 Td (" + text + ") Tj ET").encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
    if password:
        writer.encrypt(password)
    with path.open("wb") as output:
        writer.write(output)


def test_attached_pdf_outside_roots_is_read_before_the_first_model_request(tmp_path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    source = tmp_path / "lab.pdf"
    make_pdf(source, "Variant 1 " + "A" * 6000 + " Variant 2 Calculate 7 plus 5")
    actions = Actions({"Desktop": desktop})
    actions.attach(source)
    sent = []
    class Api:
        def step(self, messages, *_):
            sent.extend(messages)
            return {"content": "12"}
    agent = Agent(Api(), actions, confirm=lambda _: True, log=lambda *_: None)
    assert agent.run("вариант 2", attachments=[str(source)]) == "12"
    assert "Calculate 7 plus 5" in sent[0]["content"]
    assert str(source) in sent[0]["content"]
    assert len(sent[0]["content"]) < 11800
    first = actions.run("read_text_file", {"path": str(source)})
    assert first["next_offset"] is not None
    second = actions.run("read_text_file", {"path": str(source), "offset": first["next_offset"]})
    assert "Calculate 7 plus 5" in second["text"]


def test_explicit_attachment_can_be_opened_but_other_outside_files_cannot(tmp_path, monkeypatch):
    import deyla_desktop.actions as module
    root = tmp_path / "Desktop"
    root.mkdir()
    source, other = tmp_path / "selected.pdf", tmp_path / "unselected.pdf"
    source.write_bytes(b"%PDF")
    other.write_bytes(b"%PDF")
    actions = Actions({"Desktop": root})
    actions.attach(source)
    opened = []
    if module.os.name == "nt":
        monkeypatch.setattr(module.os, "startfile", opened.append)
    else:
        monkeypatch.setattr(module.webbrowser, "open", opened.append)
    assert actions.run("open_path", {"path": str(source)})["ok"]
    assert len(opened) == 1
    with pytest.raises(ActionError):
        actions.run("open_path", {"path": str(other)})
    program = tmp_path / "evil.exe"
    program.write_bytes(b"synthetic")
    actions.attach(program)
    with pytest.raises(ActionError):
        actions.run("open_path", {"path": str(program)})


@pytest.mark.parametrize("password,expected", [(None, "OCR"), ("synthetic", "паролем")])
def test_scans_and_password_protection_get_specific_errors(tmp_path, password, expected):
    source = tmp_path / "test.pdf"
    make_pdf(source, password=password)
    actions = Actions({"Desktop": tmp_path})
    with pytest.raises(ActionError, match=expected):
        actions.run("read_text_file", {"path": str(source)})


def test_doc_conversion_uses_new_output_and_preserves_original(tmp_path, monkeypatch):
    from deyla_desktop import readers
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    source = tmp_path / "old.doc"
    source.write_bytes(b"original")
    actions = Actions({"Desktop": desktop})
    actions.attach(source)
    def convert(origin, target):
        assert origin == source
        with zipfile.ZipFile(target, "x") as archive:
            archive.writestr("word/document.xml", "<document/>")
    monkeypatch.setattr(readers, "convert_word", convert)
    result = actions.run("convert_document", {"path": str(source)})
    assert result["file"] == "Desktop/old.docx"
    assert source.read_bytes() == b"original"
    with pytest.raises(ActionError):
        actions.run("convert_document", {"path": str(source)})
    with pytest.raises(ActionError):
        actions.run("convert_document", {"path": str(source), "destination": str(tmp_path / "outside.docx")})


def test_search_reader_uses_browser_on_http_failure_and_returns_results(monkeypatch, tmp_path):
    import deyla_desktop.actions as module
    import deyla_desktop.browser as browser_module
    actions = Actions({"Desktop": tmp_path})
    def failed(_): raise ActionError("HTTP 403")
    monkeypatch.setattr(module, "_fetch", failed)
    monkeypatch.setattr(browser_module, "public_url", lambda url: url)
    monkeypatch.setattr(actions, "_automate", lambda *args: {"ok": True, "text": "Synthetic gym trial training", "elements": [{"href": "https://example.com/gym", "label": "Gym"}]})
    result = actions.run("read_web_page", {"url": "https://example.com/search"})
    assert result["reader"] == "interactive_browser"
    assert "trial training" in result["text"] and result["elements"][0]["href"].endswith("/gym")


def test_old_backend_is_reported_as_limited_mode():
    api = DeylaApi(base_url="http://fixture.invalid", store=object())
    api._authed = lambda *args: {"actions": [{"name": "read_web_page"}]}
    assert "backend" in api.capability_status()["warning"]
    assert api.capability_status()["automation"] is False
    api._capabilities = None
    api._authed = lambda *args: {"actions": [{"name": name} for name in ("browser_open", "browser_fill", "windows_observe")]}
    assert api.capability_status()["automation"] is True


@pytest.mark.skipif(__import__("os").name != "nt", reason="Word adapter imports Windows COM")
def test_word_adapter_disables_macros_and_preserves_existing_session(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import pythoncom
    import psutil
    import win32com.client
    import win32process
    from deyla_desktop.document_worker import word_document
    calls = []
    target = tmp_path / "converted.docx"
    class Document:
        Content = SimpleNamespace(Text="Synthetic legacy document")
        def SaveAs2(self, **kwargs):
            assert kwargs["FileFormat"] == 12 and kwargs["AddToRecentFiles"] is False
            calls.append("save")
        def Close(self, **kwargs): calls.append("close")
    class Documents:
        def Open(self, **kwargs):
            assert word.AutomationSecurity == 3 and word.Options.UpdateLinksAtOpen is False
            assert kwargs["ReadOnly"] is True and kwargs["AddToRecentFiles"] is False
            calls.append("open")
            return Document()
    word = SimpleNamespace(Hwnd=123, Options=SimpleNamespace(UpdateLinksAtOpen=True), Documents=Documents(), Quit=lambda **kwargs: calls.append("quit"))
    monkeypatch.setattr(pythoncom, "CoInitialize", lambda: None)
    monkeypatch.setattr(pythoncom, "CoUninitialize", lambda: None)
    monkeypatch.setattr(psutil, "process_iter", lambda *_: [])
    monkeypatch.setattr(psutil, "Process", lambda _: SimpleNamespace(create_time=lambda: 123.0))
    monkeypatch.setattr(win32process, "GetWindowThreadProcessId", lambda _: (1, 98765))
    monkeypatch.setattr(win32com.client, "DispatchEx", lambda _: word)
    result = word_document(tmp_path / "old.doc", target, tmp_path, "convert")
    assert result["text"] == "Synthetic legacy document"
    assert calls == ["open", "save", "close", "quit"]
    assert word.Options.UpdateLinksAtOpen is True
