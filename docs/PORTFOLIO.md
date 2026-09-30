# Putting RoomMate in a portfolio

Use the description after reviewing the parts you will discuss. The implementation was developed with coding assistance; do not present assistance as independent work or claim proficiency you have not yet practiced.

## Factual project description

**RoomMate — student room planner and upgrade tracker**

Python · SQLite · JavaScript · SVG · HTTP APIs

A local application that connects a measured room layout with future furniture reservations and a product price journal. It checks rectangular fit and placement conflicts, preserves dated price evidence, and separates delivered-price target alerts from item-price changes. Automated tests cover geometry, storage, API behavior and price rules; browser checks exercise the complete local workflow.

If a CV entry uses “developed” or “implemented,” be ready to explain the implementation and your use of coding assistance. State the repository's current verified test count only if useful; no user or savings metrics have been collected.

## A short interview walkthrough

1. Show the sample room and move the bed outside its boundary. Explain why the arrangement is saved with a visible error rather than silently corrected.
2. Select the future desk. Explain that a reservation includes width, depth and height; a lamp has local coordinates on that supporting surface.
3. Add a hypothetical product in a disposable test workspace. Explain why a low price with unknown shipping cannot pass the delivered-price target.
4. Show the observation table and SQL query in `ARCHITECTURE.md`. Explain why observations are separate from product metadata and how old evidence stays inspectable.
5. Run one geometry test and one price-rule test. Explain the expected behavior before showing the result.

Use clearly labeled test data during a demonstration. The project does not establish that a real retailer's product is available or that a user saved money.

## The next learning step

Trace one edit from `web/app.js` through `server.py`, `geometry.py` and `storage.py`. Then make one small change yourself and verify it with the existing checks. Keep a brief note of what you changed, the decision you made and the result you observed. That gives you concrete material to discuss without overstating your experience.
