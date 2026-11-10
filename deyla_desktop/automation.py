"""Thread-confined automation. Neither the model nor a web page supplies executable code."""
import queue
import threading
from concurrent.futures import Future


class AutomationError(Exception):
    pass


class Automation:
    """Playwright and UIA objects stay on one dedicated thread across chat requests."""

    def __init__(self):
        self._queue = queue.Queue()
        self._thread = None
        self._lock = threading.Lock()
        self._closed = False

    def run(self, name: str, arguments: dict):
        with self._lock:
            if self._closed:
                raise AutomationError("Сеанс управления закрыт")
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, daemon=True, name="deyla-automation")
                self._thread.start()
            result = Future()
            self._queue.put((name, arguments, result))
        # Do not time out and leave an action executing invisibly on the worker.
        return result.result()

    def _work(self):
        browser = windows = None
        while True:
            item = self._queue.get()
            if item is None:
                break
            name, arguments, result = item
            try:
                if name.startswith("browser_"):
                    if browser is None:
                        from .browser import Browser
                        browser = Browser()
                    value = browser.run(name.removeprefix("browser_"), arguments)
                elif name.startswith("windows_"):
                    if windows is None:
                        from .windows import Windows
                        windows = Windows()
                    value = windows.run(name.removeprefix("windows_"), arguments)
                else:
                    raise AutomationError("Неизвестное действие управления")
                result.set_result(value)
            except AutomationError as error:
                result.set_exception(error)
            except Exception:
                # Framework errors can contain field contents, URLs, or page source.
                result.set_exception(AutomationError("Не удалось выполнить действие. Обновите состояние окна и повторите; действие могло выполниться частично."))
        try:
            if browser is not None:
                browser.close()
        finally:
            if windows is not None:
                windows.close()

    def close(self):
        with self._lock:
            self._closed = True
            if self._thread:
                self._queue.put(None)
