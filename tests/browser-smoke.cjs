/* Runs against a disposable local database. No retailer pages are requested. */
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const net = require('node:net');
const { chromium } = require('playwright');
const flatWorkflow = require('./flat-workflow.cjs');

const root = path.resolve(__dirname, '..');
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function unusedPort() {
  const socket = net.createServer();
  await new Promise((resolve, reject) => socket.listen(0, '127.0.0.1', resolve).on('error', reject));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  return port;
}

async function main() {
  const port = await unusedPort();
  const base = `http://127.0.0.1:${port}`;
  const results = path.join(root, 'test-results', `browser-${Date.now()}`);
  await fs.mkdir(results, { recursive: true });
  const server = spawn(process.env.ROOMMATE_PYTHON || 'python', [
    '-m', 'roommate', '--port', String(port), '--db', path.join(results, 'room.sqlite3'), '--no-tracker',
  ], { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '';
  let startError;
  server.stdout.on('data', chunk => { output += chunk; });
  server.stderr.on('data', chunk => { output += chunk; });
  server.on('error', error => { startError = error; });
  let browser;
  const errors = [];
  try {
    let ready = false;
    for (let attempt = 0; attempt < 60; attempt++) {
      if (startError) throw startError;
      if (server.exitCode !== null) throw new Error(`Server exited: ${output}`);
      try { ready = (await fetch(`${base}/api/state`)).ok; } catch { /* Starting. */ }
      if (ready) break;
      await pause(200);
    }
    assert(ready, `Local server did not start: ${output}`);
    browser = await chromium.launch({ headless: true, ...(process.env.ROOMMATE_BROWSER_PATH ? { executablePath: process.env.ROOMMATE_BROWSER_PATH } : {}) });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      return url.origin === base || url.protocol === 'blob:' ? route.continue() : route.abort();
    });
    const state = async () => (await fetch(`${base}/api/state`)).json();
    const saved = async () => page.waitForFunction(() => document.querySelector('#save-status').textContent.includes('All changes saved'), null, { timeout: 10000 });
    const field = (form, name) => page.locator(`${form} [name="${name}"]`);
    await page.goto(base);
    await saved();
    let current = await state();
    assert.equal(current.room.items.length, 4);
    assert.equal(current.summary.area_m2, 10.5);
    assert(current.room.is_demo);
    assert.equal(current.products.length, 0);
    assert.equal(current.flat.inventory.length, 0);
    assert.equal(current.flat.fridge.length, 0);
    assert.equal(current.flat.expenses.length, 0);
    assert(await page.locator('#view-home').isVisible());
    await page.locator('.navigation .nav-link[data-view="room"]').click();

    await page.locator('[data-item-id="bed"]').click();
    await page.locator('[data-item-id="bed"]').focus();
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(() => document.querySelector('#item-form [name="x_cm"]').value === '5');
    await pause(350);
    await saved();
    assert.equal((await state()).room.items.find(item => item.id === 'bed').x_cm, 5);
    await page.locator('#item-form > details > summary').click();
    await field('#item-form', 'x_cm').fill('-25');
    await pause(550);
    await saved();
    assert.equal((await state()).summary.valid, false);
    await field('#item-form', 'x_cm').fill('0');
    await pause(550);
    await saved();
    assert.equal((await state()).summary.valid, true);

    const bedBox = await page.locator('[data-item-id="bed"]').boundingBox();
    await page.mouse.move(bedBox.x + bedBox.width / 2, bedBox.y + bedBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(bedBox.x + bedBox.width / 2 + 18, bedBox.y + bedBox.height / 2, { steps: 6 });
    await page.mouse.up();
    await pause(550);
    await saved();
    assert((await state()).room.items.find(item => item.id === 'bed').x_cm > 0);
    await field('#item-form', 'x_cm').fill('0');
    await pause(550);
    await saved();
    await page.locator('[data-item-id="bed"]').focus();
    await page.keyboard.press('r');
    await pause(350);
    await saved();
    assert.equal((await state()).room.items.find(item => item.id === 'bed').rotation, 90);
    await page.keyboard.press('r');
    await pause(350);
    await saved();

    await page.locator('[data-item-id="desk"]').click();
    await page.locator('#suggest-positions').click();
    await page.locator('#suggestions .suggestion-button').first().waitFor();
    await page.locator('#suggestions .suggestion-button').first().click();
    await pause(200);
    await saved();
    assert.equal((await state()).summary.valid, true);
    const planDownload = page.waitForEvent('download');
    await page.locator('#download-plan').click();
    assert.equal((await planDownload).suggestedFilename(), 'roomies-room-plan.svg');

    // Confirmation here applies only to this test fixture, never the user's sample.
    await page.locator('#room-settings-top').click();
    await field('#room-settings-form', 'confirmed').check();
    await field('#room-settings-form', 'wall_color').fill('#807060');
    await field('#room-settings-form', 'floor_color').fill('#fff0dd');
    await field('#room-settings-form', 'notes').fill('Disposable browser test room.');
    await page.locator('#room-settings-form button[type="submit"]').click();
    await page.locator('#room-dialog').waitFor({ state: 'hidden' });
    assert.equal((await state()).room.is_demo, false);
    assert.equal((await state()).room.floor_color, '#fff0dd');

    await page.locator('.navigation .nav-link[data-view="wishlist"]').click();
    await page.locator('#add-product').click();
    for (const [name, value] of Object.entries({ name: 'Browser test desk', url: 'https://example.com/desk', target_price: '80', width_cm: '100', depth_cm: '50', height_cm: '73', color: 'Oak', variant: '100 × 50 cm, oak' })) {
      await field('#product-form', name).fill(value);
    }
    await field('#product-form', 'item_id').selectOption('desk');
    if (await field('#product-form', 'sku').count()) await field('#product-form', 'sku').fill('TEST-DESK-01');
    await field('#product-form', 'variant_confirmed').check();
    await field('#product-form', 'monitor').check();
    await page.locator('#product-form button[type="submit"]').click();
    await page.locator('#product-dialog').waitFor({ state: 'hidden' });
    current = await state();
    assert.equal(current.products.length, 1);
    assert.equal(current.products[0].evaluation.fit, 'pass');
    assert.equal(current.tracker.background_running, false);

    async function quote(price, shipping, minuteOffset) {
      await page.getByRole('button', { name: '+ Record price', exact: true }).click();
      const when = new Date(Date.now() - minuteOffset * 60000);
      const local = new Date(when.getTime() - when.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      await field('#observation-form', 'observed_at').fill(local);
      await field('#observation-form', 'price').fill(String(price));
      await field('#observation-form', 'shipping').fill(shipping === null ? '' : String(shipping));
      await field('#observation-form', 'availability').selectOption('in_stock');
      await field('#observation-form', 'variant_confirmed').check();
      await page.locator('#observation-form button[type="submit"]').click();
      await page.locator('#observation-dialog').waitFor({ state: 'hidden' });
    }
    await quote(90, null, 3);
    assert.equal((await state()).notifications.length, 0);

    await flatWorkflow(page, state, results);
    await page.locator('.navigation .nav-link[data-view="wishlist"]').click();
    await quote(70, 5, 2);
    current = await state();
    assert.equal(current.products[0].evaluation.eligible, true);
    assert.equal(current.products[0].evaluation.delivered_eur, 75);
    assert.equal(current.notifications.at(-1).type, 'target_ready');
    await quote(60, null, 1);
    current = await state();
    assert.equal(current.products[0].evaluation.eligible, false);
    assert.equal(current.products[0].evaluation.delivered_eur, null);
    assert.equal(current.notifications.at(-1).type, 'price_drop_info');

    await page.getByRole('button', { name: 'Details', exact: true }).click();
    await field('#product-form', 'target_price').fill('85');
    await page.locator('#product-form button[type="submit"]').click();
    await page.locator('#product-dialog').waitFor({ state: 'hidden' });
    current = await state();
    assert.equal(current.products[0].observations.length, 3);
    assert.equal(current.products[0].sku, 'TEST-DESK-01');
    assert.equal(current.products[0].target_eur, 85);
    const watch = page.locator('#wishlist-grid .watch-label input');
    await watch.uncheck();
    await page.waitForFunction(() => !document.querySelector('#wishlist-grid .watch-label input').disabled);
    assert.equal((await state()).products[0].monitor, false);
    await watch.check();
    await page.waitForFunction(() => !document.querySelector('#wishlist-grid .watch-label input').disabled);
    assert.equal((await state()).products[0].sku, 'TEST-DESK-01');
    await page.getByRole('button', { name: 'See price history →' }).click();
    await page.locator('#history-body tr').nth(2).waitFor();
    assert.equal(await page.locator('#history-body tr').count(), 3);
    assert.equal(await page.locator('#notification-list .notification-row').count(), 2);
    assert.match(await page.locator('#notification-list').innerText(), /Item price changed/);
    await page.getByRole('button', { name: 'Mark read', exact: true }).first().click();
    assert.equal((await state()).notifications.filter(alert => alert.read).length, 1);

    const csvDownload = page.waitForEvent('download');
    await page.locator('#export-prices').click();
    const csv = await csvDownload;
    await csv.saveAs(path.join(results, 'prices.csv'));
    assert.match(await fs.readFile(path.join(results, 'prices.csv'), 'utf8'), /Browser test desk/);
    await page.locator('#data-menu-top').click();
    const backupDownload = page.waitForEvent('download');
    await page.locator('a[href="/api/export?format=json"]').click();
    const backup = await backupDownload;
    const backupPath = path.join(results, 'workspace.json');
    await backup.saveAs(backupPath);
    const exported = JSON.parse(await fs.readFile(backupPath, 'utf8'));
    assert.equal(exported.products[0].observations.length, 3);
    assert.equal(exported.room.wall_color, '#807060');
    await page.locator('#import-file').setInputFiles(backupPath);
    await page.locator('#confirm-import').click();
    await page.locator('#data-dialog').waitFor({ state: 'hidden' });
    assert.equal((await state()).products[0].observations.length, 3);
    assert.equal((await state()).notifications.length, 0);

    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      for (const view of ['home', 'room', 'flat', 'kitchen', 'expenses', 'wishlist', 'journal']) {
        if (view === 'journal') await page.locator('#view-wishlist [data-view="journal"]').click();
        else await page.locator(`.navigation .nav-link[data-view="${view}"]`).click();
        const actual = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
        assert(actual.scroll <= actual.client, `${view} overflows at ${width}px: ${JSON.stringify(actual)}`);
      }
      await page.locator('.navigation .nav-link[data-view="expenses"]').click();
      await page.locator('#add-expense').click();
      const saveExpense = page.locator('#expense-form button[type="submit"]');
      await saveExpense.scrollIntoViewIfNeeded();
      const saveBox = await saveExpense.boundingBox();
      assert(saveBox && saveBox.y >= 0 && saveBox.y + saveBox.height <= 844, `Expense save button is reachable at ${width}px`);
      await page.keyboard.press('Escape');
      await page.locator('#data-menu-top').click();
      assert(await page.locator('#data-dialog').isVisible());
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
      await page.locator('#data-dialog .close-dialog').click();
    }
    await page.goto(`${base}/guide`);
    assert.match(await page.locator('body').innerText(), /Roomies/);
    assert.deepEqual(errors, []);
    console.log('PASS: room geometry and editing, product quotes and alerts, flat members and belongings, kitchen checklist, exact shared balances, full backup, guide, and all 320/390px layouts.');
    console.log(`Disposable test evidence: ${path.relative(root, results)}`);
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
