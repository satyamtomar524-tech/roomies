/* Each case uses a fresh browser context and resets a disposable local database. */
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");
const http = require("node:http");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const staticDir =
  process.env.ROOMIES_STATIC_DIR &&
  path.resolve(process.env.ROOMIES_STATIC_DIR);
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function main() {
  const temporary = await fs.mkdtemp(
    path.join(os.tmpdir(), "roomies-frontend-"),
  );
  const socket = net.createServer();
  await new Promise((resolve) => socket.listen(0, "127.0.0.1", resolve));
  const port = socket.address().port;
  await new Promise((resolve) => socket.close(resolve));
  const base = `http://127.0.0.1:${port}`;
  const server =
    !staticDir &&
    spawn(
      process.env.ROOMMATE_PYTHON || "python",
      [
        "-m",
        "roommate",
        "--port",
        String(port),
        "--db",
        path.join(temporary, "room.sqlite3"),
        "--no-tracker",
      ],
      { cwd: root, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] },
    );
  let serverOutput = "",
    startError,
    browser,
    staticServer,
    activePage;
  if (server) {
    server.stdout.on("data", (chunk) => {
      serverOutput += chunk;
    });
    server.stderr.on("data", (chunk) => {
      serverOutput += chunk;
    });
    server.on("error", (error) => {
      startError = error;
    });
  } else {
    const mime = {
      ".html": "text/html",
      ".js": "application/javascript",
      ".mjs": "application/javascript",
      ".css": "text/css",
      ".wasm": "application/wasm",
      ".zip": "application/zip",
      ".json": "application/json",
    };
    staticServer = http.createServer(async (request, response) => {
      const pathname = new URL(request.url, base).pathname;
      const file = path.resolve(
        staticDir,
        "." + (pathname === "/" ? "/index.html" : pathname),
      );
      if (!file.startsWith(staticDir + path.sep))
        return response.writeHead(403).end();
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
    await new Promise((resolve) =>
      staticServer.listen(port, "127.0.0.1", resolve),
    );
  }
  const failures = [];
  let casesRun = 0;
  try {
    let ready = false;
    for (let i = 0; i < 60; i++) {
      if (startError) throw startError;
      if (server && server.exitCode !== null) throw new Error(serverOutput);
      try {
        ready = (await fetch(base + (staticDir ? "/" : "/api/state"))).ok;
      } catch {}
      if (ready) break;
      await pause(200);
    }
    assert(ready, `Disposable server failed to start: ${serverOutput}`);
    const request = async (url, method = "GET", body) => {
      if (staticDir)
        return activePage.evaluate(
          async ({ url, method, body }) => {
            const data = await window.roomiesBrowser.request(url, {
              method,
              body: body && JSON.stringify(body),
            });
            return data.text ? JSON.parse(data.text) : data;
          },
          { url, method, body },
        );
      const response = await fetch(base + url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: body && JSON.stringify(body),
      });
      const data = await response.json();
      assert(response.ok, JSON.stringify(data));
      return data;
    };
    let baseline = staticDir ? null : await request("/api/export");
    browser = await chromium.launch({
      headless: true,
      ...(process.env.ROOMMATE_BROWSER_PATH
        ? { executablePath: process.env.ROOMMATE_BROWSER_PATH }
        : {}),
    });

    async function test(name, run) {
      if (
        process.env.ROOMIES_REGRESSION_FILTER &&
        !new RegExp(process.env.ROOMIES_REGRESSION_FILTER).test(name)
      )
        return;
      casesRun++;
      if (!staticDir) await request("/api/import", "POST", baseline);
      const context = await browser.newContext({
        viewport: { width: 1440, height: 1000 },
        acceptDownloads: true,
      });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("dialog", (dialog) => dialog.dismiss());
      await page.route("**/*", (route) =>
        new URL(route.request().url()).origin === base
          ? route.continue()
          : route.abort(),
      );
      if (process.env.ROOMMATE_APP_JS)
        await page.route("**/app.js", (route) =>
          route.fulfill({
            path: process.env.ROOMMATE_APP_JS,
            contentType: "application/javascript",
          }),
        );
      try {
        await page.goto(base);
        await page.waitForFunction(
          () =>
            document
              .querySelector("#save-status")
              .textContent.includes("All changes saved"),
          null,
          { timeout: 60000 },
        );
        activePage = page;
        baseline ||= await request("/api/export");
        await page.locator('.navigation [data-view="room"]').click();
        await run(page, request);
        assert.deepEqual(errors, [], "Unexpected browser errors");
        console.log(`PASS ${name}`);
      } catch (error) {
        failures.push(`${name}: ${error.message}`);
        console.error(`FAIL ${name}: ${error.message}`);
      } finally {
        await context.close();
      }
    }
    const saved = (page) =>
      page.waitForFunction(
        () => savedRevision === mutationRevision && savingPromise === null,
      );
    const field = (page, name) => page.locator(`#item-form [name="${name}"]`);

    await test("autosave preserves furniture keyboard focus", async (page) => {
      await page.locator('[data-item-id="bed"]').focus();
      await page.keyboard.press("ArrowRight");
      await saved(page);
      assert.equal(
        await page.evaluate(() => document.activeElement.dataset.itemId),
        "bed",
      );
      await page.keyboard.press("ArrowRight");
      await saved(page);
      assert.equal(
        (await request("/api/state")).room.items.find(
          (item) => item.id === "bed",
        ).x_cm,
        10,
      );
    });

    await test("edits during the final save refresh are persisted", async (page) => {
      await page.evaluate(() => {
        const original = api;
        let held = false;
        api = async (url, options) => {
          if (url === "/api/state" && !held) {
            held = true;
            window.testRefreshStarted = true;
            await new Promise((resolve) => setTimeout(resolve, 900));
          }
          return original(url, options);
        };
      });
      await page.evaluate(() => {
        itemById("bed").x_cm = 5;
        markDirty(0);
      });
      await page.waitForFunction(() => window.testRefreshStarted);
      await page.evaluate(() => {
        itemById("bed").x_cm = 10;
        markDirty();
      });
      await page.waitForFunction(() => savingPromise === null);
      assert.equal(
        await page.evaluate(() => savedRevision),
        await page.evaluate(() => mutationRevision),
      );
      assert.equal(
        (await request("/api/state")).room.items.find(
          (item) => item.id === "bed",
        ).x_cm,
        10,
      );
    });

    await test("stale suggestions cannot change another item or an edited room", async (page) => {
      await page.evaluate(() => {
        const original = api;
        api = async (url, options) => {
          if (url !== "/api/suggest") return original(url, options);
          if (JSON.parse(options.body).item_id !== "desk")
            throw new Error("Wrong requested suggestion item");
          await new Promise((resolve) => setTimeout(resolve, 400));
          return { placements: [{ x_cm: 111, y_cm: 122, rotation: 90 }] };
        };
      });
      await page.locator('[data-item-id="desk"]').click();
      await page.locator("#suggest-positions").click();
      await page.locator('[data-item-id="bed"]').click();
      await page.waitForFunction(
        () => !document.querySelector("#suggest-positions").disabled,
      );
      assert(await page.locator("#suggestions").isHidden());
      assert.equal(
        (await request("/api/state")).room.items.find(
          (item) => item.id === "bed",
        ).x_cm,
        0,
      );
      await page.locator('[data-item-id="desk"]').click();
      await page.locator("#suggest-positions").click();
      await page.locator("#suggestions .suggestion-button").waitFor();
      await field(page, "width_cm").fill("112");
      await page.locator("#suggestions .suggestion-button").click();
      await saved(page);
      assert(await page.locator("#suggestions").isHidden());
      assert.equal(
        (await request("/api/state")).room.items.find(
          (item) => item.id === "desk",
        ).x_cm,
        185,
      );
    });

    await test("editing a purchased find preserves its owned room link", async (page) => {
      await page.evaluate(async () => {
        await api("/api/products", {
          method: "POST",
          body: JSON.stringify({
            id: "purchased-desk",
            name: "Desk find",
            variant: "100 x 50 cm",
            item_id: "desk",
            url: "https://example.com/desk",
            width_cm: 100,
            depth_cm: 50,
            height_cm: 50,
            target_eur: 120,
            monitor: false,
            currency: "EUR",
          }),
        });
        await reload();
      });
      await page.locator('[data-item-id="desk"]').click();
      await field(page, "status").selectOption("owned");
      await saved(page);
      await page.evaluate(() => openProduct("desk", "purchased-desk"));
      assert.equal(
        await page.locator('#product-form [name="item_id"]').inputValue(),
        "desk",
      );
      await page
        .locator('#product-form [name="notes"]')
        .fill("Purchased; keep this link");
      await page.locator('#product-form button[type="submit"]').click();
      await page.locator("#product-dialog").waitFor({ state: "hidden" });
      const product = (await request("/api/state")).products.find(
        (product) => product.id === "purchased-desk",
      );
      assert.equal(product.item_id, "desk");
      assert.equal(product.identity_notes, "Purchased; keep this link");
    });

    await test("invalid drafts survive selection and save when repaired", async (page) => {
      await page.locator('[data-item-id="bed"]').click();
      await field(page, "width_cm").fill("");
      await field(page, "name").fill("My edited bed");
      assert.match(
        await page.locator("#save-status").textContent(),
        /not saved/i,
      );
      assert.equal(
        await page.evaluate(() => {
          const event = new Event("beforeunload", { cancelable: true });
          window.dispatchEvent(event);
          return event.defaultPrevented;
        }),
        true,
      );
      await page.locator('[data-item-id="desk"]').click();
      await field(page, "width_cm").fill("112");
      await saved(page);
      assert.match(
        await page.locator("#save-status").textContent(),
        /not saved/i,
      );
      await page.locator('[data-item-id="bed"]').click();
      assert.equal(await field(page, "width_cm").inputValue(), "");
      assert.equal(await field(page, "name").inputValue(), "My edited bed");
      assert.equal(
        (await request("/api/state")).room.items.find(
          (item) => item.id === "bed",
        ).name,
        "Bed",
      );
      await field(page, "width_cm").fill("120");
      await saved(page);
      assert.equal(
        (await request("/api/state")).room.items.find(
          (item) => item.id === "bed",
        ).name,
        "My edited bed",
      );
      assert.match(
        await page.locator("#save-status").textContent(),
        /All changes saved/,
      );
    });

    await test("valid own backups above 2 MiB restore; above 32 MiB reject", async (page) => {
      const large = structuredClone(baseline),
        notes = "x".repeat(1000);
      large.flat.members.push({ id: "other", name: "Other" });
      large.flat.inventory = Array.from({ length: 500 }, (_, i) => ({
        id: `i${i}`,
        name: `Item ${i}`,
        owner_id: null,
        notes,
        quantity: 1,
        category: "other",
        location: "Room",
        spot: "",
      }));
      large.flat.fridge = Array.from({ length: 300 }, (_, i) => ({
        id: `f${i}`,
        name: `Food ${i}`,
        owner_id: null,
        notes,
        quantity: "1",
        storage: "fridge",
        status: "stocked",
        best_before: null,
      }));
      large.flat.expenses = Array.from({ length: 500 }, (_, i) => ({
        id: `e${i}`,
        title: `Expense ${i}`,
        amount_cents: 100,
        paid_by: "me",
        split_between: ["me", "other"],
        date: "2026-09-30",
        category: "other",
        notes: "x".repeat(2000),
      }));
      large.flat.repayments = Array.from({ length: 500 }, (_, i) => ({
        id: `r${i}`,
        from_id: "other",
        to_id: "me",
        amount_cents: 1,
        date: "2026-09-30",
        notes,
      }));
      await request("/api/import", "POST", large);
      const text = staticDir
        ? await page.evaluate(
            async () =>
              (await window.roomiesBrowser.request("/api/export")).text,
          )
        : await (await fetch(`${base}/api/export`)).text();
      const buffer = Buffer.from(text);
      assert(buffer.length > 2 * 1024 * 1024);
      await request("/api/import", "POST", baseline);
      await page.locator("#data-menu-top").click();
      await page.locator("#import-file").setInputFiles({
        name: "large-own-backup.json",
        mimeType: "application/json",
        buffer,
      });
      await page.locator("#import-preview").waitFor({ state: "visible" });
      await page.locator("#confirm-import").click();
      await page.locator("#data-dialog").waitFor({ state: "hidden" });
      assert.equal((await request("/api/state")).flat.inventory.length, 500);
      await page.locator("#data-menu-top").click();
      await page.evaluate(() =>
        readImport({
          target: {
            files: [
              {
                size: 32 * 1024 * 1024 + 1,
                text: async () => {
                  throw new Error("Oversized file should not be read");
                },
              },
            ],
          },
        }),
      );
      assert.match(
        await page.locator("#import-error").textContent(),
        /larger than 32 MiB/,
      );
      assert(await page.locator("#import-preview").isHidden());
    });

    await test("failed room and flat saves allow a clearly labeled saved-only backup", async (page) => {
      const worker = staticDir && page.workers()[0];
      async function setFailure(fail) {
        if (worker)
          await worker.evaluate((fail) => {
            self.testOriginalPut ||= IDBObjectStore.prototype.put;
            IDBObjectStore.prototype.put = fail
              ? function () {
                  throw new DOMException(
                    "Simulated full storage",
                    "QuotaExceededError",
                  );
                }
              : self.testOriginalPut;
          }, fail);
        else
          await page.evaluate((fail) => {
            window.testFailSave = fail;
          }, fail);
      }
      if (!staticDir)
        await page.evaluate(() => {
          window.roomiesBrowser = {
            async request(url, options = {}) {
              if (window.testFailSave && options.method === "PUT")
                throw new Error("Simulated full storage");
              const response = await fetch(url, {
                headers: { "Content-Type": "application/json" },
                ...options,
              });
              if (!response.ok) throw new Error((await response.json()).error);
              if (url.startsWith("/api/export"))
                return {
                  text: await response.text(),
                  type: "application/json",
                  filename: "roomies-backup.json",
                };
              return response.json();
            },
            async download(url) {
              const result = await this.request(url);
              const href = URL.createObjectURL(
                new Blob([result.text], { type: result.type }),
              );
              const link = Object.assign(document.createElement("a"), {
                href,
                download: result.filename,
              });
              document.body.append(link);
              link.click();
              link.remove();
              setTimeout(() => URL.revokeObjectURL(href), 1000);
            },
          };
        });
      await setFailure(true);
      await page.evaluate(() => {
        itemById("bed").x_cm = 15;
        markDirty(0);
      });
      await page.waitForFunction(
        () =>
          savingPromise === null &&
          document
            .querySelector("#save-status")
            .textContent.includes("Not saved"),
      );
      await page.locator("#data-menu-top").click();
      assert.match(
        await page.locator("#backup-recovery").textContent(),
        /only the last saved workspace.*excludes those edits/,
      );
      let downloadPromise = page.waitForEvent("download");
      await page.locator("#export-saved-backup").click();
      let download = await downloadPromise;
      let exported = JSON.parse(
        await fs.readFile(await download.path(), "utf8"),
      );
      assert.equal(
        exported.room.items.find((item) => item.id === "bed").x_cm,
        0,
      );
      assert.equal(
        await page.evaluate(() => savedRevision < mutationRevision),
        true,
      );
      assert.match(
        await page.locator("#toast").textContent(),
        /latest edits are still unsaved/,
      );
      await setFailure(false);
      await page.evaluate(() => flushRoom());
      assert(await page.locator("#backup-recovery").isHidden());
      await setFailure(true);
      await page.evaluate(async () => {
        try {
          await updateFlat((flat) => {
            flat.name = "Unsaved flat name";
          });
        } catch {}
      });
      assert(await page.locator("#backup-recovery").isVisible());
      downloadPromise = page.waitForEvent("download");
      await page.locator("#export-saved-backup").click();
      download = await downloadPromise;
      exported = JSON.parse(await fs.readFile(await download.path(), "utf8"));
      assert.equal(exported.flat.name, baseline.flat.name);
      assert.match(
        await page.locator("#save-status").textContent(),
        /not saved/i,
      );
      await setFailure(false);
      await page.evaluate(async () => {
        itemById("bed").x_cm = 20;
        markDirty(0);
        await flushRoom();
      });
      assert.match(
        await page.locator("#save-status").textContent(),
        /Flat changes not saved/,
      );
      assert(await page.locator("#backup-recovery").isVisible());
      await page.evaluate(() =>
        updateFlat((flat) => {
          flat.name = "Saved flat name";
        }),
      );
      assert.match(
        await page.locator("#save-status").textContent(),
        /All changes saved/,
      );
      assert(await page.locator("#backup-recovery").isHidden());
      await setFailure(true);
      await page.evaluate(async () => {
        try {
          await updateFlat((flat) => {
            flat.name = "Another unsaved flat name";
          });
        } catch {}
      });
      await setFailure(false);
      await page.locator("#import-file").setInputFiles({
        name: "restore-after-failure.json",
        mimeType: "application/json",
        buffer: Buffer.from(JSON.stringify(baseline)),
      });
      await page.locator("#import-preview").waitFor({ state: "visible" });
      await page.locator("#confirm-import").click();
      await page.locator("#data-dialog").waitFor({ state: "hidden" });
      assert.equal(await page.evaluate(() => flatSaveError), null);
      assert.equal((await request("/api/state")).flat.name, baseline.flat.name);
      assert.match(
        await page.locator("#save-status").textContent(),
        /All changes saved/,
      );
      assert.equal(
        await page
          .locator("#backup-recovery")
          .evaluate((element) => element.hidden),
        true,
      );
    });

    await test("a draft created while export waits prevents an incomplete export", async (page) => {
      let downloads = 0;
      page.on("download", () => downloads++);
      await page.evaluate(() => {
        const original = api;
        let held = false;
        api = async (url, options) => {
          if (url === "/api/room" && options?.method === "PUT" && !held) {
            held = true;
            window.testRefreshStarted = true;
            await new Promise((resolve) => setTimeout(resolve, 900));
          }
          return original(url, options);
        };
        itemById("bed").x_cm = 5;
        markDirty(0);
      });
      await page.waitForFunction(() => window.testRefreshStarted);
      await page.evaluate(() => {
        window.testExport = downloadData("/api/export");
      });
      await page.locator('[data-item-id="bed"]').click();
      await field(page, "width_cm").fill("");
      await page.evaluate(() => window.testExport);
      assert.equal(downloads, 0);
      assert.match(
        await page.locator("#toast").textContent(),
        /Correct the invalid item fields/,
      );
      assert.match(
        await page.locator("#save-status").textContent(),
        /not saved/i,
      );
    });

    await test("room completion does not report success over a pending or failed flat save", async (page) => {
      await page.evaluate(() => {
        const original = api;
        api = async (url, options) => {
          if (url === "/api/flat" && options?.method === "PUT") {
            await new Promise((resolve) => setTimeout(resolve, 1200));
            throw new Error("Simulated flat persistence failure");
          }
          return original(url, options);
        };
        window.testFlatSave = updateFlat((flat) => {
          flat.name = "Pending flat";
        }).catch(() => {});
        itemById("bed").x_cm = 5;
        markDirty(0);
      });
      await page.waitForFunction(
        () => savingPromise === null && savedRevision === mutationRevision,
      );
      assert.equal(await page.evaluate(() => Boolean(flatSavingPromise)), true);
      assert.doesNotMatch(
        await page.locator("#save-status").textContent(),
        /All changes saved/,
      );
      await page.evaluate(() => window.testFlatSave);
      await page.evaluate(async () => {
        itemById("bed").x_cm = 10;
        markDirty(0);
        await flushRoom();
      });
      assert.match(
        await page.locator("#save-status").textContent(),
        /Flat changes not saved/,
      );
      assert.equal(
        await page
          .locator("#backup-recovery")
          .evaluate((element) => element.hidden),
        false,
      );
    });
    await test("export errors keep truthful save status and stay in the workspace", async (page) => {
      let downloads = 0;
      page.on("download", () => downloads++);
      if (staticDir)
        await page.evaluate(() => {
          const original = window.roomiesBrowser.request.bind(
            window.roomiesBrowser,
          );
          window.roomiesBrowser.request = (url, options) => {
            if (url.startsWith("/api/export"))
              throw new Error("This backup is larger than 32 MiB.");
            return original(url, options);
          };
        });
      else
        await page.route("**/api/export?format=json", (route) =>
          route.fulfill({
            status: 413,
            contentType: "application/json",
            body: JSON.stringify({
              error: "This backup is larger than 32 MiB.",
            }),
          }),
        );
      const originalUrl = page.url();
      await page.evaluate(() => downloadData("/api/export?format=json"));
      assert.equal(page.url(), originalUrl);
      assert.equal(downloads, 0);
      assert.match(
        await page.locator("#save-status").textContent(),
        /All changes saved/,
      );
      assert.match(
        await page.locator("#toast").textContent(),
        /Export failed.*32 MiB/,
      );
      assert.doesNotMatch(
        await page.locator("#toast").textContent(),
        /not.*saved|unsaved/,
      );
      assert.equal(await page.locator("#backup-recovery").count(), 0);
    });
    if (failures.length)
      throw new Error(
        `${failures.length} frontend regression(s):\n${failures.join("\n")}`,
      );
    console.log(
      `All ${casesRun} frontend regression cases passed (${staticDir ? "static worker" : "local server"}).`,
    );
  } finally {
    if (browser) await browser.close();
    if (server && server.exitCode === null) {
      const stopped = new Promise((resolve) => server.once("exit", resolve));
      server.kill();
      await stopped;
    }
    if (staticServer)
      await new Promise((resolve) => staticServer.close(resolve));
    const resolvedTemporary = path.resolve(temporary);
    assert(
      resolvedTemporary.startsWith(path.resolve(os.tmpdir()) + path.sep) &&
        path.basename(resolvedTemporary).startsWith("roomies-frontend-"),
      "Cleanup target must be this test's disposable temporary directory",
    );
    await fs.rm(resolvedTemporary, { recursive: true, force: true });
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
