"""The limits of the desktop agent on this computer: only the user's folders, no overwriting, deleting or running programs."""

import os
from pathlib import Path

import pytest

from deyla_desktop.actions import ActionError, Actions
from deyla_desktop.agent import Agent


@pytest.fixture
def sandbox(tmp_path):
    roots = {"Desktop": tmp_path / "Desktop", "Documents": tmp_path / "Documents", "Downloads": tmp_path / "Downloads"}
    for folder in roots.values():
        folder.mkdir()
    (tmp_path / "secret.txt").write_text("outside")
    launched = []
    return Actions(roots, launch=launched.append), tmp_path, launched


def test_paths_stay_inside_the_users_folders(sandbox):
    actions, tmp, _ = sandbox
    assert actions.resolve("Desktop") == (tmp / "Desktop").resolve()
    assert actions.resolve("рабочий стол/", must_exist=False) == (tmp / "Desktop").resolve()
    for path in ["Desktop/../secret.txt", str(tmp / "secret.txt"), "C:/Windows/System32", "Windows", "Desktop/.ssh/key", "Documents/AppData/x"]:
        with pytest.raises(ActionError):
            actions.resolve(path, must_exist=False)


def test_write_creates_appends_but_never_overwrites(sandbox):
    actions, tmp, _ = sandbox
    assert actions.run("write_text_file", {"path": "Desktop/покупки.txt", "content": "молоко"})["ok"]
    with pytest.raises(ActionError, match="перезаписывать"):
        actions.run("write_text_file", {"path": "Desktop/покупки.txt", "content": "пусто"})
    actions.run("write_text_file", {"path": "Desktop/покупки.txt", "content": "хлеб", "append": True})
    assert (tmp / "Desktop" / "покупки.txt").read_text(encoding="utf-8") == "молоко\nхлеб"
    for name in ["Desktop/run.bat", "Desktop/x.ps1", "Desktop/x.exe"]:
        with pytest.raises(ActionError):
            actions.run("write_text_file", {"path": name, "content": "echo"})


def test_move_does_not_replace_and_stays_inside(sandbox):
    actions, tmp, _ = sandbox
    (tmp / "Downloads" / "a.pdf").write_bytes(b"%PDF")
    (tmp / "Documents" / "a.pdf").write_bytes(b"old")
    with pytest.raises(ActionError, match="заменять"):
        actions.run("move_file", {"source": "Downloads/a.pdf", "destination": "Documents"})
    with pytest.raises(ActionError):
        actions.run("move_file", {"source": "Downloads/a.pdf", "destination": str(tmp / "a.pdf")})
    assert actions.run("move_file", {"source": "Downloads/a.pdf", "destination": "Documents/b.pdf"})["to"] == "Documents/b.pdf"


def test_only_listed_programs_and_safe_files_are_opened(sandbox, monkeypatch):
    actions, tmp, launched = sandbox
    actions.run("open_app", {"app": "notepad"})
    assert launched == [["notepad.exe"]]
    with pytest.raises(ActionError):
        actions.run("open_app", {"app": "cmd"})
    (tmp / "Desktop" / "evil.bat").write_text("del *")
    with pytest.raises(ActionError, match="не открывает"):
        actions.run("open_path", {"path": "Desktop/evil.bat"})
    for url in ["file:///C:/Windows", "javascript:alert(1)", "ms-settings:", "https://user:pw@example.com"]:
        with pytest.raises(ActionError):
            actions.run("open_url", {"url": url})


def test_there_is_no_delete_or_shell(sandbox):
    actions, _, _ = sandbox
    for name in ["delete_file", "run_command", "shell", "__init__", "resolve"]:
        with pytest.raises(ActionError):
            actions.run(name, {})


def test_read_list_and_find(sandbox):
    actions, tmp, _ = sandbox
    (tmp / "Documents" / "Отчёт за май.txt").write_text("итого 5", encoding="utf-8")
    (tmp / "Documents" / "big.txt").write_bytes(b"x" * 200_000)
    assert actions.run("read_text_file", {"path": "Documents/Отчёт за май.txt"})["text"] == "итого 5"
    with pytest.raises(ActionError, match="100 КБ"):
        actions.run("read_text_file", {"path": "Documents/big.txt"})
    assert actions.run("find_files", {"pattern": "отчёт"})["found"] == ["Documents/Отчёт за май.txt"]
    assert {entry["name"] for entry in actions.run("list_folder", {"path": "Documents"})["entries"]} == {"Отчёт за май.txt", "big.txt"}


class FakeApi:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def step(self, messages, os_name, local_time):
        self.sent.append([dict(m) for m in messages])
        return self.replies.pop(0)


def test_agent_asks_before_writing_and_reports_a_refusal(sandbox):
    actions, tmp, _ = sandbox
    api = FakeApi([
        {"action": {"name": "write_text_file", "arguments": {"path": "Desktop/a.txt", "content": "x"}}, "confirm": False},
        {"content": "Хорошо, не создаю"},
    ])
    asked = []
    agent = Agent(api, actions, confirm=lambda text: asked.append(text) or False, log=lambda *_: None)
    assert agent.run("создай файл") == "Хорошо, не создаю"
    assert asked and not (tmp / "Desktop" / "a.txt").exists()
    assert "не разрешил" in api.sent[1][-1]["content"]
    assert api.sent[1][-2]["function_call"]["name"] == "write_text_file"


def test_agent_sends_errors_back_and_keeps_short_context(sandbox):
    actions, _, _ = sandbox
    api = FakeApi([{"action": {"name": "read_text_file", "arguments": {"path": "C:/Windows/win.ini"}}}, {"content": "Нет доступа"}, {"content": "Привет"}])
    agent = Agent(api, actions, confirm=lambda _: True, log=lambda *_: None)
    agent.run("прочитай win.ini")
    assert "вне папок" in api.sent[1][-1]["content"]
    agent.run("привет")
    assert [m["role"] for m in api.sent[2]] == ["user", "assistant", "user"]
