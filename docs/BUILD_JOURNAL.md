# Build journal

## 30 September 2026 — A website to share

I wanted friends to open the project without setting up Python. The browser version runs the existing rules with Pyodide and keeps each visitor's SQLite database in IndexedDB. This avoids maintaining two different geometry and expense engines. I kept manual price records in this version and left automatic retailer requests in the local app.

The public build starts with the sample, includes a Share Roomies button and makes the storage boundary clear. It checks persistence before calling an edit saved, and allows one editor tab so a stale tab cannot overwrite the database. Browser tests cover isolated visitors, reloads, backups and storage failure as well as the everyday workflows.

## 30 September 2026 — Finishing the everyday flow

I wanted the shared-cost page to finish the job: add a bill, see who owes what, then record the money paid back. Repayments now change the balance without counting as more spending.

Rent and regular bills can be saved as monthly templates. They need a reviewed entry after payment. A template creates no debt on its own, and the same bill cannot be recorded twice for one month.

I also shortened the main copy around the original idea: my room, my things, and our flat. The guide explains the full flow, including backups, mistakes and corrections. This release finishes the local app; cloud accounts and syncing are outside its scope.

## 30 September 2026 — Roomies

I expanded the room idea to include flat belongings, where things are kept, kitchen supplies and shared expenses. The interface starts with a simple home screen and one page per task.

### Decisions

- Keep flat records separate from the measured room. A small belonging does not need a floor footprint.
- Add owner and exact storage spot so the inventory answers where something is.
- Keep kitchen equipment in inventory and food stock in a separate list. Low and missing stock becomes a shopping checklist.
- Store shared amounts in integer cents and keep payer and participant IDs explicit.
- Keep the original Python module for compatibility while naming the app and repository Roomies.
- Preserve flat data when an old room-only backup is imported or the sample room is reset.
- Use local member labels. Synchronized accounts and invitations are not implemented.

### Next useful improvements

1. Add recurring bill templates for rent and utilities.
2. Let a shopping item become a shared expense with one reviewed action.
3. Add optional authenticated syncing if the project moves beyond one local workspace.

## 30 September 2026 — First complete local version

The original idea was a whole-house concept planner. It became more useful when narrowed to one student's room: owned furniture, future reservations, and buying decisions tied to those reservations.

### Decisions

- Use a labeled 3 × 3.5 m sample because actual wall and furniture measurements are not yet supplied.
- Keep the project local and single-user so it can run without an API key or cloud account.
- Use centimeters throughout the room model. Use EUR for this version's price journal.
- Draw furniture from measured rectangular footprints. Keep the measured view as the working view.
- Treat planned places as reservations, not empty space. Distinguish floor furniture, surface objects, overlays, and wall items.
- Keep the price history as dated records with their sources. Do not overwrite a past observation or infer missing shipping.
- Begin with manual observations and a public structured-data adapter. Unsupported retailer pages should fail visibly.
- Use in-app notifications. No automatic checkout or messages to other people.
- Keep runtime room data outside Git and use synthetic data only when clearly labeled.
- Write code in small modules with responsibilities you can point to. Avoid adding a framework where the standard library is sufficient.

### Next useful improvements

1. Map the actual room and check its measurements against the furniture.
2. Test a few real product pages from permitted sources and document support and failure cases.
3. Add a read-only SQL/Power BI report over collected price history once actual observations exist.

An irregular room outline, calibrated photo import, detailed 3D furniture, and cloud notification delivery are future extensions. They are not needed to demonstrate the first room-and-price workflow.

### Portfolio boundary

Describe the delivered behavior and your actual contributions. Keep coding assistance transparent. No measured savings, users, market coverage, or trained model is claimed. The test report is evidence of software checks, not a real-world impact evaluation.
