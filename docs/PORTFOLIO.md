# Roomies in a portfolio

Use the description after reviewing the parts you will discuss. The implementation was developed with coding assistance. Be clear about that assistance and describe the decisions you can explain.

## Factual description

**Roomies — student flat companion**

Python · SQLite · JavaScript · SVG · HTTP APIs · WebAssembly

An application that combines measured room planning, belongings with storage locations, kitchen stock lists, shared expenses, repayments, monthly bill templates and a product price journal. It validates saved inputs, calculates shared balances in integer cents, preserves dated price evidence and separates item-price changes from delivered-price target alerts.

A static browser build runs the same Python rules through Pyodide and persists each visitor's SQLite database in IndexedDB. It can be shared without installing Python or exposing a public write API. The local Python server remains available for compatible retailer checks.

Automated tests cover the implemented rules and failure cases. Browser checks exercise room editing, household records, kitchen updates, expense balances and backup flows. No actual users, savings or productivity improvement have been measured.

## A short interview demonstration

1. Add a kettle with its owner and exact storage spot, then find it through search.
2. Mark milk as Low and show how it appears on the shopping checklist.
3. Split a hypothetical €20.00 bill three ways. Explain the one-cent remainder, record a repayment and show that balances change while total spending stays the same.
4. Move a bed outside the sample room and explain the visible geometry error.
5. Show why a low product price with unknown shipping cannot pass a delivered-price target.

Use a disposable workspace and label hypothetical records. Explain the difference between a member label and a real account: this version has local bookkeeping, not synchronized roommate logins.

For another example, save an internet bill as a monthly template. Show that it creates no expense until reviewed, cannot be recorded twice in the same month, and does not rewrite an older bill when its usual amount changes.

## What to learn next

Trace one bill from the browser form through `server.py`, `household.py`, `expenses.py` and `storage.py`. Make one small change yourself, run the relevant test and record what you observed. That gives you a concrete contribution to discuss.
