# Roomies

**My room. My things. Our flat.**

I wanted to know how my room could look before buying more things. Would a bed fit? Where could I keep a table? Could I leave a space for a lamp that I don't have yet?

Then the idea got bigger. I also wanted to remember where I kept my things, check what was in the kitchen, and work out shared bills with flatmates. That is what Roomies brings together.

![Roomies home screen](docs/screenshots/home-desktop.png)

## What it does

| Page | What you can do |
|---|---|
| Home | See what's useful next and open the right page |
| My room | Move measured furniture, reserve space for future items and try wall and floor colours |
| My flat | Save what you own, who owns it, and exactly where it is kept |
| Kitchen | Keep a fridge, freezer and pantry checklist; see what is running low |
| Shared costs | Split bills, record money paid back and save monthly bill details |
| Upgrades | Save products, compare their size with your plan and keep dated price records |

The room starts with a clearly labelled **3 × 3.5 m sample**. It is there to try the planner. Replace it with your measurements when you are ready. The flat starts empty, with one placeholder person called Me.

## Open it in your browser

The public browser version lets friends try Roomies without installing Python. Each person gets their own workspace, saved on that device. The Share Roomies button shares the website, not your records. Export a backup before clearing browser data or changing devices.

Room planning, flat and kitchen lists, shared costs, repayments, monthly bills and manual price records work in the browser. It has no shared accounts or live sync between flatmates. Automatic retailer checks remain a feature of the local app below.

## Run it

You need Python 3.10 or newer. The app itself uses Python's standard library, so there is no API key or database server to set up.

```sh
git clone https://github.com/satyamtomar524-tech/roomies.git
cd roomies
python -m roommate
```

On Windows, you can run `py -m roommate` or `./start.ps1`. Open the local address printed in the terminal. Keep that terminal running while using the app; Ctrl+C stops it.

The module is still called `roommate` so older working copies keep working. Installing the package with `pip install .` also gives you the `roomies` command. Use `python -m roommate --no-tracker` if you only want planning and manual records.

## A small example

Save a kettle as **Kitchen → Worktop beside the sink → Shared**. Mark milk as **Low** and it appears on the shopping list.

For a shared bill, say one person pays €30 for groceries for two people. Each person's share is €15. When the other person pays back €15, record that repayment: both balances become zero, and total spending stays €30.

For rent or internet, save a monthly bill once. When it is paid, open the saved details, check the amount and date, and record it. The app stops the same saved bill being recorded twice for the same month. Templates never create charges on their own.

## How I built it

Python handles the rules and local HTTP API. SQLite stores the records. Plain JavaScript handles the forms, and SVG draws the room. Shared amounts are stored as whole cents so rounding cannot lose money. The public build uses Pyodide to run those same Python rules in a browser worker and saves the database in IndexedDB.

The idea and requirements are mine. I used coding assistance to build and review the implementation. I have kept the code, tests and guide together so I can understand the decisions and learn from the project.

Start with the [project guide](docs/PROJECT_GUIDE.md). The [architecture](docs/ARCHITECTURE.md) shows where each action goes in the code. [Verification](docs/VERIFICATION.md) records the checks, and [portfolio notes](docs/PORTFOLIO.md) give an accurate project description.

```sh
python -m unittest discover -s tests -v
node --check web/app.js
node --check web/flat.js
node --check web/costs.js
```

Browser checks are optional development tools. Their setup is in the verification guide. [GitHub Actions](https://github.com/satyamtomar524-tech/roomies/actions) runs the tests for each update.

## What this version covers

- The local app stores data on one computer; the public website stores it in each visitor's browser. Flatmate names are labels, so there are no shared logins or live phone-to-phone updates. Repayments are records of payments you made yourself.
- The room is a rough rectangular plan with dimension and clearance checks. Colours are schematic; it is not a construction drawing or a 3D rendering.
- Live price checks work only with compatible public product pages that permit crawling. No real retailer has been demonstrated as compatible yet. Manual price records work independently. Blank shipping stays unknown, and checks run only while the server is open.

Use the data menu for a complete backup. It includes bills, repayments and monthly templates as well as the room and flat. Keep your actual backups private; runtime databases are excluded from Git. [Data and rules](docs/DATA_AND_RULES.md) explains older backup formats and price evidence.

To build the shareable version yourself, see [browser hosting](docs/BROWSER_HOSTING.md).

## References

[Room-Planner](https://github.com/EricAndrechek/Room-Planner) and [price-tracker](https://github.com/sonoyumi/price-tracker) were reviewed as feature references for the original room and price idea. Their source code was not copied.

MIT license · Satyam Tomar
