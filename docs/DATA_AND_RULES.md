# Data and decisions

## Measurements

All room dimensions and coordinates are centimeters. The plan origin is north-west: X increases right, Y increases down. Floor footprints are axis-aligned rectangles. A 90° rotation exchanges width and depth.

Furniture measurements should include the complete frame, handles, and protruding parts. The code cannot correct an inaccurate measurement. The 3 × 3.5 m room is a sample, not the user's measured room.

## Placement types

| Type | Meaning | Floor-area accounting |
|---|---|---|
| Floor | Bed, desk, wardrobe, floor lamp | Owned and planned footprints occupy or reserve floor area |
| Surface | Lamp or bottle on a desk/cabinet | Local coordinates on a supporting floor item; no extra floor footprint |
| Overlay | Rug or mat beneath furniture | Can overlap floor furniture; does not reserve a second solid footprint |
| Wall | Wall decoration or similar item | Separate marker; not occupied floor area |

Surface support checks model dimensions, not load capacity or material strength. A curtain's required length and mounting details are not derived automatically. Window positions are visual/context records, not a daylight model.

## Area accounting

- Room area = width × depth ÷ 10,000.
- Owned floor area is the union of owned floor rectangles clipped to the room.
- Combined floor usage is the union of owned and planned floor rectangles.
- Reserved area = combined usage − owned usage.
- Remaining area = room area − combined usage.

Using a union means overlapping rectangles do not inflate the reported floor area. Remaining area is not a measure of usable walking space: door zones, obstacles, comfort, and access can reduce what is usable.

## Hard errors and preferences

Room-boundary, furniture overlap, surface support, ceiling height, fixed obstacles, and inward-door rectangle conflicts are modeled errors. Preferred furniture clearance is a user preference and can produce a warning.

An inward door uses a conservative rectangular zone. It is not a precise hinge/sweep simulation. Accessibility and escape-route compliance are not evaluated.

The position suggestion search checks modeled candidates and returns up to five options. It prioritizes fewer preference warnings and proximity to boundaries. Its numeric score is an internal ordering rule, not a quality probability, safety rating, or proof of global optimality.

## Product fit

A product is linked to a planned item. Width, depth, and height must be known. The entered dimensions must fit the reservation in the allowed modeled orientation. Relevant placement conflicts prevent a positive buying signal. A product linked to an owned item does not count as a new planned reservation.

Wall, floor and item colours appear in the plan; style is an explicit note. These are schematic colours, not a lighting or material simulation. The application does not infer that an item will improve someone's mood or objectively match a room. Verify the chosen variant and its dimensions against the actual product page.

## Price observations

Every quote has a timestamp with a timezone, an explicit EUR item price, stock state, source, and optional shipping. Timestamps are normalized to UTC and displayed in the browser's local time.

Unknown shipping stays NULL. Confirmed free shipping is zero. A delivered total exists only when both item price and shipping are known. Product metadata edits do not count as fresh price checks.

The newest observation is determined by its observed time. Recording an older price later should not replace a current quote. The journal remains a history of evidence, not an overwrite of the last value.

## When a target alert is allowed

All of these must be true:

1. The user has confirmed the actual room measurements; the room is no longer marked as a sample.
2. The product fits a planned reservation and its relevant modeled placement has no hard conflict.
3. The exact product variant and measurements are explicitly confirmed.
4. The exact variant is in stock.
5. Item price and shipping are known in EUR.
6. Delivered price is at or below the recorded target.
7. The quote is no older than 24 hours.
8. The product and quote are not marked demonstration data.
9. Monitoring is enabled for that product.

An unchanged qualifying observation does not repeatedly notify. An alert records the conditions at the time it was generated; current facts may change. Recheck the retailer before acting.

## Item-price changes

An informational notice can report a lower item price even when shipping is unknown. It still requires a confirmed room, a valid fit, a confirmed exact variant, current stock, a fresh non-demo quote, and enabled monitoring. It compares the newest quote against the preceding quote for the same saved product identity. The first quote, repeated price, changed identity, and backdated insertion do not create a drop notice.

