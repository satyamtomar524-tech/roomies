# Verification record

Checked on 30 September 2026 for Roomies 2.0. This records local evidence. Remote results are available in the repository's [workflow run history](https://github.com/satyamtomar524-tech/roomies/actions).

## Results

| Check | Result |
|---|---|
| Python behavioral suite | **161 passed** on Python 3.12.14 / Windows |
| JavaScript syntax | Passed with Node 24.19.0 |
| Complete browser workflow | Passed using Playwright 1.62.1 and isolated headless Chrome 154.0.8037.58 |
| Responsive pages | No horizontal overflow in all seven views at 320 px and 390 px; shared-cost dialog controls remain reachable |
| Browser runtime | No uncaught page errors in the tested workflow |
| Visual inspection | Desktop and mobile home, room and kitchen screenshots, plus the narrow expense dialog, inspected |
| Python distribution | Version 2.0 wheel built and installed into a fresh virtual environment; all six web assets, installed HTTP server and Roomies CLI verified outside the source checkout |

The Python suite covers geometry, prices, HTTP/API routes, SQLite persistence, scheduling, household validation and shared expenses. The browser check uses a fresh disposable database, synthetic belongings, people, bills, products and prices, and a stopped scheduler. It does not contact a retailer or modify the user's workspace.

The browser workflow checks dragging, keyboard movement and rotation, numeric room edits, invalid geometry and recovery, suggested positions, wall/floor colours, product edits and SKU preservation, watch controls, manual quotes, fit and delivery eligibility, distinct alerts, notification read state, price history, SVG/CSV/JSON exports, backup import, the guide, and narrow layouts.

It also creates flat members, adds and edits a belonging's location, searches inventory, blocks deletion of a referenced member, updates the kitchen checklist, creates/edits/removes shared costs, verifies exact balances, exports per-person shares and restores the full flat. A held background response verifies that a newly saved change survives an older read. A held checklist write verifies that import waits before restoring the backup. A bill imported with a different participant order verifies that a title-only edit preserves its odd-cent allocation.

## Repeat the checks

From the repository directory:

```sh
python -m unittest discover -s tests -v
node --check web/app.js
node --check web/flat.js
```

Browser tooling is optional; the application itself needs only Python. On a machine with Node and npm:

```sh
npm install --ignore-scripts
npx playwright install chromium
npm run test:browser
```

On Linux, Playwright may need `npx playwright install --with-deps chromium`. `ROOMMATE_PYTHON` selects a Python executable. `ROOMMATE_BROWSER_PATH` can select an installed Chrome/Chromium executable instead of the downloaded browser. The test starts and stops its own localhost server and writes only under ignored `test-results/`.

GitHub Actions is configured for Python 3.10, 3.12 and 3.13, JavaScript syntax, and a Chromium browser workflow. Only Python 3.12 was executed locally; the other Python versions are covered by the remote workflow.

The browser job uses Chrome already installed on the Ubuntu 24.04 runner, selected through `ROOMMATE_BROWSER_PATH`. This runs the same smoke test without installing a second browser and its operating-system dependencies. The [runner's software inventory](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md) documents its available browser.

## Important regressions covered

- A planned desk reserves its footprint; a surface lamp does not consume additional floor area.
- Rotating a supporting item does not produce a suggested placement that strands its surface child.
- Surface height includes the parent, and invalid ceiling clearance is flagged.
- Areas use geometric unions, so overlap is not counted twice.
- Missing shipping cannot become free shipping.
- Product metadata edits do not refresh a quote. Identity changes invalidate previous variant evidence.
- Backdated observations do not replace a newer quote, clear a failed current check, postpone monitoring, or create a new price-drop notice.
- Demo rooms and example products cannot produce buying alerts.
- Live notices require a confirmed matching SKU and product link; manual quote confirmation is separate.
- Repeated quotes do not duplicate alerts; identical notification timestamps preserve insertion order.
- Malformed imports leave the previous workspace intact. Valid imports restore history without replaying alerts.
- Existing databases gain flat records without losing the room or price history. Older room-only imports and room resets preserve current flat records.
- Bills reject fractional cents, unknown members and duplicate participants. Shared balances sum to zero; suggested payments reconcile them exactly.
- Every cent is allocated in saved participant order, including tiny bills and amounts that do not divide evenly.
- Flat writes are serialized in the browser. Older polling responses cannot replace a newly accepted flat change.
- Failed public checks retain the old observation but cannot turn it into a current purchase signal.
- Local request checks, private-address rejection, redirect validation, crawling restrictions, response limits and ambiguous structured offers are exercised.

## Limits of this evidence

The live adapter was tested with controlled HTML and network fixtures. **No real retailer has been demonstrated as compatible in this build.** Site markup, crawling permission and offers can change. Validate a permitted exact product link before relying on its scheduled checks.

No actual room measurements, user study, real savings or professional architectural validation were collected. The plan is a two-dimensional rectangle model, and colour previews are schematic. There is no photorealistic 3D view, irregular-room editor, cloud worker, email delivery or market-wide search. Socket/body limits do not impose one overall deadline across DNS, robots and redirects.

Member names are local bookkeeping labels. Separate roommate accounts, multi-device synchronization, recurring bills and bank payments are not implemented. Suggested payments describe the outstanding ledger; they do not record an actual transfer. Kitchen dates are user-entered planning notes.

The live parser leaves delivery unknown. Its informational price-drop notice is not proof of a delivered-price bargain. Quote history represents observations, not every market price between them.

Source packaging and local checks passed. The [public repository](https://github.com/satyamtomar524-tech/roomies) contains the source and workflow; `GITHUB_SETUP.md` explains how to obtain and update it.
