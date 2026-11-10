# Deyla desktop agent (Windows)

`Deyla.exe` is a small window where the user writes a task ("открой калькулятор", "найди в загрузках pdf",
"создай на рабочем столе покупки.txt со списком", "напомни через 20 минут…") and Deyla does it on the computer.

It uses the same backend and the same model as the chat assistant: the app signs in through the browser (or with the site's email and password) and calls `POST /api/desktop/step` (`backend/app/api/desktop.py`). The backend asks the model selected by
`LLM_PROVIDER` (for `openai`: `BASE_URL` + `OPENAI_AGENT_MODEL`, actions sent as OpenAI tools) and returns one
action; the app runs it locally and sends the result back. No model key is ever on the user's computer.

## The window

It looks like the site: `deyla_desktop/web/index.html` uses the site's tokens (`frontend src/app/app.css`) — the
background glows, glass cards, the blue → violet gradient, the chat bubbles and light/dark from the Windows setting —
and is shown by Edge WebView2 through pywebview (`webapp.py`). Paste, drag-and-drop of files and the right-click menu
work as in a browser. Without WebView2 (or with `DEYLA_CLASSIC=1`) the plain Tk window (`app.py`) opens instead.

## Limits

| Where | Limit |
| --- | --- |
| Server | Only the 16 actions in `ACTIONS`; unknown actions from the client history or from the model are rejected |
| Server | At most 12 actions per task, then the model must answer with words |
| Server | 20 steps/minute, 300 steps/hour per user, plus the shared token budget (`LLM_USER_TOKENS_PER_HOUR/DAY`); tokens are recorded as purpose `desktop` |
| Server | `DESKTOP_AGENT=false` turns the agent off (503) |
| App | Files only inside Desktop, Documents, Downloads, Pictures, Music, Videos (real locations, OneDrive included); no hidden folders, no AppData |
| App | No deleting, no overwriting (new files or append only), text files only (.txt .md .csv), up to 5000 characters |
| App | No commands or scripts; programs only from a fixed list; `.exe/.bat/.ps1/.lnk/…` are never opened |
| App | Writing, creating folders, moving files and reading the clipboard always ask the user first |
| App | Web pages (`read_web_page`) only from public internet addresses, never this computer or the local network, also after redirects; currency rates from cbr.ru |
| App | Files attached with 📎 or pasted from Explorer can be read wherever they are — read only |
| App | Excel tables (`write_spreadsheet`, a real .xlsx without extra packages) are new files only and need «Разрешить» |
| App | A "Стоп" button; at most 16 requests per task |

## Build

```powershell
cd desktop_agent
.\build.ps1          # installs PyInstaller, runs the tests, builds dist\Deyla.exe
```

Run from source: `python run.py`. Tests: `python -m pytest`.

The server address defaults to `https://deyla.tech`; for a local backend set `DEYLA_API_URL=http://127.0.0.1:8000`
or `{"api_url": "..."}` in `%APPDATA%\Deyla\config.json`. The refresh token is stored in `%APPDATA%\Deyla\session.bin`,
encrypted with Windows DPAPI.

## Signing in

«Войти через браузер» works for every account, Google and Yandex ones too: the app listens on `127.0.0.1`, opens
`<site>/app/desktop-login`, the user presses «Разрешить» there (signing in on the site first if needed), and the site
sends the browser back to the app with a one-time code (2 minutes, single use) that only works with the app's own
PKCE verifier (`/auth/desktop/token`). Email and password sign-in is still there below it. For a local setup where the
site is not on the API's host, set `DEYLA_SITE_URL` (or `"site_url"` in `config.json`), e.g. `http://localhost:5173`.
The exe is not code-signed, so Windows SmartScreen will warn on first launch until it is signed.
