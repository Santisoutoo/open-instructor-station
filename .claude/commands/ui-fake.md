---
description: Start the backend (forced onto FakeSimAdapter, no X-Plane) and the UI dev server
---

Start both dev servers for frontend work, with the backend pinned to `FakeSimAdapter` so no
X-Plane connection is ever attempted — even if `OIS_ADAPTER` is already set to `xplane` in this
shell from a previous session:

1. Set `OIS_ADAPTER=fake` for the launch (PowerShell: `$env:OIS_ADAPTER = "fake"`) and run
   `instructor-station` (or `python -m server` if the console script isn't on PATH) from the
   repo root **in the background** (`run_in_background: true`), using the project's `.venv`.
   Read its output and confirm it is listening on `http://localhost:8000` (check `/api/health`
   if the log is ambiguous) and that it did not try to reach X-Plane.
2. Run `npm run dev` inside `ui/` **in the background**.
3. Read its output to find the local URL (normally `http://localhost:5173`) and report both URLs
   to the user.
4. If either process fails to start (e.g. port already in use, missing `node_modules`/`.venv`),
   diagnose and report — don't silently retry.

Do not stop either server afterwards; both should keep running so the user can use the app. Do
not open a browser or take screenshots unless the user separately asks to verify something
visually.
