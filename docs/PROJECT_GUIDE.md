# Read this first

RoomMate has one main job: connect a measured place in a student room to a planned upgrade and its price evidence.

## Use the app

1. Run `python -m roommate` from the project directory. On Windows you can run `start.ps1`.
2. Open the local address printed in the terminal.
3. Look at the sample room. It is 300 × 350 cm, not a measurement of anyone's actual room.
4. Open Room settings, enter the actual measurements, and review doors, windows, and obstacles. Confirm them only after measuring; sample rooms cannot create buying alerts. Choose wall and floor colours for a rough plan preview.
5. Add what you own with full external dimensions. Select an item to edit or rotate it.
6. Add a planned item where you want something later. Its dimensions define the reservation.
7. Link a wishlist product to that reservation. Enter the exact product variant and dimensions. For automatic price-drop notices, also enter and confirm the retailer's exact SKU.
8. Record a checked price with shipping, stock, evidence URL, and time. Unknown shipping stays blank.
9. Check the fit and price explanation. A target alert is a decision prompt; it does not purchase anything.
10. Export a backup from the workspace data menu before making a large change.

Scheduled price checks run only while the server is running and the product's monitoring is enabled. An unsupported page can still be recorded manually. The project does not claim coverage of every store.

## Understand it without reading everything

Start with one behavior. For example, move the desk 10 cm to the right and follow the change:

| Step | File | What happens |
|---|---|---|
| Click or drag | `web/app.js` | Updates the selected item's coordinates and sends a JSON request |
| API request | `roommate/server.py` | Checks the request and calls the room-storage operation |
| Measurement checks | `roommate/geometry.py` | Validates dimensions and checks the new placement |
| Persistence | `roommate/storage.py` | Saves the room in SQLite |
| Response | `web/app.js` | Shows the saved room and any conflicts |

An API is the interface between the browser and Python. JSON is the structured text they exchange. SQLite is a database stored in one local file. None of these require a paid cloud account.

## The main concepts

**Room:** dimensions, wall openings, budget, style, notes, and items.

**Owned item:** something you already have. It appears with a solid outline.

**Planned item:** a future place. It appears with a dashed outline and reserves its footprint.

**Product:** a particular retailer item or variant, linked to a planned place.

**Observation:** a dated record of a price, shipping, stock, source, and variant check. Keeping observations separately allows price history to remain inspectable.

**Notification:** either a confirmed delivered-price target alert or a separately labeled item-price change. RoomMate prevents the same unchanged offer from generating repeated alerts. An imported backup restores observations without replaying old notifications.

## What “fits” means

The entered product dimensions fit the linked reservation in one of the modeled 0° or 90° orientations, and the relevant modeled room placement is not blocked. This is a geometric check using rectangles. It does not model assembly access, comfort, detailed shapes, structural loads, or building compliance.

For a lamp, choose Surface and a supporting desk. Coordinates are local to that surface. A rug uses Overlay, so furniture can overlap it. Wall items do not count as occupied floor furniture.

## Learn from a small change later

When you want to learn the code, begin by changing one room label or adding a new sample item. Then run the existing tests. Next, change a placement rule and add a test that demonstrates the intended behavior. Follow with one SQL report over observations.

Keep the first learning task small. You do not need to understand the network importer, server, drawing code, and database schema in one sitting.

## Run the checks

```sh
python -m unittest discover -s tests -v
node --check web/app.js
```

The tests exercise meaningful behaviors and failure cases. Passing tests do not establish real room safety or universal retailer compatibility. See `VERIFICATION.md` for the recorded checks and limits.
