"""The window drawn like the site: web/index.html in Edge WebView2 (pywebview), the same tokens, glass and chat.

Bridge is the page's window.pywebview.api; its calls run in pywebview's threads, so a task may take as long as it
needs. Python talks back with window.evaluate_js("ui.…"): steps of a task, confirmations (the page answers with
answer(id, ok)), timers. Everything else — signing in, the agent, the actions and their limits — is shared with the
Tk window (app.py), which stays as the fallback when WebView2 is missing.
"""

import ctypes
import json
import os
import platform
import sys
import threading
import webbrowser
from ctypes import wintypes
from itertools import count
from pathlib import Path

from . import __version__, editing
from .actions import Actions, UiHooks, default_roots
from .agent import Agent
from .api import ApiError, DeylaApi, site_url
from .browser_login import BrowserLogin, LoginCancelled

CONFIRM_WAIT = 600


def resource(name: str) -> Path:
    """A file next to this module, also inside the PyInstaller exe (sys._MEIPASS)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "deyla_desktop" / name


def icon_path() -> Path:
    """assets/deyla.ico: in the exe (added by build.ps1) or next to the sources."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / "deyla.ico"


def own_taskbar_icon() -> None:
    """Without its own AppUserModelID the window is grouped under python.exe and shows Python's icon on the taskbar."""
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Deyla.Desktop.Agent")
        except (AttributeError, OSError):
            pass


ABILITIES = [
    "Открыть сайт, поиск в интернете или стандартную программу: Блокнот, Калькулятор, Проводник, Paint, Параметры, Диспетчер задач, Ножницы",
    "Найти, показать, прочитать (текст, Word, Excel) и открыть файлы в папках: {folders}",
    "Прочитать файлы, которые вы приложили 📎, перетащили в окно или вставили из Проводника, где бы они ни лежали",
    "Узнать курсы валют ЦБ РФ и прочитать текст веб-страницы",
    "Создать таблицу Excel, текстовый файл или папку, переместить или переименовать файл — только с вашего разрешения",
    "Буфер обмена (чтение — с разрешения), таймер-напоминание, сведения о компьютере",
]


class WinClipboard:
    """Text on the Windows clipboard without Tk."""

    CF_UNICODETEXT = 13

    def __init__(self):
        self.user32, self.kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self.user32.GetClipboardData.restype = wintypes.HANDLE
        self.kernel32.GlobalLock.restype = wintypes.LPVOID
        self.kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        self.kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        self.kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        self.user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

    def get(self) -> str:
        if not self.user32.OpenClipboard(None):
            return ""
        try:
            handle = self.user32.GetClipboardData(self.CF_UNICODETEXT)
            if not handle:
                return ""
            pointer = self.kernel32.GlobalLock(handle)
            try:
                return ctypes.wstring_at(pointer) if pointer else ""
            finally:
                self.kernel32.GlobalUnlock(handle)
        finally:
            self.user32.CloseClipboard()

    def set(self, text: str) -> None:
        data = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(data)
        if not self.user32.OpenClipboard(None):
            raise OSError("Буфер обмена занят")
        try:
            self.user32.EmptyClipboard()
            handle = self.kernel32.GlobalAlloc(0x0002, size)  # GMEM_MOVEABLE
            pointer = self.kernel32.GlobalLock(handle)
            ctypes.memmove(pointer, data, size)
            self.kernel32.GlobalUnlock(handle)
            self.user32.SetClipboardData(self.CF_UNICODETEXT, handle)
        finally:
            self.user32.CloseClipboard()


