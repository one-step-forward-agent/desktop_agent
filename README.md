# Deyla desktop agent (Windows)

`Deyla.exe` is a small window where the user writes a task ("открой калькулятор", "найди в загрузках pdf",
"создай на рабочем столе покупки.txt со списком", "напомни через 20 минут…") and Deyla does it on the computer.

It uses the same backend and the same model as the chat assistant: the app signs in through the browser (or with the site's email and password) and calls `POST /api/desktop/step` (`backend/app/api/desktop.py`). The backend asks the model selected by
`LLM_PROVIDER` (for `openai`: `BASE_URL` + `OPENAI_AGENT_MODEL`, actions sent as OpenAI tools) and returns one
action; the app runs it locally and sends the result back. No model key is ever on the user's computer.

## Working on websites and in Windows apps

Version 0.2.1 fixes attachment workflows: explicitly selected files may be read and opened outside the standard user roots; unselected files remain restricted. Text-based PDFs can be read without opening a viewer. Up to three selected files are previewed before the first model call, with a bounded context budget; “вариант 2”/“variant 2” requests select a matching passage when present. `read_text_file` supports character offsets for subsequent chunks. PDF extraction is isolated in a subprocess with a 35-second timeout, 20 MB file limit, 100-page and 200,000-character extraction limits. Scans require OCR; password-protected PDFs produce a specific error.

Legacy `.doc` reading and `convert_document` require installed Microsoft Word on Windows. Conversion creates a real new `.docx` inside the allowed folders, never renames the extension or replaces the original. Word runs in a separate instance with macros and automatic link updating disabled; existing Word processes are not used. The COM adapter has mocked coverage; actual Word compatibility must be verified on a machine with Office installed.

The chat now checks the backend's action catalog and shows a persistent limited-mode indicator when computer-control tools are unavailable. Updating the executable alone does not update the backend. Attachment previews and PDF reading work with the existing step contract, even if the older server's tool descriptions do not mention PDF. The new DOC conversion tool and browser/Windows planning require the matching backend update.

`read_web_page` now asks permission and can fall back to the managed browser if the plain HTTP request fails or returns a bot/JavaScript challenge. Browser observations include link destinations and rendered page text. If a CAPTCHA remains, the user must complete it; this is not a CAPTCHA bypass and does not guarantee access to protected search engines.

Version 0.2 adds an isolated, visible Microsoft Edge session controlled with Playwright. Deyla can inspect page text and controls, fill fields, select options, click buttons, use navigation keys, scroll, switch tabs, upload an explicitly attached file and download a new file. It uses element IDs from the latest observation, not guessed screen coordinates. Observations are refreshed after interactions; the assistant must check the result before reporting completion.

Examples: “Открой сайт и найди нужный товар”, “Заполни форму этими данными, перед отправкой покажи мне”, or “Открой Word и посмотри доступные элементы окна”. Websites may require you to sign in manually in this separate browser and send a follow-up request to continue. Passwords, verification codes and CAPTCHA remain manual. Browser cookies are temporary and are not copied from your everyday browser or persisted by Deyla.

Windows UI Automation supports accessible controls in Notepad, Calculator, Paint, Word, Excel and PowerPoint: discover windows, inspect controls, invoke buttons, select items, replace Edit-field text, insert literal Unicode at the caret in Edit/Document controls, read text and send a small list of navigation keys. Literal text is escaped so braces and symbols cannot become keyboard shortcuts. Office must already be installed. Custom-drawn interfaces and rich document editors that do not expose the necessary UIA patterns are not universally supported; no screenshot-based control is implemented. Terminals, scripts, arbitrary hotkeys and arbitrary program launches are not exposed.

Every browser/Windows automation action requires local confirmation, including observations that may send private page/window text to the backend model. The prompt includes the observed target and arguments. GUI actions can submit forms or change application data, so the filesystem actions' no-overwrite guarantee does not apply to edits made inside another application. If an automation action fails, the task stops rather than retrying a potentially completed submission. Stop prevents subsequent actions; an interaction already in progress may finish before it stops.

The browser checks public HTTP(S) destinations and blocks private addresses, nonstandard ports, service workers and WebSockets. These application checks are not an operating-system network sandbox; use network isolation if stronger destination guarantees are required. Downloads must use `browser_download`, create a new allowed file inside the normal user folders and pass the 25 MB completed-file check. Uploads accept explicitly attached files only, up to 20 MB. Unexpected downloads and JavaScript dialogs are dismissed. Sites requiring service workers, WebSockets, nonstandard ports or native dialogs may not work in this session.

## Reducing model calls

Upgraded clients advertise supported actions. The updated backend handles exact single commands such as “открой калькулятор”, “open notepad”, “launch Word”, “покажи папку загрузки” and “system info”, and their completion, without an LLM request. Compound or ambiguous instructions still go to the existing planner. A successful launch request is reported as a launch request, not proof that work inside the program is complete.

Optional semantic retrieval uses an independent embeddings service configured **on the backend**:

```dotenv
EMBEDDING_BASE_URL=https://your-embedding-service.example/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=your-multilingual-model
DESKTOP_SEMANTIC_TOOLS=true
```

The service must support float-vector `POST /embeddings` responses with indexed `data` entries. Use a model evaluated for both Russian and English. The backend caches embeddings of the static action catalog, embeds the request and selects relevant complete tool families, retaining previously used tools and file operations. It does not persist personal embeddings or reuse another user's answers. Errors or low similarity retain the full catalog; retrieval is off by default until a real model is configured and evaluated. This reduces tool prompt size, not the need for planning unfamiliar tasks. Embedding usage is recorded separately as purpose `embedding`; no reduction percentage has been measured against production traffic.

Both the backend and desktop client must be updated for automation. Old clients retain their existing tools and 12-action limit; new clients allow 32 actions. No website or bot API change is needed.

## The window

It looks like the site: `deyla_desktop/web/index.html` uses the site's tokens (`frontend src/app/app.css`) — the
background glows, glass cards, the blue → violet gradient, the chat bubbles and light/dark from the Windows setting —
and is shown by Edge WebView2 through pywebview (`webapp.py`). Paste, drag-and-drop of files and the right-click menu
work as in a browser. Without WebView2 (or with `DEYLA_CLASSIC=1`) the plain Tk window (`app.py`) opens instead.

## Limits

| Where | Limit |
| --- | --- |
| Server | Only actions in `ACTIONS` and supported by the client; invalid action arguments are rejected |
| Server | At most 32 actions per upgraded-client task, 12 for legacy clients |
| Server | 60 steps/minute, 300 steps/hour per user; model calls also use the shared token budget (`LLM_USER_TOKENS_PER_HOUR/DAY`) and purpose `desktop` |
| Server | `DESKTOP_AGENT=false` turns the agent off (503) |
| App | Files only inside Desktop, Documents, Downloads, Pictures, Music, Videos (real locations, OneDrive included); no hidden folders, no AppData |
| App | Filesystem writes: no deleting or overwriting, text files only (.txt .md .csv), up to 5000 characters; GUI edits have their own confirmation |
| App | No commands or scripts; programs only from a fixed list; `.exe/.bat/.ps1/.lnk/…` are never opened |
| App | Writing, creating folders, moving files and reading the clipboard always ask the user first |
| App | Web pages (`read_web_page`) only from public internet addresses, never this computer or the local network, also after redirects; currency rates from cbr.ru |
| App | Explicitly attached files can be read or opened wherever they are; file writes and moves still use allowed roots |
| App | Excel tables (`write_spreadsheet`, a real .xlsx without extra packages) are new files only and need «Разрешить» |
| App | A "Стоп" button; at most 40 step requests and a 15-minute deadline checked between requests/actions |

## Build

```powershell
cd desktop_agent
.\build.ps1          # installs PyInstaller, runs the tests, builds dist\Deyla.exe
```

Run from source: `python run.py`. Tests: `python -m pytest`.

`build.ps1` prefers `.venv/Scripts/python.exe` if present; `-SkipInstall` uses already-installed dependencies. Microsoft Edge must be installed for browser control in Windows. A bundled Chromium browser is not included in the executable. Linux development tests need `python -m playwright install chromium`.

Real automation tests are opt-in and use synthetic local fixtures only:

```powershell
$env:DEYLA_TEST_BROWSER='1'
$env:DEYLA_TEST_WINDOWS='1'
python -m pytest -q
```

The browser test explicitly permits its own loopback fixture through an injected test validator; production validation does not allow loopback. The Windows test starts and closes an owned synthetic WinForms process and does not operate personal applications. These checks establish the automation primitives, not compatibility with every website, Office version or a live model's planning quality.

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
