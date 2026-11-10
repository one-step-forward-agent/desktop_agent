"""Automation policy, cancellation and serialization; no real personal applications or accounts."""
import json
import threading
from types import SimpleNamespace

import pytest

from deyla_desktop.actions import AUTOMATION_ACTIONS, CONFIRM, ActionError, Actions, result_text
from deyla_desktop.agent import Agent
from deyla_desktop.automation import AutomationError
from deyla_desktop.browser import public_url
from deyla_desktop.windows import Windows


def test_automation_always_requires_confirmation_and_rejects_unattached_uploads(tmp_path):
    assert AUTOMATION_ACTIONS <= CONFIRM
    actions = Actions({"Desktop": tmp_path})
    local = tmp_path / "private.txt"
    local.write_text("synthetic")
    with pytest.raises(ActionError, match="приложенный"):
        actions.run("browser_upload", {"element": "b1", "path": str(local)})
    for destination in (str(tmp_path.parent / "outside.txt"), str(local), str(tmp_path / "run.exe")):
        with pytest.raises(ActionError):
            actions.run("browser_download", {"element": "b1", "destination": destination})


@pytest.mark.parametrize("url", ["file:///C:/Windows", "javascript:alert(1)", "http://127.0.0.1/", "http://192.168.0.1/", "https://user:pass@example.com"])
def test_browser_rejects_local_and_non_web_urls(url):
    with pytest.raises(AutomationError):
        public_url(url)


def test_stop_during_confirmation_prevents_execution(tmp_path):
    actions = Actions({"Desktop": tmp_path})
    calls = []
    class Api:
        def step(self, *args):
            return {"action": {"name": "write_text_file", "arguments": {"path": "Desktop/no.txt", "content": "x"}}}
    agent = Agent(Api(), actions, confirm=lambda _: agent.stop.set() or True, log=lambda *args: calls.append(args))
    assert agent.run("write") == "Остановлено."
    assert not (tmp_path / "no.txt").exists()
    assert calls == []


def test_stop_while_request_is_running_does_not_show_success(tmp_path):
    class Api:
        def step(self, *args):
            agent.stop.set()
            return {"content": "done"}
    agent = Agent(Api(), Actions({"Desktop": tmp_path}), confirm=lambda _: True, log=lambda *_: None)
    assert agent.run("test") == "Остановлено."


def test_automation_failure_does_not_repeat_possible_submission(tmp_path):
    class Api:
        def step(self, *args):
            return {"action": {"name": "browser_click", "arguments": {"element": "b1"}}}
    actions = Actions({"Desktop": tmp_path})
    def failed(*_):
        raise ActionError("partially completed")
    actions._automate = failed
    agent = Agent(Api(), actions, confirm=lambda _: True, log=lambda *_: None)
    assert "partially completed" in agent.run("submit")


def test_result_budget_preserves_json_and_pagination():
    result = {"ok": True, "offset": 24, "elements": [{"id": f"b{i}", "label": "x" * 2000} for i in range(24)]}
    encoded = result_text(result)
    body = json.loads(encoded)
    assert len(encoded) <= 11000
    assert body["next_offset"] == 24 + len(body["elements"])
    assert len(result["elements"]) == 24


def test_overlapping_tasks_are_rejected(tmp_path):
    agent = Agent(None, Actions({"Desktop": tmp_path}), confirm=lambda _: True, log=lambda *_: None)
    agent._running.acquire()
    try:
        with pytest.raises(ActionError, match="уже выполняется"):
            agent.run("another")
    finally:
        agent._running.release()


class Control:
    def __init__(self, name="Name", kind="Edit", pid=12345):
        self.element_info = SimpleNamespace(name=name, control_type=kind, automation_id="field", element=SimpleNamespace(CurrentIsPassword=False))
        self.pid = pid
        self.handle = 99
        self.text = ""
        self.items = []
    def children(self): return self.items
    def process_id(self): return self.pid
    def is_visible(self): return True
    def is_enabled(self): return True
    def window_text(self): return self.text or self.element_info.name
    def top_level_parent(self): return self.parent if hasattr(self, "parent") else self
    def set_edit_text(self, text): self.text = text
    def invoke(self): self.text = "invoked"


def test_windows_control_lifecycle_and_process_restrictions():
    window, terminal = Control("Scratch", "Window"), Control("Terminal", "Window", 54321)
    edit = Control()
    edit.parent = window
    window.items = [edit]
    controller = Windows(desktop=SimpleNamespace(windows=lambda **_: [window, terminal]),
                         process_name=lambda pid: "notepad.exe" if pid == 12345 else "powershell.exe")
    listed = controller.list()
    assert len(listed["windows"]) == 1
    state = controller.observe(listed["windows"][0]["id"])
    element = next(row["id"] for row in state["controls"] if row["type"] == "Edit")
    controller.fill(element, "Привет")
    assert edit.text == "Привет"
    with pytest.raises(AutomationError, match="устарел"):
        controller.fill(element, "stale")
    state = controller.observe()
    element = next(row["id"] for row in state["controls"] if row["type"] == "Edit")
    edit.element_info.element.CurrentIsPassword = True
    with pytest.raises(AutomationError):
        controller.read(element)


def test_client_reports_installed_capabilities(monkeypatch):
    from deyla_desktop.api import DeylaApi
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda _: None)
    api = DeylaApi(base_url="http://local-test.invalid", store=object())
    sent = []
    monkeypatch.setattr(api, "_authed", lambda *args: sent.append(args) or {})
    api.step([{"role": "user", "content": "hi"}], "test", "now")
    capabilities = sent[0][2]["client_actions"]
    assert "open_app" in capabilities and "browser_open" not in capabilities and "windows_list" not in capabilities