class Bridge(UiHooks):
    """window.pywebview.api. Attributes start with "_" so pywebview does not expose them to the page."""

    def __init__(self):
        self._window = None
        self._api = DeylaApi()
        self._actions = Actions(default_roots(), ui=self)
        self._agent = Agent(self._api, self._actions, confirm=self._confirm, log=self._step)
        self._clipboard = WinClipboard() if os.name == "nt" else None
        self._answers: dict[int, tuple[threading.Event, list]] = {}
        self._ids = count(1)
        self._login: BrowserLogin | None = None

    def _js(self, function: str, *args) -> None:
        if self._window:
            self._window.evaluate_js(f"ui.{function}({', '.join(json.dumps(arg, ensure_ascii=False) for arg in args)})")

    # ---------- what the agent needs from the window ----------

    def _step(self, kind: str, text: str) -> None:
        self._js("step", kind, text.split("\n\n")[0].rstrip(" :"))

    def _confirm(self, description: str) -> bool:
        number = next(self._ids)
        event, box = threading.Event(), []
        self._answers[number] = (event, box)
        self._js("confirm", number, description)
        answered = event.wait(CONFIRM_WAIT)
        self._answers.pop(number, None)
        return bool(answered and box and box[0])

    def set_clipboard(self, text: str) -> None:
        self._clipboard.set(text)

    def get_clipboard(self) -> str:
        return self._clipboard.get() if self._clipboard else ""

    def set_timer(self, minutes: int, text: str) -> None:
        def ring():
            self._actions.timers = max(0, self._actions.timers - 1)
            if os.name == "nt":
                ctypes.windll.user32.MessageBeep(0x40)
            if self._window:
                self._window.restore()
                self._window.on_top = True
                self._js("reminder", text)
                threading.Timer(3, lambda: setattr(self._window, "on_top", False)).start()

        timer = threading.Timer(minutes * 60, ring)
        timer.daemon = True
        timer.start()

    # ---------- the page's calls ----------

    def answer(self, number: int, ok: bool) -> None:
        waiting = self._answers.get(int(number))
        if waiting:
            waiting[1].append(bool(ok))
            waiting[0].set()

    def start(self) -> dict:
        state = {"server": self._api.base_url, "version": __version__, "signed_in": False, "error": ""}
        try:
            state["signed_in"] = self._api.resume()
        except ApiError as error:
            state["error"] = error.detail
        return state

    def login_password(self, email: str, password: str) -> dict:
        try:
            self._api.login(email, password)
            return {"ok": True}
        except ApiError as error:
            return {"ok": False, "error": error.detail}

    def login_browser(self) -> dict:
        self._login = BrowserLogin(site_url(self._api.base_url))
        try:
            self._login.start()
            code, verifier = self._login.wait()
            self._api.login_with_code(code, verifier)
            return {"ok": True}
        except (LoginCancelled, ApiError) as error:
            return {"ok": False, "error": getattr(error, "detail", str(error))}
        except OSError as error:
            return {"ok": False, "error": f"Не удалось открыть браузер: {error}"}
        finally:
            self._login = None

    def logout(self) -> None:
        self._agent.forget()
        self._api.logout()

    def send(self, text: str, files: list) -> dict:
        attached = []
        for path in files or []:
            try:
                attached.append(str(self._actions.attach(path)))
            except Exception:
                continue
        task = (text.strip() or "Посмотри приложенные файлы") + "".join(f"\nПриложен файл: {path}" for path in attached)
        try:
            return {"answer": self._agent.run(task)}
        except ApiError as error:
            if error.status == 401:
                return {"relogin": True, "error": "Сессия истекла, войдите снова"}
            return {"error": error.detail}
        except Exception as error:  # shown in the chat rather than lost
            return {"error": f"Что-то пошло не так: {error}"}

    def stop(self) -> None:
        self._agent.stop.set()
        for event, box in list(self._answers.values()):
            box.append(False)
            event.set()

    def new_chat(self) -> None:
        self._agent.forget()

    def abilities(self) -> list[str]:
        folders = ", ".join(self._actions.roots)
        return [line.format(folders=folders) for line in ABILITIES]

    def pick_files(self) -> list[str]:
        import webview

        chosen = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True) if self._window else None
        return list(chosen or [])

    def clipboard_files(self) -> list[str]:
        return editing.clipboard_files()

    def open_link(self, url: str) -> None:
        if str(url).startswith(("http://", "https://")):
            webbrowser.open(url)

    def _closing(self) -> None:
        if self._login:
            self._login.cancel()
        self.stop()


def _on_drop(bridge: Bridge, event: dict) -> None:
    """Files dropped on the window: pywebview gives their full paths."""
    files = [item.get("pywebviewFullPath") for item in (event.get("dataTransfer") or {}).get("files") or []]
    paths = [path for path in files if path and os.path.isfile(path)]
    if paths:
        bridge._js("attach", paths)


def run() -> None:
    import webview
    from webview.dom import DOMEventHandler

    bridge = Bridge()
    window = webview.create_window(
        "Deyla — помощник на компьютере",
        url=str(resource("web/index.html")),
        js_api=bridge,
        width=880,
        height=760,
        min_size=(520, 520),
        background_color="#f6f7fb",
        text_select=True,
    )
    bridge._window = window
    window.events.closing += bridge._closing

    def loaded():
        window.dom.document.events.drop += DOMEventHandler(lambda event: _on_drop(bridge, event), True, True)

    window.events.loaded += loaded
    own_taskbar_icon()
    icon = icon_path()
    webview.start(gui="edgechromium", icon=str(icon) if icon.is_file() else None, private_mode=False, storage_path=str(Path(os.environ.get("APPDATA") or Path.home()) / "Deyla" / "webview"))


def available() -> bool:
    """Edge WebView2 and pywebview are there (Windows 10/11 have WebView2; very old systems may not)."""
    if os.name != "nt" or platform.release() not in ("10", "11"):
        return False
    try:
        import webview  # noqa: F401
    except Exception:
        return False
    return True