This notice is labeled separately from a target alert and does not establish a delivered total or recommend buying. If a quote passes the delivered-price checks, the target alert takes priority.

## Live source scope

The adapter reads public [Schema.org Product](https://schema.org/Product) and [Offer](https://schema.org/Offer) JSON-LD. It supports one explicit current EUR offer; it rejects aggregate ranges, multiple/ambiguous product variants, expired offers, and missing prices.

Delivery is deliberately left unknown by the adapter. A general page-level delivery rate may not apply to a particular postcode, quantity, or basket. The user needs to record confirmed delivery for their case.

Automatic variant confirmation requires the user to confirm the saved variant and provide a retailer SKU. The fetched SKU must match exactly, the requested product URL must match the saved link, and the quote must carry the current product identity signature. Names alone cannot establish a variant match. Changing the URL, SKU, variant, colour or dimensions invalidates previous identity evidence. Manual quotes have their own explicit variant confirmation.

The fetcher uses HTTPS, public-address checks, pinned connections, bounded responses, redirect validation, and crawling-permission checks. It sends no cookies or account credentials. It cannot bypass a blocked page, authenticate, or execute JavaScript-only offers. Requests have socket and body-read time limits; the complete DNS, crawling-permission and redirect sequence has no single overall deadline.

## Flat records and ownership

The flat base is separate from room geometry. Inventory entries have a name, category, location, exact spot, positive integer quantity and optional owner. A NULL owner means Shared. Owner IDs must refer to current flat members. Members are bookkeeping labels, not authenticated accounts.

Kitchen stock entries belong to Fridge, Freezer or Pantry. Quantity is ordinary descriptive text. Stock is Stocked, Low or Out. Low and Out entries form the shopping checklist. Best-before dates are optional calendar dates used for planning; they are not freshness or food-safety conclusions.

Removing a referenced member is rejected. Existing records must first be reassigned or removed deliberately. The empty starter includes no invented objects, groceries or expense receipts.

## Shared expense arithmetic

Amounts are stored as positive integer cents in EUR. Equal shares use integer division. Remaining cents are assigned to the first participants in saved order. For example, 2,000 cents shared by three people yields 667, 667 and 666 cents.

Balance = bills paid − allocated share + repayments sent − repayments received. Positive means owed money; negative means owing money. Balances must sum to zero. Suggested payments match debtors to creditors deterministically and reconcile the recorded balances; the method is not claimed to find the fewest possible transfers.

A payer may pay for other participants without taking a share. Expense edits change the current ledger; entries are not immutable accounting receipts. A repayment records money the user says has already been sent between two different members. It adjusts balances without adding to spending. Overpayments are allowed and can reverse who owes whom. The app does not send money, connect to banks or verify transfers.

Monthly templates store the usual amount, payer, participant order and due day. A due day beyond the end of a month uses its last day. Templates are limited to 100 and repayments to 500 records. Neither an active template nor its due date creates an expense automatically. The user reviews a draft before recording a paid bill. An expense's optional `bill_id` and `bill_month` appear together; its month must match its payment date. Duplicate bill/month pairs are rejected. Deleting a template preserves expenses already recorded from it.

## Backups

Schema 3 exports contain the room, products, observations and complete flat, including repayments and monthly templates. Import validation completes before replacement, so rejected data cannot erase the existing workspace. Schema 1 room-only imports leave the current flat unchanged. Schema 2 imports restore the flat records present in that backup; missing repayments and monthly bills become empty lists. The import preview warns about this before confirmation. Resetting the sample room preserves the flat. Imports do not replay historical price notifications.

Expense CSV has one row per participant share. The expense's total repeats on each row: do not sum that total column across participant rows. Sum `share_cents` for allocated amounts, or count each expense ID once for expense totals.

Repayment CSV has one row per repayment, with sender, recipient, date, amount in cents and notes. Keep it separate from spending totals. Both CSV exports neutralize text that spreadsheet tools could read as formulas.

## What is not claimed

No actual savings, product availability, market price coverage, behavioral outcome, professional room survey, architectural compliance, or trained model is established by this software. Tests establish specific implemented properties and failure handling. Read `VERIFICATION.md` for the evidence from this build.
