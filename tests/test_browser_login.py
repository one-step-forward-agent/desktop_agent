"""Signing in through the browser: the callback on 127.0.0.1 hands over the code only with the right state."""

import base64
import hashlib
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest

from deyla_desktop.browser_login import BrowserLogin, LoginCancelled


def test_the_browser_brings_back_the_code():
    opened = []
    login = BrowserLogin("https://deyla.tech/", open_browser=opened.append)
    address = login.start()
    assert opened == [address]
    parts = urlsplit(address)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "deyla.tech", "/app/desktop-login")
    query = parse_qs(parts.query)
    assert query["challenge"][0] == base64.urlsafe_b64encode(hashlib.sha256(login.verifier.encode()).digest()).rstrip(b"=").decode()
    port, state = query["port"][0], query["state"][0]
    assert len(address) - len("https://deyla.tech") < 300  # the site's limit for a return path after Google sign-in

    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=stolen&state=wrong", timeout=5)
    page = urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=the-code&state={state}", timeout=5).read().decode()
    assert "Готово" in page
    assert login.wait(timeout=5) == ("the-code", login.verifier)


def test_closing_the_app_or_waiting_too_long_cancels():
    login = BrowserLogin("https://deyla.tech", open_browser=lambda _: None)
    login.start()
    login.cancel()
    with pytest.raises(LoginCancelled):
        login.wait(timeout=5)
    slow = BrowserLogin("https://deyla.tech", open_browser=lambda _: None)
    slow.start()
    with pytest.raises(LoginCancelled):
        slow.wait(timeout=0.2)
