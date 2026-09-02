---
description: Start the backend (connected to X-Plane) and the UI dev server
---

Start both dev servers, backend first (the frontend proxies `/api` and `/ws` to it), with the
backend pinned to the X-Plane adapter — the server's default is `fake`, so leaving
`OIS_ADAPTER` unset would silently place aircraft in an in-memory simulator:

1. Set `OIS_ADAPTER=xplane` for the launch (Bash: `OIS_ADAPTER=xplane ./.venv/Scripts/instructor-station.exe`;
   PowerShell: `$env:OIS_ADAPTER = "xplane"`) and run `instructor-station` (or
   `python -m server` if the console script isn't on PATH) from the repo root **in the
   background** (`run_in_background: true`), using the project's `.venv`. Then check
   `GET http://localhost:8000/api/health` and require `"adapter": "xplane"` and
   `"connected": true`. If `connected` is `false`, report that X-Plane is not running or its
   Web API (port 8086) is not enabled — do not silently continue.
2. Run `npm run dev` inside `ui/` **in the background**.
3. Read its output to find the local URL (normally `http://localhost:5173`) and report both URLs
   to the user.
4. If either process fails to start (e.g. port already in use, missing `node_modules`/`.venv`),
   diagnose and report — don't silently retry.

Do not stop either server afterwards; both should keep running so the user can use the app. Do
not open a browser or take screenshots unless the user separately asks to verify something
visually.
