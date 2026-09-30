# A link my friends can open

**Public website: [Open Roomies](https://roomies-satyam.satyamtomar524.chatgpt.site)**

The Python app originally needed a terminal running on my laptop. That was fine for development, but awkward for someone who only wanted to try the idea.

The browser build keeps the same interface and the same Python rules. Pyodide runs Python in a separate browser worker, so calculations do not block the page. The worker uses the existing SQLite storage and saves the database in IndexedDB after every accepted write. There is no public server holding everyone's flat records.

## What sharing means

- Each browser starts with the labelled sample room and an empty flat.
- Changes stay on that browser and device. Export a backup to move them or keep a separate copy.
- Sharing the link shares the app. It does not invite people into your records or sync their edits.
- Room planning, inventory, kitchen lists, costs, repayments, monthly bills and manual price observations work here.
- Automatic retailer requests need the local Python app. The public version hides those controls and explains manual price recording.
- The first visit downloads about 14 MB of app/runtime files before editing starts. Use a current browser with WebAssembly, workers, IndexedDB and Web Locks. Clearing site data clears the saved workspace.

## Build it

From the repository:

```sh
python scripts/build_browser.py
python -m http.server 8841 --bind 127.0.0.1 --directory dist
```

Open `http://127.0.0.1:8841/`. The build downloads a pinned Pyodide package, verifies its SHA-512, and copies only allowlisted code and assets into `dist`. No database, backup, token or environment file is copied. Its runtime archive is cached under `build/runtime-cache` for later builds. Both folders are ignored by Git.

The contents of `dist` can be hosted as static files over HTTPS. Assets use relative paths, so a project subdirectory works too. Serve `.wasm` as `application/wasm` and `.mjs` as JavaScript. Runtime files are served from the same origin; visitors do not need a CDN or an API key.

The Sites deployment has a separate generated checkout. Its `.openai/hosting.json` holds the Site identity and `static.directory: "dist"`. Rebuild the generated files from this repository before publishing an update. Keep the Site identity so saved browser records remain on the same origin.

## Follow one save

1. `web/app.js` calls the browser transport instead of the local HTTP API.
2. `web/browser.js` sends the action to `web/browser-worker.mjs`.
3. `roommate/browser.py` dispatches it to the existing validation and storage modules.
4. The worker persists the SQLite bytes in IndexedDB before reporting success.
5. If persistence fails, it restores the previous database in memory and reports the failure. It does not call the edit saved.

One editor tab is allowed per browser profile and origin. A second tab explains how to continue instead of overwriting a stale copy. Other visitors have independent storage. A read-only WebMCP overview is registered only in browsers that provide that optional API; the ordinary UI needs no AI integration.

## Check it

Install the optional development dependency with `npm install`, build `dist`, then run:

```sh
npm run test:public
```

The test serves only static files and blocks external page requests. It checks room edits, flat records, kitchen stock, exact-cent costs, repayments, monthly templates, manual prices, exports/imports, reload persistence, independent visitor storage, a second editor tab, a simulated storage failure and phone widths. It reuses the local app's repayment and monthly-bill workflow. The optional WebMCP registration is tested with a mock; actual agent integration is not verified.

## Dependencies

Pyodide 314.0.7 is distributed unmodified under MPL-2.0. Python 3.14.2 uses the PSF license; SQLite is public domain. License files are included in the build. Sources: [Pyodide](https://github.com/pyodide/pyodide/tree/314.0.7), [Python](https://github.com/python/cpython/tree/v3.14.2), [SQLite](https://sqlite.org/copyright.html). The integration follows the official [worker guide](https://pyodide.org/en/stable/usage/webworker.html) and [deployment guide](https://pyodide.org/en/stable/usage/downloading-and-deploying.html).
