/* Real form interactions against the smoke test's disposable flat. */
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

module.exports = async function costsWorkflow(page, getState, results) {
  const field = (form, name) => page.locator(`${form} [name="${name}"]`);
  const submit = (form) =>
    page.locator(`${form} button[type="submit"]`).click();
  const before = await getState();
  const debt = before.flat_summary.expenses.settlements[0];
  const spending = before.flat_summary.expenses.total_cents;

  await page
    .locator("#settlements-list")
    .getByRole("button", { name: "Record repayment", exact: true })
    .click();
  assert.equal(
    await field("#repayment-form", "from_id").inputValue(),
    debt.from_id,
  );
  assert.equal(
    await field("#repayment-form", "to_id").inputValue(),
    debt.to_id,
  );
  await field("#repayment-form", "amount").fill("4.00");
  await field("#repayment-form", "confirmed").check();
  await submit("#repayment-form");
  await page.locator("#repayment-dialog").waitFor({ state: "hidden" });
  let current = await getState();
  assert.equal(
    current.flat_summary.expenses.settlements[0].amount_cents,
    debt.amount_cents - 400,
  );
  assert.equal(current.flat_summary.expenses.total_cents, spending);
  const paymentId = current.flat.repayments[0].id;
  await page
    .locator(`[data-repayment-id="${paymentId}"]`)
    .getByRole("button", { name: "Edit", exact: true })
    .click();
  await field("#repayment-form", "amount").fill("4.25");
  await submit("#repayment-form");
  await page.locator("#repayment-dialog").waitFor({ state: "hidden" });
  assert.equal(
    (await getState()).flat_summary.expenses.settlements[0].amount_cents,
    debt.amount_cents - 425,
  );
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .locator(`[data-repayment-id="${paymentId}"]`)
    .getByRole("button", { name: "Remove", exact: true })
    .click();
  await page
    .locator(`[data-repayment-id="${paymentId}"]`)
    .waitFor({ state: "detached" });
  assert.deepEqual((await getState()).flat_summary.expenses.settlements, [
    debt,
  ]);

  await page
    .locator("#settlements-list")
    .getByRole("button", { name: "Record repayment", exact: true })
    .click();
  await field("#repayment-form", "confirmed").check();
  await submit("#repayment-form");
  await page.locator("#repayment-dialog").waitFor({ state: "hidden" });
  assert.deepEqual((await getState()).flat_summary.expenses.settlements, []);
  assert.match(await page.locator("#settlements-list").innerText(), /balanced/);
  const downloaded = page.waitForEvent("download");
  await page.locator("#export-repayments").click();
  const csvPath = path.join(results, "repayments.csv");
  const csv = await downloaded;
  assert.equal(csv.suggestedFilename(), "roomies-repayments.csv");
  await csv.saveAs(csvPath);
  assert.match(await fs.readFile(csvPath, "utf8"), /sender_name/);
  assert.match(
    await fs.readFile(csvPath, "utf8"),
    new RegExp(String(debt.amount_cents)),
  );

  await page.locator("#monthly-bills-panel > summary").click();
  await page.locator("#add-monthly-bill").click();
  await field("#monthly-bill-form", "title").fill("Test internet");
  await field("#monthly-bill-form", "amount").fill("30.01");
  await field("#monthly-bill-form", "due_day").fill("31");
  await field("#monthly-bill-form", "paid_by").selectOption(debt.to_id);
  await field("#monthly-bill-form", "category").selectOption("utilities");
  await submit("#monthly-bill-form");
  await page.locator("#monthly-bill-dialog").waitFor({ state: "hidden" });
  current = await getState();
  assert.equal(current.flat_summary.expenses.total_cents, spending);
  assert.equal(current.flat.expenses.length, before.flat.expenses.length);
  const bill = current.flat.monthly_bills[0];
  const status = current.flat_summary.monthly_bills[0];
  const billRow = page.locator(`[data-monthly-bill-id="${bill.id}"]`);
  await billRow
    .getByRole("button", { name: "Record paid bill", exact: true })
    .click();
  assert.equal(await field("#expense-form", "amount").inputValue(), "30.01");
  assert.equal(
    await field("#expense-form", "date").inputValue(),
    status.due_date,
  );
  await submit("#expense-form");
  await page.locator("#expense-dialog").waitFor({ state: "hidden" });
  current = await getState();
  assert.equal(current.flat_summary.expenses.total_cents, spending + 3001);
  assert.equal(current.flat.expenses.at(-1).bill_id, bill.id);
  assert.equal(
    current.flat.expenses.at(-1).bill_month,
    status.due_date.slice(0, 7),
  );
  assert(
    await billRow
      .getByRole("button", { name: "Recorded this month", exact: true })
      .isDisabled(),
  );

  await billRow.getByRole("button", { name: "Edit", exact: true }).click();
  await field("#monthly-bill-form", "amount").fill("32.00");
  await submit("#monthly-bill-form");
  await page.locator("#monthly-bill-dialog").waitFor({ state: "hidden" });
  current = await getState();
  assert.equal(current.flat.monthly_bills[0].amount_cents, 3200);
  assert.equal(current.flat.expenses.at(-1).amount_cents, 3001);
  await billRow.getByRole("button", { name: "Pause", exact: true }).click();
  await billRow.getByRole("button", { name: "Resume", exact: true }).waitFor();
  assert.equal((await getState()).flat.monthly_bills[0].active, false);
  await billRow.getByRole("button", { name: "Resume", exact: true }).click();
  await billRow.getByRole("button", { name: "Pause", exact: true }).waitFor();

  await page.locator("#data-menu-top").click();
  const backupDownload = page.waitForEvent("download");
  await page.locator('a[href="/api/export?format=json"]').click();
  const backupPath = path.join(results, "finished-ledger.json");
  await (await backupDownload).saveAs(backupPath);
  const backup = JSON.parse(await fs.readFile(backupPath, "utf8"));
  assert.equal(backup.flat.repayments.length, 1);
  assert.equal(backup.flat.monthly_bills.length, 1);
  await page.locator("#import-file").setInputFiles(backupPath);
  await page.locator("#confirm-import").click();
  await page.locator("#data-dialog").waitFor({ state: "hidden" });
  assert.deepEqual((await getState()).flat, backup.flat);
};
