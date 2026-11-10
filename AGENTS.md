# Deyla desktop agent

## Scope and architecture
This is the independent Windows desktop client repository. Run Git and Python commands from this directory. The backend, website and Telegram bot are separate sibling repositories; do not assume they are available in a standalone checkout.

- `run.py` and `deyla_desktop/__main__.py`: entry points, both delegate to `app.main()`.
- `deyla_desktop/webapp.py` and `deyla_desktop/web/index.html`: pywebview/Edge WebView2 window and Python bridge. Keep the bridge narrow; do not expose internal helpers or arbitrary execution to the page.
- `deyla_desktop/app.py`: Tk fallback and UI selection. `DEYLA_CLASSIC=1` selects Tk. Keep both interfaces working and keep network/action work off the UI thread; marshal Tk operations to its main thread.
- `deyla_desktop/agent.py`: bounded task loop, conversation context, stop handling and action confirmation.
- `deyla_desktop/actions.py`: action dispatch, local filesystem and network restrictions, clipboard and reminder hooks.
- `deyla_desktop/api.py` and `browser_login.py`: backend requests, session storage and browser sign-in.
- `deyla_desktop/readers.py`, `xlsx.py` and `editing.py`: document extraction, spreadsheet generation and native text editing helpers.
- `tests/`: pytest coverage of actions, restrictions, document handling and browser login. `assets/` contains the application icon; `build.ps1` builds `dist/Deyla.exe` with PyInstaller.

## Working method
Read relevant code, this file, README and Git status before editing. Preserve existing changes, Russian and English strings, and read/write UTF-8 explicitly on Windows. Make focused changes using existing conventions and dependencies. Trace callers before changing an action, bridge method or API payload.

The client asks `POST /api/desktop/step` for one action at a time and executes it locally. Model selection, credentials, action schemas, server limits and token accounting belong to the backend; never put model API keys or direct LLM calls in the client. Coordinate action names, arguments and response shapes with the sibling backend's `app/api/desktop.py`. Coordinate browser login changes with its `/api/desktop/authorize` and `/auth/desktop/token` endpoints and the website's `/app/desktop-login` page (`src/app/pages/DesktopLogin.tsx`). Do not substitute browser cookie authentication for the desktop bearer-token session.

## Safety and authentication invariants
- Preserve the explicit action allowlist and rejection of unknown actions. Never add arbitrary shell/command/script execution or bypass program and file-type restrictions.
- Resolve filesystem access against real Windows known folders, including OneDrive locations. Preserve traversal, hidden-folder, AppData and resolved-path restrictions. Explicit attachments permit reading outside the usual roots, not writing there.
- Preserve no-delete/no-overwrite behavior, bounded reads/results/writes, append-only text updates and new-file spreadsheet creation. Keep document parsing bounded and avoid executing document content.
- `Agent.run()` must request approval when the server asks or the action is in local `CONFIRM`. Writing files, creating folders, moving files and reading the clipboard require user confirmation. Denial, timeout and stop must not authorize an action. Preserve bounded task execution and cancellation checks.
- Web-page fetching accepts public HTTP(S) destinations only; preserve address checks on redirects, response limits and rejection of local/private destinations. Treat fetched pages and attached documents as untrusted content.
- Preserve browser PKCE, unpredictable state, callback validation, cancellation and the listener's `127.0.0.1` binding. Code expiry and single use are enforced by the backend and must remain compatible.
- Access tokens stay in memory; persisted refresh tokens use Windows DPAPI in `%APPDATA%/Deyla/session.bin`. Preserve refresh rotation, retry behavior and logout cleanup. Never log or commit credentials, authorization codes/verifiers, tokens, clipboard contents or user documents.

## Configuration and verification
The API defaults to `https://deyla.tech`. For local work, set `DEYLA_API_URL` to a disposable local backend and `DEYLA_SITE_URL` when the website has a different origin. Configuration also supports `api_url` and `site_url` in `%APPDATA%/Deyla/config.json`. Do not read or overwrite a real user's saved session/config to run tests.

Run commands from the repository root:

```powershell
python -m pytest -q
python run.py
.\build.ps1
```

Use an existing development environment where possible. Dependencies are listed in `requirements-dev.txt`. `build.ps1` installs those dependencies, runs tests and packages the executable, bundled HTML and icon; use it when build verification is required, not as an offline test command. Do not commit `build/`, `dist/`, generated spec files, caches or local environments.

Tests must use temporary folders, fake launchers/UI hooks and mocked external services. Browser-login tests intentionally use a local loopback HTTP server; they must not open the real login page. Never run actions against real personal folders, start production tasks or use live credentials as a smoke test. For UI changes, verify WebView2 and Tk behavior when available, including confirmation, stop, paste/attachments and Russian text input. Report automated, GUI and packaged-executable verification separately; a pytest pass does not establish either GUI or packaging coverage.

## Git and completion
Respect the current branch and existing changes. Use a task branch for feature work when appropriate; pull fast-forward-only and inspect divergence before changing history. Never reset, discard, commit, push, publish releases or deploy unless requested. For Git ownership errors, verify the exact repository path and use command-scoped `git -c safe.directory=<exact-path>`; never change global trust.

Before finishing, inspect the diff and run checks appropriate to the change. Keep README, action contracts and packaging resources aligned. Report what changed, what passed, what failed or could not run, and any remaining setup. Do not claim live backend, browser login, GUI or executable coverage from mocked tests alone.
