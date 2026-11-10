"""Deyla backend client: sign-in with the site's email and password, the desktop agent's steps.

The refresh token is kept in %APPDATA%\\Deyla\\session.bin, encrypted with Windows DPAPI for this Windows user,
so another account on the computer cannot read it. The access token lives in memory only.
"""

import ctypes
import json
import os
import urllib.error
import urllib.request
from ctypes import wintypes
from pathlib import Path

from . import __version__

DEFAULT_API_URL = "https://deyla.tech"
TIMEOUT = 90


def app_dir() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    folder = base / "Deyla"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _config() -> dict:
    config = app_dir() / "config.json"
    if config.exists():
        try:
            value = json.loads(config.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            pass
    return {}


def site_url(api: str) -> str:
    """Where the browser signs in: DEYLA_SITE_URL, else "site_url" in config.json, else the API's own address
    (in production the site and the API are one host)."""
    return (os.environ.get("DEYLA_SITE_URL") or _config().get("site_url") or api).rstrip("/")


def api_url() -> str:
    """DEYLA_API_URL, else "api_url" in %APPDATA%\\Deyla\\config.json, else the production site."""
    if os.environ.get("DEYLA_API_URL"):
        return os.environ["DEYLA_API_URL"].rstrip("/")
    config = app_dir() / "config.json"
    if config.exists():
        try:
            value = json.loads(config.read_text(encoding="utf-8")).get("api_url")
            if value:
                return str(value).rstrip("/")
        except (OSError, ValueError):
            pass
    return DEFAULT_API_URL


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


# ---------- DPAPI ----------

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        return data
    source = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    result = _Blob()
    call = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not call(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(result)):  # CRYPTPROTECT_UI_FORBIDDEN
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


class SessionStore:
    def __init__(self, path: Path | None = None):
        self.path = path or app_dir() / "session.bin"

    def load(self) -> str | None:
        try:
            return _dpapi(self.path.read_bytes(), protect=False).decode()
        except (OSError, UnicodeDecodeError):
            return None

    def save(self, refresh_token: str) -> None:
        self.path.write_bytes(_dpapi(refresh_token.encode(), protect=True))

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


# ---------- HTTP ----------

class DeylaApi:
    def __init__(self, base_url: str | None = None, store: SessionStore | None = None, language: str = "ru"):
        self.base_url = (base_url or api_url()).rstrip("/")
        self.store = store or SessionStore()
        self.language = language
        self.access_token: str | None = None
        self._capabilities: dict | None = None

    def capability_status(self) -> dict:
        if self._capabilities is None:
            try:
                body = self._authed("GET", "/api/desktop/actions")
                names = {item.get("name") for item in body.get("actions", []) if isinstance(item, dict)}
                missing = not {"browser_open", "browser_fill", "windows_observe"} <= names
                self._capabilities = {"automation": not missing, "warning": (
                    "Ограниченный режим сервера: управление сайтами и программами недоступно. Требуется обновить backend; обновления exe недостаточно. Чтение приложенных PDF работает локально."
                    if missing else ""), "server": self.base_url}
            except ApiError:
                return {"automation": False, "warning": "Не удалось проверить инструменты сервера. Проверьте подключение и вход.", "server": self.base_url}
        return self._capabilities

    def _request(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Content-Type": "application/json", "Accept-Language": self.language, "User-Agent": f"DeylaDesktop/{__version__}"}
        if auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read()).get("detail")
            except ValueError:
                detail = None
            if isinstance(detail, list):  # FastAPI validation errors
                detail = "Сервер не принял запрос"
            raise ApiError(error.code, str(detail or f"Ошибка сервера ({error.code})")) from None
        except urllib.error.URLError as error:
            raise ApiError(0, f"Нет связи с {self.base_url}: {error.reason}") from None

    def _keep(self, tokens: dict) -> None:
        self.access_token = tokens["access_token"]
        self.store.save(tokens["refresh_token"])

    def login(self, email: str, password: str) -> None:
        self._keep(self._request("POST", "/auth/login", {"email": email.strip().lower(), "password": password}, auth=False))

    def login_with_code(self, code: str, verifier: str) -> None:
        """The browser sign-in's one-time code (browser_login.py) exchanged for this app's own session."""
        self._keep(self._request("POST", "/auth/desktop/token", {"code": code, "verifier": verifier}, auth=False))

    def resume(self) -> bool:
        """Sign in with the saved refresh token; False when there is none or it expired."""
        token = self.store.load()
        if not token:
            return False
        try:
            self._keep(self._request("POST", "/auth/refresh", {"refresh_token": token}, auth=False))
            return True
        except ApiError as error:
            if error.status in (400, 401, 422):
                self.store.clear()
            if error.status == 0:
                raise
            return False

    def logout(self) -> None:
        self._capabilities = None
        token = self.store.load()
        try:
            if token:
                self._request("POST", "/auth/logout", {"refresh_token": token}, auth=False)
        except ApiError:
            pass
        self.store.clear()
        self.access_token = None

    def _authed(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            return self._request(method, path, body)
        except ApiError as error:
            if error.status != 401 or not self.resume():
                raise
            return self._request(method, path, body)

    def me(self) -> dict:
        return self._authed("GET", "/api/me")

    def step(self, messages: list[dict], os_name: str, local_time: str) -> dict:
        from .actions import Actions, AUTOMATION_ACTIONS
        import importlib.util
        supported = {name[3:] for name in dir(Actions) if name.startswith("do_")}
        if importlib.util.find_spec("docx") is None:
            supported.discard("write_document")
        if importlib.util.find_spec("playwright") is not None:
            supported.update(name for name in AUTOMATION_ACTIONS if name.startswith("browser_"))
        if os.name == "nt" and importlib.util.find_spec("pywinauto") is not None and importlib.util.find_spec("psutil") is not None:
            supported.update(name for name in AUTOMATION_ACTIONS if name.startswith("windows_"))
        return self._authed("POST", "/api/desktop/step", {"messages": messages, "client_version": __version__, "os": os_name,
            "local_time": local_time, "client_actions": sorted(supported)})
