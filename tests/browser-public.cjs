/* Run against a static build: no local Python server or external requests. */
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const http = require("node:http");
const { chromium } = require("playwright");
const costsWorkflow = require("./costs-workflow.cjs");

async function main() {
  const root = path.resolve(__dirname, "..");
  const dist = path.resolve(
    process.env.ROOMIES_STATIC_DIR || path.join(root, "dist"),
  );
  const results = path.join(root, "test-results", "public");
  await fs.mkdir(results, { recursive: true });
  const mime = {
    ".html": "text/html",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".wasm": "application/wasm",
    ".css": "text/css",
    ".json": "application/json",
    ".zip": "application/zip",
  };
  const requested = [];
  const server = http.createServer(async (request, response) => {
    const pathname = new URL(request.url, "http://localhost").pathname;
    requested.push(pathname);
    const file = path.resolve(
      dist,
      "." + (pathname === "/" ? "/index.html" : pathname),
    );
    if (!file.startsWith(dist + path.sep)) {
      response.writeHead(403).end();
      return;
    }
    try {
      response.setHeader(
        "Content-Type",
        mime[path.extname(file)] || "application/octet-stream",
      );
      response.end(await fs.readFile(file));
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  let browser;
  const errors = [];
  const external = [];
  try {
    browser = await chromium.launch({
      headless: true,
      ...(process.env.ROOMMATE_BROWSER_PATH
        ? { executablePath: process.env.ROOMMATE_BROWSER_PATH }
        : {}),
    });
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
    });
    await context.route("**/*", (route) => {
      const url = new URL(route.request().url());
      if (url.origin === base || url.protocol === "blob:")
        return route.continue();
      external.push(url.href);
      return route.abort();
    });
    const page = await context.newPage();
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => {
      Object.defineProperty(document, "modelContext", {
        value: {
          registerTool: (tool) => {
            window.registeredRoomiesTool = tool;
          },
        },
      });
    });
    const loaded = (p) =>
      p.waitForFunction(
        () =>
          document
            .querySelector("#save-status")
            .textContent.includes("All changes saved"),
        null,
        { timeout: 60000 },
      );
    const getState = () =>
      page.evaluate(() => window.roomiesBrowser.request("/api/state"));
    const field = (form, name) => page.locator(`${form} [name="${name}"]`);
    const submit = (form) =>
      page.locator(`${form} button[type="submit"]`).click();
    const navigate = (view) =>
      page.locator(`.navigation .nav-link[data-view="${view}"]`).click();
    await page.goto(base);
    await loaded(page);
    assert.equal((await getState()).summary.area_m2, 10.5);
    assert.match(
      await page.locator(".browser-note").innerText(),
      /friends their own space/,
    );
    const tool = await page.evaluate(async () => ({
      name: window.registeredRoomiesTool.name,
      value: await window.registeredRoomiesTool.execute({}),
      invalid: await window.registeredRoomiesTool.execute({ extra: true }).then(
        () => false,
        () => true,
      ),
    }));
    assert.equal(tool.name, "read_roomies_overview");
    assert.equal(tool.value.room.area_m2, 10.5);
    assert(tool.invalid);

    await navigate("room");
    await page.locator('[data-item-id="bed"]').click();
    await page.locator('[data-item-id="bed"]').focus();
    await page.keyboard.press("ArrowRight");
    await page.waitForFunction(
      () => document.querySelector('#item-form [name="x_cm"]').value === "5",
    );
    await page.waitForTimeout(400);
    await loaded(page);
    assert.equal((await getState()).room.items[0].x_cm, 5);
    await page.locator('[data-item-id="desk"]').click();
    await page.locator("#suggest-positions").click();
    await page.locator("#suggestions .suggestion-button").first().click();
    await page.waitForTimeout(400);
    await loaded(page);
    assert((await getState()).summary.valid);

    await navigate("flat");
    await page.locator("#flat-settings-button").click();
    await field("#flat-settings-form", "name").fill("Friends test flat");
    await field("#flat-settings-form", "confirmed").check();
    await page.locator("#flat-members-editor input").first().fill("Alice");
    await page.locator("#add-flat-member").click();
    await page.locator("#flat-members-editor input").last().fill("Bob");
    await submit("#flat-settings-form");
    await page.locator("#flat-dialog").waitFor({ state: "hidden" });
    const people = (await getState()).flat.members;
    await page.locator("#add-flat-item").click();
    for (const [key, value] of Object.entries({
      name: "Kettle",
      category: "kitchen",
      location: "Kitchen",
      spot: "Beside the sink",
      quantity: "1",
    }))
      await field("#flat-item-form", key).fill(value);
    await submit("#flat-item-form");
    await page.locator("#flat-item-dialog").waitFor({ state: "hidden" });
    assert.equal((await getState()).flat.inventory[0].spot, "Beside the sink");

    await navigate("kitchen");
    await page.locator("#add-fridge-item").click();
    await field("#fridge-form", "name").fill("Milk");
    await field("#fridge-form", "quantity").fill("One carton");
    await field("#fridge-form", "status").selectOption("low");
    await submit("#fridge-form");
    await page.locator("#fridge-dialog").waitFor({ state: "hidden" });
    assert.match(await page.locator("#shopping-list").innerText(), /Milk/);
    await page
      .locator("#shopping-list")
      .getByRole("button", { name: "Restocked", exact: true })
      .click();
    await page.waitForFunction(
      () => document.querySelector("#shopping-count").textContent === "0",
    );

    await navigate("expenses");
    await page.locator("#add-expense").click();
    await field("#expense-form", "title").fill("Groceries");
    await field("#expense-form", "amount").fill("30.01");
    await field("#expense-form", "paid_by").selectOption(people[0].id);
    for (const person of people)
      await page
        .locator(`#expense-participants input[value="${person.id}"]`)
        .check();
    await submit("#expense-form");
    await page.locator("#expense-dialog").waitFor({ state: "hidden" });
    assert.equal(
      (await getState()).flat_summary.expenses.settlements[0].amount_cents,
      1500,
    );
    await costsWorkflow(page, getState, results);

    await navigate("wishlist");
    assert(!(await page.locator("#check-all").isVisible()));
    await page.locator("#add-product").click();
    for (const [key, value] of Object.entries({
      name: "Small desk",
      url: "https://example.com/desk",
      target_price: "80",
      width_cm: "100",
      depth_cm: "50",
      height_cm: "73",
      color: "Oak",
      variant: "100 by 50 cm",
    }))
      await field("#product-form", key).fill(value);
    await field("#product-form", "item_id").selectOption("desk");
    await field("#product-form", "variant_confirmed").check();
    await submit("#product-form");
    await page.locator("#product-dialog").waitFor({ state: "hidden" });
    assert.equal((await getState()).products[0].evaluation.fit, "pass");
    await page
      .getByRole("button", { name: "+ Record price", exact: true })
      .click();
    await field("#observation-form", "price").fill("70");
    await field("#observation-form", "shipping").fill("5");
    await field("#observation-form", "availability").selectOption("in_stock");
    await field("#observation-form", "variant_confirmed").check();
    await submit("#observation-form");
    await page.locator("#observation-dialog").waitFor({ state: "hidden" });
    assert.equal((await getState()).products[0].evaluation.delivered_eur, 75);
    await page.locator("#data-menu-top").click();
    const download = page.waitForEvent("download");
    await page.locator('a[href="/api/export?format=json"]').click();
    const backup = await download;
    const backupPath = path.join(results, "complete-workspace.json");
    await backup.saveAs(backupPath);
    const exported = JSON.parse(await fs.readFile(backupPath, "utf8"));
    assert.equal(exported.products[0].observations.length, 1);
    await page.locator("#import-file").setInputFiles(backupPath);
    await page.locator("#confirm-import").click();
    await page.locator("#data-dialog").waitFor({ state: "hidden" });
    assert.equal((await getState()).products[0].observations.length, 1);

    // A failed browser write must roll back memory as well as report an error.
    const before = await getState();
    const worker = page
      .workers()
      .find((w) => w.url().endsWith("browser-worker.mjs"));
    await worker.evaluate(() => {
      self.originalPut = IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put = () => {
        throw new DOMException("Storage full", "QuotaExceededError");
      };
    });
    const failed = await page.evaluate(async () => {
      const s = await window.roomiesBrowser.request("/api/state");
      s.flat.name = "Must not be saved";
      return window.roomiesBrowser
        .request("/api/flat", { method: "PUT", body: JSON.stringify(s.flat) })
        .then(
          () => false,
          () => true,
        );
    });
    assert(failed);
    await worker.evaluate(() => {
      IDBObjectStore.prototype.put = self.originalPut;
    });
    assert.deepEqual((await getState()).flat, before.flat);

    const secondTab = await context.newPage();
    await secondTab.goto(base);
    await secondTab.locator("#load-error:not([hidden])").waitFor();
    assert.match(
      await secondTab.locator("#load-error").innerText(),
      /another tab/,
    );
    assert(await secondTab.locator("#add-flat-item").isDisabled());
    await secondTab.close();
    const friend = await browser.newContext();
    const friendPage = await friend.newPage();
    await friendPage.goto(base);
    await loaded(friendPage);
    assert.equal(
      await friendPage.evaluate(
        async () =>
          (await window.roomiesBrowser.request("/api/state")).flat.inventory
            .length,
      ),
      0,
    );
    await friend.close();
    await page.reload();
    await loaded(page);
    assert.deepEqual((await getState()).flat, before.flat);
    assert.equal((await getState()).products[0].observations.length, 1);

    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      for (const view of [
        "home",
        "room",
        "flat",
        "kitchen",
        "expenses",
        "wishlist",
        "journal",
      ]) {
        if (view === "journal")
          await page.locator('#view-wishlist [data-view="journal"]').click();
        else await navigate(view);
        assert(
          await page.evaluate(
            () =>
              document.documentElement.scrollWidth <=
              document.documentElement.clientWidth,
          ),
          `${view} overflows at ${width}px`,
        );
      }
    }
    await page.goto(`${base}/guide.html`);
    assert.match(
      await page.locator("body").innerText(),
      /Sharing the link does not share/,
    );
    assert.equal(requested.filter((url) => url.startsWith("/api/")).length, 0);
    assert.deepEqual(external, []);
    assert.deepEqual(errors, []);
    console.log(
      "PASS: static browser app, room edits, belongings, kitchen, expenses, repayments, monthly bills, prices, downloads/import, persistence, visitor isolation, tab protection, quota rollback, and 320/390px layouts. No public API or external browser requests.",
    );
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
