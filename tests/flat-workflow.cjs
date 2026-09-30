/* Household checks reuse the disposable local server from browser-smoke.cjs. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

module.exports = async function flatWorkflow(page, getState, results) {
  const field = (form, name) => page.locator(`${form} [name="${name}"]`);
  const navigate = view => page.locator(`.navigation .nav-link[data-view="${view}"]`).click();
  const submit = form => page.locator(`${form} button[type="submit"]`).click();
  await navigate('flat');
  await page.locator('#flat-settings-button').click();
  await field('#flat-settings-form', 'name').fill('Browser test flat');
  await field('#flat-settings-form', 'confirmed').check();
  await page.locator('#flat-members-editor input').first().fill('Alice');
  await page.locator('#add-flat-member').click();
  await page.locator('#flat-members-editor input').last().fill('Bob');
  await submit('#flat-settings-form');
  await page.locator('#flat-dialog').waitFor({ state: 'hidden' });
  let current = await getState();
  const alice = current.flat.members.find(member => member.name === 'Alice').id;
  const bob = current.flat.members.find(member => member.name === 'Bob').id;
  assert.equal(current.flat.is_demo, false);
  assert.equal(current.flat.members.length, 2);

  await page.locator('#add-flat-item').click();
  for (const [name, value] of Object.entries({ name: 'Test kettle', category: 'kitchen', location: 'Kitchen', spot: 'Worktop beside the sink', quantity: '1' })) {
    await field('#flat-item-form', name).fill(value);
  }
  await field('#flat-item-form', 'owner_id').selectOption(alice);
  await submit('#flat-item-form');
  await page.locator('#flat-item-dialog').waitFor({ state: 'hidden' });
  current = await getState();
  assert.equal(current.flat.inventory[0].spot, 'Worktop beside the sink');
  assert.equal(current.flat.inventory[0].owner_id, alice);
  const kettleId = current.flat.inventory[0].id;
  assert.match(await page.locator('#flat-inventory').innerText(), /Worktop beside the sink/);
  await page.locator('#flat-search').fill('nothing matches this phrase');
  assert.doesNotMatch(await page.locator('#flat-inventory').innerText(), /Test kettle/);
  await page.locator('#flat-search').fill('kettle');
  assert.match(await page.locator('#flat-inventory').innerText(), /Test kettle/);
  await page.locator('#flat-search').fill('');
  await page.locator(`#flat-inventory [data-flat-item-id="${kettleId}"]`).getByRole('button', { name: 'Edit', exact: true }).click();
  await field('#flat-item-form', 'spot').fill('Lower cupboard');
  await submit('#flat-item-form');
  await page.locator('#flat-item-dialog').waitFor({ state: 'hidden' });
  assert.equal((await getState()).flat.inventory[0].spot, 'Lower cupboard');

  // Hold an old background read until after a new write has completed.
  // The screen and the next write must keep the accepted change.
  const stateUrl = `${new URL(page.url()).origin}/api/state`;
  let releaseRead;
  let readCaptured;
  const captured = new Promise(resolve => { readCaptured = resolve; });
  const released = new Promise(resolve => { releaseRead = resolve; });
  let holdNext = true;
  const holdOldRead = async route => {
    if (!holdNext) return route.continue();
    holdNext = false;
    const response = await route.fetch();
    const body = await response.body();
    readCaptured();
    await released;
    await route.fulfill({ response, body });
  };
  await page.route(stateUrl, holdOldRead);
  await page.evaluate(() => { window.heldFlatPoll = pollWorkspace(); });
  await captured;
  await page.locator(`#flat-inventory [data-flat-item-id="${kettleId}"]`).getByRole('button', { name: 'Edit', exact: true }).click();
  await field('#flat-item-form', 'spot').fill('Upper cupboard');
  await submit('#flat-item-form');
  await page.locator('#flat-item-dialog').waitFor({ state: 'hidden' });
  releaseRead();
  await page.evaluate(() => window.heldFlatPoll);
  await page.unroute(stateUrl, holdOldRead);
  assert.match(await page.locator('#flat-inventory').innerText(), /Upper cupboard/);
  assert.equal((await getState()).flat.inventory[0].spot, 'Upper cupboard');

  await page.locator('#flat-settings-button').click();
  await page.getByRole('button', { name: 'Remove Alice', exact: true }).click();
  assert.match(await page.locator('#flat-settings-error').innerText(), /referenced/);
  assert.equal(await page.locator('#flat-members-editor input').count(), 2);
  await page.getByRole('button', { name: 'Close flat settings', exact: true }).click();

  await navigate('kitchen');
  assert.match(await page.locator('#kitchen-inventory').innerText(), /Test kettle/);
  await page.locator('#add-fridge-item').click();
  await field('#fridge-form', 'name').fill('Test milk');
  await field('#fridge-form', 'quantity').fill('One carton');
  await field('#fridge-form', 'storage').selectOption('fridge');
  await field('#fridge-form', 'status').selectOption('low');
  await page.locator('#fridge-form details summary').click();
  await field('#fridge-form', 'best_before').fill('2030-01-01');
  await submit('#fridge-form');
  await page.locator('#fridge-dialog').waitFor({ state: 'hidden' });
  current = await getState();
  const milkId = current.flat.fridge[0].id;
  assert.equal(current.flat.fridge[0].status, 'low');
  assert.match(await page.locator('#shopping-list').innerText(), /Test milk/);
  assert.equal(await page.locator(`#fridge-list [data-fridge-id="${milkId}"]`).count(), 1);
  await page.locator('#shopping-list').getByRole('button', { name: 'Restocked', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#shopping-count').textContent === '0');
  assert.equal((await getState()).flat.fridge[0].status, 'stocked');
  assert.doesNotMatch(await page.locator('#shopping-list').innerText(), /Test milk/);

  await navigate('expenses');
  async function addExpense(title, amount, payer) {
    await page.locator('#add-expense').click();
    await field('#expense-form', 'title').fill(title);
    await field('#expense-form', 'amount').fill(amount);
    await field('#expense-form', 'paid_by').selectOption(payer);
    for (const person of [alice, bob]) {
      await page.locator(`#expense-participants input[value="${person}"]`).check();
    }
    await submit('#expense-form');
    await page.locator('#expense-dialog').waitFor({ state: 'hidden' });
  }
  await addExpense('Test groceries', '30.00', alice);
  current = await getState();
  assert.equal(current.flat.expenses[0].amount_cents, 3000);
  assert.deepEqual(current.flat_summary.expenses.settlements, [{ from_id: bob, to_id: alice, amount_cents: 1500 }]);
  await addExpense('Test household supplies', '12.00', bob);
  current = await getState();
  assert.equal(current.flat_summary.expenses.total_cents, 4200);
  assert.deepEqual(current.flat_summary.expenses.settlements, [{ from_id: bob, to_id: alice, amount_cents: 900 }]);
  assert.equal(current.flat_summary.expenses.balances.reduce((total, person) => total + person.balance_cents, 0), 0);
  assert.match(await page.locator('#settlements-list').innerText(), /Bob/);
  assert.match(await page.locator('#settlements-list').innerText(), /Alice/);

  const supplies = current.flat.expenses.find(expense => expense.title === 'Test household supplies');
  await page.locator(`#expense-list [data-expense-id="${supplies.id}"]`).getByRole('button', { name: 'Edit', exact: true }).click();
  await field('#expense-form', 'amount').fill('10.50');
  await submit('#expense-form');
  await page.locator('#expense-dialog').waitFor({ state: 'hidden' });
  assert.deepEqual((await getState()).flat_summary.expenses.settlements, [{ from_id: bob, to_id: alice, amount_cents: 975 }]);
  page.once('dialog', dialog => dialog.accept());
  await page.locator(`#expense-list [data-expense-id="${supplies.id}"]`).getByRole('button', { name: 'Remove', exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('#expense-list [data-expense-id]').length === 1);
  assert.deepEqual((await getState()).flat_summary.expenses.settlements, [{ from_id: bob, to_id: alice, amount_cents: 1500 }]);
  await addExpense('Test household supplies', '12.00', bob);

  const csvDownload = page.waitForEvent('download');
  await page.locator('#export-expenses').click();
  const csv = await csvDownload;
  const csvPath = path.join(results, 'expense-shares.csv');
  await csv.saveAs(csvPath);
  assert.match(await fs.readFile(csvPath, 'utf8'), /share_cents/);
  assert.match(await fs.readFile(csvPath, 'utf8'), /Test groceries/);

  // A current workspace backup must include the new base, not only the old room.
  await page.locator('#data-menu-top').click();
  const downloaded = page.waitForEvent('download');
  await page.locator('a[href="/api/export?format=json"]').click();
  const backup = await downloaded;
  const backupPath = path.join(results, 'flat-workspace.json');
  await backup.saveAs(backupPath);
  const exported = JSON.parse(await fs.readFile(backupPath, 'utf8'));
  assert.equal(exported.schema_version, 2);
  assert.equal(exported.flat.inventory[0].spot, 'Upper cupboard');
  assert.equal(exported.flat.fridge[0].best_before, '2030-01-01');
  assert.equal(exported.flat.expenses.length, 2);
  await page.getByRole('button', { name: 'Close data controls', exact: true }).click();

  // A restore waits for a checklist write already in flight. Otherwise the
  // old PUT could arrive last and silently replace the restored flat.
  const flatUrl = `${new URL(page.url()).origin}/api/flat`;
  let releaseWrite;
  let writeCaptured;
  const pendingWrite = new Promise(resolve => { writeCaptured = resolve; });
  const writeReleased = new Promise(resolve => { releaseWrite = resolve; });
  const holdWrite = async route => {
    writeCaptured();
    await writeReleased;
    await route.continue();
  };
  let importRequests = 0;
  const countImports = request => {
    if (new URL(request.url()).pathname === '/api/import') importRequests++;
  };
  await page.route(flatUrl, holdWrite);
  page.on('request', countImports);
  await navigate('kitchen');
  await page.locator(`#fridge-list [data-fridge-id="${milkId}"]`).getByRole('button', { name: 'Mark low', exact: true }).click();
  await pendingWrite;
  await page.locator('#data-menu-top').click();
  await page.locator('#import-file').setInputFiles(backupPath);
  await page.locator('#confirm-import').click();
  await page.waitForTimeout(300);
  const restoreWaited = importRequests === 0;
  releaseWrite();
  assert(restoreWaited, 'Import must wait for the pending flat write');
  await page.locator('#data-dialog').waitFor({ state: 'hidden' });
  await page.unroute(flatUrl, holdWrite);
  page.off('request', countImports);
  assert.equal(importRequests, 1);
  assert.deepEqual((await getState()).flat, exported.flat);

  // Imported bills can have a saved participant order unlike the member list.
  // Editing only the title must not move the odd-cent share to another person.
  const reordered = JSON.parse(JSON.stringify(exported));
  reordered.flat.expenses[0].amount_cents = 3001;
  reordered.flat.expenses[0].split_between = [bob, alice];
  const reorderedPath = path.join(results, 'reordered-shares.json');
  await fs.writeFile(reorderedPath, JSON.stringify(reordered));
  await page.locator('#data-menu-top').click();
  await page.locator('#import-file').setInputFiles(reorderedPath);
  await page.locator('#confirm-import').click();
  await page.locator('#data-dialog').waitFor({ state: 'hidden' });
  await navigate('expenses');
  const originalSummary = (await getState()).flat_summary.expenses;
  await page.locator(`#expense-list [data-expense-id="${reordered.flat.expenses[0].id}"]`).getByRole('button', { name: 'Edit', exact: true }).click();
  await field('#expense-form', 'title').fill('Test groceries renamed');
  await submit('#expense-form');
  await page.locator('#expense-dialog').waitFor({ state: 'hidden' });
  current = await getState();
  assert.deepEqual(current.flat.expenses[0].split_between, [bob, alice]);
  assert.deepEqual(current.flat_summary.expenses, originalSummary);
  await navigate('home');
  assert.match(await page.locator('#home-flat-name').innerText(), /Browser test flat/);
};
