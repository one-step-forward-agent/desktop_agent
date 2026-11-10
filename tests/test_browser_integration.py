"""Opt-in real browser checks against a synthetic local website, never production."""
import http.server
import json
import os
import threading
from pathlib import Path

import pytest

from deyla_desktop.automation import AutomationError
from deyla_desktop.browser import Browser

pytestmark = pytest.mark.skipif(os.getenv("DEYLA_TEST_BROWSER") != "1", reason="Set DEYLA_TEST_BROWSER=1 for synthetic real-browser checks")
PAGE = """<!doctype html><html><head><title>Synthetic Deyla test</title></head><body>
<h1>Test form</h1><label>Name<input name="name"></label><label>Secret<input type="password" value="never-export-this"></label>
<select aria-label="Currency"><option value="rub">RUB</option><option value="usd">USD</option></select>
<button onclick="document.getElementById('status').textContent='Saved '+document.querySelector('input').value">Save</button>
<p id="status">Ready</p><input type="file" aria-label="Attachment"><a href="/report.txt" download>Download report</a>
<a href="/other" target="_blank">Other tab</a><a href="file:///C:/Windows/win.ini">Forbidden</a>
</body></html>"""


@pytest.fixture
def browser():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            content = b"synthetic report" if self.path == "/report.txt" else PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain" if self.path == "/report.txt" else "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content)
        def log_message(self, *_): pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    def validate(url):
        if not url.startswith(base + "/"):
            raise AutomationError("Blocked test URL")
        return url
    controller = Browser(headless=True, validate_url=validate)
    try:
        yield controller, base
    finally:
        controller.close()
        server.shutdown()
        server.server_close()


def element(state, label):
    return next(row["id"] for row in state["elements"] if row["label"] == label)


def test_browser_fill_select_submit_download_upload_and_stale_ids(browser, tmp_path):
    controller, base = browser
    state = controller.run("open", {"url": base + "/"})
    assert "never-export-this" not in json.dumps(state)
    old = element(state, "Name")
    state = controller.fill(old, "Тест")
    with pytest.raises(AutomationError, match="устарел"):
        controller.fill(old, "wrong")
    state = controller.select(element(state, "Currency"), "usd")
    state = controller.click(element(state, "Save"))
    assert "Saved Тест" in state["text"]
    uploaded = tmp_path / "upload.txt"
    uploaded.write_text("synthetic", encoding="utf-8")
    state = controller.upload(element(state, "Attachment"), str(uploaded))
    target = tmp_path / "report.txt"
    result = controller.download(element(state, "Download report"), str(target))
    assert result["ok"] and target.read_text() == "synthetic report"
    with pytest.raises(AutomationError):
        controller.download(element(state, "Download report"), str(target))
    state = controller.observe()
    with pytest.raises(AutomationError):
        controller.click(element(state, "Forbidden"))


def test_browser_tabs_and_keyboard(browser):
    controller, base = browser
    state = controller.run("open", {"url": base + "/"})
    state = controller.press(element(state, "Name"), "Tab")
    with pytest.raises(AutomationError):
        controller.press(element(state, "Name"), "Control+L")
    controller.click(element(state, "Other tab"))
    controller._page.wait_for_timeout(150)
    state = controller.observe()
    assert len(state["tabs"]) == 2
    other = next(tab["id"] for tab in state["tabs"] if not tab["active"])
    assert controller.tab(other)["url"] == base + "/other"


def test_client_shows_legacy_backend_warning_in_chat(browser):
    controller, base = browser
    controller.run("open", {"url": base + "/"})
    page = controller._page
    page.evaluate("""() => { window.pywebview = {api: {
      start: async () => ({server:'fixture',version:'0.2.1',signed_in:true}),
      status: async () => ({server:'fixture',automation:false,warning:'Ограниченный режим сервера: требуется обновить backend'}),
      abilities: async () => []
    }}; }""")
    html = Path(__file__).resolve().parents[1] / "deyla_desktop/web/index.html"
    page.set_content(html.read_text(encoding="utf-8"))
    page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
    page.wait_for_function("document.querySelector('#capability-status').textContent.includes('Ограниченный режим')")
    assert "backend" in page.locator("#log").inner_text()
    assert page.locator("#chat").is_visible()
