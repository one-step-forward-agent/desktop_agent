"""One task of the desktop agent: ask the server for the next step, run the action here, send back the result.

The server stops offering actions after its per-task limit; the app also stops after MAX_STEPS requests
and when the user presses "Stop".
"""

import platform
import threading
import time
from datetime import datetime
from typing import Callable

from .actions import CONFIRM, AUTOMATION_ACTIONS, ActionError, Actions, result_text
from .api import DeylaApi

MAX_STEPS = 40
MAX_TASK_SECONDS = 15 * 60
# Earlier tasks the model sees as context (their questions and answers only)
KEEP_EXCHANGES = 3
# The server takes up to 12000 characters a message
MAX_CONTENT = 24000


class Agent:
    def __init__(self, api: DeylaApi, actions: Actions, confirm: Callable[[str], bool], log: Callable[[str, str], None]):
        """confirm(text) asks the user and returns True to allow; log(kind, text) shows a line in the window."""
        self.api = api
        self.actions = actions
        self.confirm = confirm
        self.log = log
        self.earlier: list[dict] = []
        self.stop = threading.Event()
        self._running = threading.Lock()

    def run(self, task: str, attachments: list[str] | None = None) -> str:
        if not self._running.acquire(blocking=False):
            raise ActionError("Задача уже выполняется. Сначала остановите её или дождитесь результата.")
        try:
            return self._run(task, attachments)
        finally:
            self._running.release()

    def _run(self, task: str, attachments: list[str] | None = None) -> str:
        self.stop.clear()
        started = time.monotonic()
        if attachments:
            task = self.actions.prepare_task(task, attachments)
        messages = [{"role": "user", "content": task[:MAX_CONTENT]}]
        answer = ""
        for _ in range(MAX_STEPS):
            if self.stop.is_set() or time.monotonic() - started > MAX_TASK_SECONDS:
                answer = "Остановлено."
                break
            reply = self.api.step(self.earlier + messages, platform.platform(), datetime.now().astimezone().isoformat(timespec="minutes"))
            if self.stop.is_set():
                answer = "Остановлено."
                break
            action = reply.get("action")
            if not action:
                answer = reply.get("content") or ""
                break
            name, arguments = action["name"], action.get("arguments") or {}
            description = self.actions.describe(name, arguments)
            messages.append({"role": "assistant", "content": (reply.get("content") or "")[:MAX_CONTENT], "function_call": {"name": name, "arguments": arguments}})
            if self.stop.is_set():
                result = {"ok": False, "error": "Пользователь остановил задачу"}
            elif (reply.get("confirm") or name in CONFIRM) and not self.confirm(description):
                result = {"ok": False, "error": "Пользователь не разрешил это действие"}
                self.log("denied", description)
            else:
                # Stop may have been pressed while the confirmation dialog was open.
                if self.stop.is_set() or time.monotonic() - started > MAX_TASK_SECONDS:
                    answer = "Остановлено."
                    break
                try:
                    result = self.actions.run(name, arguments)
                    self.log("action", description)
                except ActionError as error:
                    result = {"ok": False, "error": str(error)}
                    label = description.split("\n\n", 1)[0]
                    self.log("error", f"{label}: {error}")
            messages.append({"role": "function", "content": result_text(result)})
            if name in AUTOMATION_ACTIONS and not result.get("ok"):
                # A timed-out click may have submitted a form. Never blindly replay it.
                answer = "Остановлено: " + str(result.get("error", "Действие не выполнено"))
                break
        else:
            answer = "Задача заняла слишком много шагов — я остановилась. Попробуйте разбить её на части."
        answer = answer.strip() or "Готово."
        if not self.stop.is_set():
            self.earlier = (self.earlier + [{"role": "user", "content": task[:MAX_CONTENT]}, {"role": "assistant", "content": answer[:MAX_CONTENT]}])[-2 * KEEP_EXCHANGES:]
        return answer

    def forget(self) -> None:
        self.stop.set()
        self.earlier = []
        self.actions.attached.clear()
        self.actions.close_automation()
