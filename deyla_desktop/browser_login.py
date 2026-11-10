"""Sign in through the browser — the way for every account, Google and Yandex ones included (they have no password).

The app listens on 127.0.0.1 on a free port and opens <site>/app/desktop-login with a PKCE challenge and a state.
The user presses «Разрешить» on the site (signing in there first if needed, with Google or anything else); the site
sends the browser to http://127.0.0.1:<port>/callback?code=…&state=…; the app exchanges the code together with
its verifier (backend /auth/desktop/token). A code seen by anyone else is useless without the verifier.
"""

import base64
import hashlib
import http.server
import secrets
import threading
import webbrowser
from urllib.parse import parse_qs, urlencode, urlsplit

WAIT_SECONDS = 300
PAGE = """<!doctype html><meta charset="utf-8"><title>Deyla</title>
<body style="font-family:Segoe UI,sans-serif;text-align:center;padding-top:15vh">
<h2>{title}</h2><p>{text}</p></body>"""


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class LoginCancelled(Exception):
    pass


class BrowserLogin:
    """One attempt: start() opens the browser, wait() returns (code, verifier) or raises LoginCancelled."""

    def __init__(self, site_url: str, open_browser=webbrowser.open):
        self.site_url = site_url.rstrip("/")
        self.open_browser = open_browser
        self.verifier, self.challenge = pkce()
        self.state = secrets.token_urlsafe(16)
        self.code: str | None = None
        self.done = threading.Event()
        self.server: http.server.HTTPServer | None = None

    def _handler(self):
        login = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server's name
                parts = urlsplit(self.path)
                query = parse_qs(parts.query)
                ok = parts.path == "/callback" and query.get("state") == [login.state] and query.get("code")
                if ok:
                    login.code = query["code"][0]
                title, text = (
                    ("Готово", "Вернитесь в приложение Deyla — эту вкладку можно закрыть.") if ok else ("Ссылка не подошла", "Нажмите «Войти через браузер» в приложении ещё раз.")
                )
                body = PAGE.format(title=title, text=text).encode()
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                if ok:
                    login.done.set()

            def log_message(self, *args):
                pass

        return Handler

    def url(self, port: int) -> str:
        return f"{self.site_url}/app/desktop-login?" + urlencode({"port": port, "challenge": self.challenge, "state": self.state})

    def start(self) -> str:
        self.server = http.server.HTTPServer(("127.0.0.1", 0), self._handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        address = self.url(self.server.server_address[1])
        self.open_browser(address)
        return address

    def wait(self, timeout: float = WAIT_SECONDS) -> tuple[str, str]:
        try:
            if not self.done.wait(timeout) or not self.code:
                raise LoginCancelled("Время на вход вышло — попробуйте ещё раз")
            return self.code, self.verifier
        finally:
            self.close()

    def cancel(self) -> None:
        self.done.set()

    def close(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
