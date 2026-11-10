"""The window: sign-in, the chat with the agent, the action log, confirmations and timers.

Network requests and actions run in a worker thread; anything that touches Tk is sent back to the main thread
through on_main(), which waits for the result.
"""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from . import __version__, editing
from .actions import Actions, UiHooks, default_roots
from .agent import Agent
from .api import ApiError, DeylaApi, site_url
from .browser_login import BrowserLogin

TITLE = "Дейла — помощник на компьютере"
EXAMPLES = "Например: «создай Excel с курсами валют к рублю», «найди в загрузках pdf за эту неделю», «создай на рабочем столе файл покупки.txt со списком», «напомни через 20 минут выключить чайник». Файлы можно приложить кнопкой 📎 или вставить из Проводника (Ctrl+V)."


class App(UiHooks):
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(TITLE)
        from .webapp import icon_path, own_taskbar_icon

        own_taskbar_icon()
        if icon_path().is_file():
            self.root.iconbitmap(default=str(icon_path()))
        self.root.geometry("640x620")
        self.root.minsize(480, 420)
        self.calls: queue.Queue = queue.Queue()
        self.root.after(50, self._pump)
        self.api = DeylaApi()
        self.actions = Actions(default_roots(), ui=self)
        self.agent = Agent(self.api, self.actions, confirm=self._confirm, log=self._log_from_worker)
        self.busy = False
        self.frame: ttk.Frame | None = None
        self.root.after(10, self._start)

    # ---------- threads ----------

    def _pump(self) -> None:
        while True:
            try:
                function, box, done = self.calls.get_nowait()
            except queue.Empty:
                break
            try:
                box.append(function())
            except Exception as error:  # returned to the worker
                box.append(error)
            done.set()
        self.root.after(50, self._pump)

    def on_main(self, function):
        if threading.current_thread() is threading.main_thread():
            return function()
        box, done = [], threading.Event()
        self.calls.put((function, box, done))
        done.wait()
        if isinstance(box[0], Exception):
            raise box[0]
        return box[0]

    def _in_background(self, work, then) -> None:
        def run():
            try:
                result, error = work(), None
            except Exception as failure:
                result, error = None, failure
            self.on_main(lambda: then(result, error))

        threading.Thread(target=run, daemon=True).start()

    # ---------- UiHooks ----------

    def set_clipboard(self, text: str) -> None:
        def put():
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        self.on_main(put)

    def get_clipboard(self) -> str:
        def get():
            try:
                return self.root.clipboard_get()
            except tk.TclError:
                return ""
        return self.on_main(get)

    def set_timer(self, minutes: int, text: str) -> None:
        def ring():
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.bell()
            messagebox.showinfo("Напоминание Дейлы", text, parent=self.root)
            self.root.attributes("-topmost", False)
            self.actions.timers = max(0, self.actions.timers - 1)
        self.on_main(lambda: self.root.after(minutes * 60 * 1000, ring))

    def _confirm(self, description: str) -> bool:
        return self.on_main(lambda: messagebox.askyesno("Разрешить действие?", description + "\n\nРазрешить?", parent=self.root, icon="warning"))

    # ---------- screens ----------

    def _clear(self) -> None:
        if self.frame:
            self.frame.destroy()
        self.frame = ttk.Frame(self.root, padding=16)
        self.frame.pack(fill="both", expand=True)

    def _start(self) -> None:
        self._clear()
        ttk.Label(self.frame, text="Подключение…").pack(pady=40)
        self._in_background(self.api.resume, lambda ok, error: self._chat() if ok else self._login(str(error) if error else ""))

    def _login(self, problem: str = "") -> None:
        self._clear()
        ttk.Label(self.frame, text="Вход в Дейлу", font=("Segoe UI", 16, "bold")).pack(pady=(30, 12))
        browser_button = ttk.Button(self.frame, text="🌐  Войти через браузер (Google, Яндекс, email)")
        browser_button.pack(ipady=6, padx=80, fill="x")
        ttk.Label(self.frame, text="Откроется сайт Deyla — нажмите там «Разрешить»", foreground="#666").pack(pady=(4, 0))
        browser_status = ttk.Label(self.frame, text="", foreground="#666", wraplength=420)
        browser_status.pack(pady=(4, 0))

        def through_browser():
            self.browser_login = BrowserLogin(site_url(self.api.base_url))
            browser_button.state(["disabled"])
            browser_status.config(text="Ждём подтверждения в браузере…", foreground="#666")

            def work():
                self.browser_login.start()
                code, verifier = self.browser_login.wait()
                self.api.login_with_code(code, verifier)

            def done(_, error):
                if error:
                    browser_button.state(["!disabled"])
                    browser_status.config(text=getattr(error, "detail", str(error)), foreground="#b00020")
                else:
                    self._chat()
            self._in_background(work, done)

        browser_button.config(command=through_browser)
        ttk.Separator(self.frame).pack(fill="x", padx=80, pady=16)
        ttk.Label(self.frame, text="или email и пароль от сайта", foreground="#666").pack(pady=(0, 8))
        email, password = tk.StringVar(), tk.StringVar()
        ttk.Label(self.frame, text="Email").pack(anchor="w", padx=80)
        email_entry = ttk.Entry(self.frame, textvariable=email, width=40)
        email_entry.pack(padx=80, fill="x")
        ttk.Label(self.frame, text="Пароль").pack(anchor="w", padx=80, pady=(8, 0))
        ttk.Entry(self.frame, textvariable=password, show="•", width=40).pack(padx=80, fill="x")
        status = ttk.Label(self.frame, text=problem, foreground="#b00020", wraplength=420)
        status.pack(pady=8)
        button = ttk.Button(self.frame, text="Войти")
        button.pack()
        ttk.Label(self.frame, text=f"Сервер: {self.api.base_url} · версия {__version__}", foreground="#999").pack(side="bottom")

        def submit(_event=None):
            if not email.get().strip() or not password.get():
                status.config(text="Введите email и пароль")
                return
            button.state(["disabled"])
            status.config(text="Входим…", foreground="#666")

            def done(_, error):
                if error:
                    button.state(["!disabled"])
                    status.config(text=getattr(error, "detail", str(error)), foreground="#b00020")
                else:
                    self._chat()
            self._in_background(lambda: self.api.login(email.get(), password.get()), done)

        button.config(command=submit)
        self.root.bind("<Return>", submit)
        email_entry.focus_set()

    def _chat(self) -> None:
        self.root.unbind("<Return>")
        self._clear()
        self._in_background(self.api.capability_status, lambda status, error: self._write("hint", status["warning"]) if status and status.get("warning") else None)
        top = ttk.Frame(self.frame)
        top.pack(fill="x")
        ttk.Label(top, text="Дейла", font=("Segoe UI", 14, "bold")).pack(side="left")
        ttk.Button(top, text="Выйти", command=self._logout).pack(side="right")
        ttk.Button(top, text="Что я умею", command=self._help).pack(side="right", padx=6)
        ttk.Button(top, text="Новый разговор", command=self._new).pack(side="right")

        self.log = scrolledtext.ScrolledText(self.frame, wrap="word", state="disabled", font=("Segoe UI", 10), height=20, relief="flat", background="#fafafa")
        self.log.pack(fill="both", expand=True, pady=10)
        for tag, options in {
            "user": {"foreground": "#1a4f9c", "font": ("Segoe UI", 10, "bold")},
            "agent": {"foreground": "#222"},
            "action": {"foreground": "#2e7d32", "font": ("Segoe UI", 9)},
            "denied": {"foreground": "#9e6a00", "font": ("Segoe UI", 9)},
            "error": {"foreground": "#b00020", "font": ("Segoe UI", 9)},
            "hint": {"foreground": "#888", "font": ("Segoe UI", 9, "italic")},
        }.items():
            self.log.tag_config(tag, **options)
        self._write("hint", EXAMPLES)

        editing.readonly_menu(self.log)

        self.attachments: list[str] = []
        self.attached_label = ttk.Label(self.frame, text="", foreground="#1a4f9c", cursor="hand2", wraplength=600)
        self.attached_label.pack(fill="x")
        self.attached_label.bind("<Button-1>", lambda _e: self._clear_attachments())
        bottom = ttk.Frame(self.frame)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="📎", width=3, command=self._pick_files).pack(side="left", padx=(0, 6), anchor="n")
        # Several lines: Enter sends, Shift+Enter starts a new line; long pasted text fits
        self.entry = tk.Text(bottom, height=3, wrap="word", font=("Segoe UI", 11), relief="solid", borderwidth=1, undo=True)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self._on_enter)
        self.entry.bind("<<Paste>>", self._on_paste)
        editing.fix_shortcuts(self.entry)
        editing.context_menu(self.entry)
        buttons = ttk.Frame(bottom)
        buttons.pack(side="left", padx=(6, 0), anchor="n")
        self.send_button = ttk.Button(buttons, text="Отправить", command=self._send)
        self.send_button.pack(fill="x")
        self.stop_button = ttk.Button(buttons, text="Стоп", command=self.agent.stop.set, state="disabled")
        self.stop_button.pack(fill="x", pady=(4, 0))
        self.entry.focus_set()

    # ---------- the input ----------

    def _on_enter(self, event):
        if event.state & 0x1:  # Shift: a new line
            return None
        self._send()
        return "break"

    def _on_paste(self, _event):
        """Files copied in Explorer are attached; text is pasted as usual."""
        files = editing.clipboard_files()
        if not files:
            return None
        self._attach(files)
        return "break"

    def _pick_files(self) -> None:
        from tkinter import filedialog

        files = filedialog.askopenfilenames(parent=self.root, title="Приложить файлы")
        if files:
            self._attach(list(files))

    def _attach(self, files: list[str]) -> None:
        for path in files:
            try:
                file = str(self.actions.attach(path))
            except Exception:
                continue
            if file not in self.attachments:
                self.attachments.append(file)
        self._show_attachments()

    def _show_attachments(self) -> None:
        from pathlib import Path

        names = ", ".join(Path(path).name for path in self.attachments)
        self.attached_label.config(text=f"📎 {names}   ✕ убрать" if names else "")

    def _clear_attachments(self) -> None:
        self.attachments = []
        self._show_attachments()

    # ---------- chat ----------

    def _write(self, kind: str, text: str) -> None:
        prefix = {"user": "Вы: ", "agent": "Дейла: ", "action": "  ✓ ", "denied": "  ✗ Не разрешено: ", "error": "  ⚠ ", "hint": ""}[kind]
        self.log.config(state="normal")
        self.log.insert("end", prefix + text + "\n\n" if kind in {"user", "agent", "hint"} else prefix + text + "\n", kind)
        self.log.config(state="disabled")
        self.log.see("end")

    def _log_from_worker(self, kind: str, text: str) -> None:
        self.on_main(lambda: self._write(kind, text.split("\n\n")[0]))

    def _send(self) -> None:
        typed = self.entry.get("1.0", "end").strip()
        if (not typed and not self.attachments) or self.busy:
            return
        self.entry.delete("1.0", "end")
        files = self.attachments
        self._clear_attachments()
        shown = typed + ("\n" if typed and files else "") + "\n".join(f"📎 {path}" for path in files)
        self._write("user", shown)
        # The agent reads the attached files by these full paths (actions.attach allowed them)
        text = typed or "Посмотри приложенные файлы"
        self.busy = True
        self.send_button.state(["disabled"])
        self.stop_button.state(["!disabled"])

        def done(answer, error):
            self.busy = False
            self.send_button.state(["!disabled"])
            self.stop_button.state(["disabled"])
            if isinstance(error, ApiError) and error.status == 401:
                self._login("Сессия истекла, войдите снова")
                return
            self._write("error" if error else "agent", getattr(error, "detail", str(error)) if error else answer)

        self._in_background(lambda: self.agent.run(text, attachments=files), done)

    def _new(self) -> None:
        if self.busy:
            return
        self.agent.forget()
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        self._write("hint", EXAMPLES)

    def _help(self) -> None:
        from .webapp import ABILITIES
        folders = ", ".join(self.actions.roots)
        messagebox.showinfo(
            "Что умеет Дейла на компьютере",
            "\n".join("• " + line.format(folders=folders) for line in ABILITIES)
            + "\n\nДо 32 действий на задачу. Пароли и коды входа вводите самостоятельно. "
            "Управление интерфейсом может изменить данные программы или сайта; проверяйте подтверждения.",
            parent=self.root,
        )

    def _logout(self) -> None:
        if self.busy:
            return
        self.agent.forget()
        self._in_background(self.api.logout, lambda *_: self._login())

    def _close(self) -> None:
        if getattr(self, "browser_login", None):
            self.browser_login.cancel()
        self.agent.stop.set()
        self.actions.close_automation()
        self.root.destroy()

    def run(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.mainloop()


def main() -> None:
    """The window like the site (webapp.py, Edge WebView2); this Tk window only when WebView2 cannot start."""
    import os

    from . import webapp

    if os.environ.get("DEYLA_CLASSIC") != "1" and webapp.available():
        try:
            webapp.run()
            return
        except Exception:
            import logging

            logging.exception("The web window could not start; the classic window opens instead")
    App().run()
