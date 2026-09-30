/* Repayments are recorded transfers. Monthly bills are reusable details, never automatic charges. */
"use strict";

function fillMemberSelect(select, selected) {
  select.replaceChildren(
    ...state.flat.members.map((person) =>
      node("option", { value: person.id }, person.name),
    ),
  );
  select.value = selected || state.flat.members[0].id;
}

function openRepayment(repaymentId = null, suggestion = null) {
  const form = $("#repayment-form");
  form.reset();
  const saved = state.flat.repayments.find(
    (record) => record.id === repaymentId,
  );
  const payment = saved || suggestion;
  form.elements.id.value = saved?.id || "";
  fillMemberSelect(form.elements.from_id, payment?.from_id);
  fillMemberSelect(
    form.elements.to_id,
    payment?.to_id || state.flat.members[1]?.id,
  );
  form.elements.amount.value = payment
    ? expenseAmountInput(payment.amount_cents)
    : "";
  form.elements.date.value = saved?.date || localDateValue().slice(0, 10);
  form.elements.notes.value = saved?.notes || "";
  form.elements.confirmed.checked = Boolean(saved);
  $("#repayment-dialog-title").textContent = saved
    ? "Edit repayment"
    : "Record a repayment";
  $("#repayment-error").hidden = true;
  $("#repayment-dialog").showModal();
}

function openMonthlyBill(billId = null) {
  const form = $("#monthly-bill-form");
  form.reset();
  const bill = state.flat.monthly_bills.find((record) => record.id === billId);
  form.elements.id.value = bill?.id || "";
  form.elements.title.value = bill?.title || "";
  form.elements.amount.value = bill
    ? expenseAmountInput(bill.amount_cents)
    : "";
  form.elements.due_day.value = bill?.due_day || 1;
  form.elements.category.value = bill?.category || "rent";
  form.elements.active.checked = bill?.active ?? true;
  form.elements.notes.value = bill?.notes || "";
  fillMemberSelect(form.elements.paid_by, bill?.paid_by);
  const order = bill
    ? [
        ...bill.split_between,
        ...state.flat.members
          .map((person) => person.id)
          .filter((id) => !bill.split_between.includes(id)),
      ]
    : state.flat.members.map((person) => person.id);
  $("#monthly-bill-participants").replaceChildren(
    ...order.map((memberId) => {
      const checkbox = node("input", { type: "checkbox", value: memberId });
      checkbox.checked = !bill || bill.split_between.includes(memberId);
      return append(
        node("label"),
        checkbox,
        document.createTextNode(memberName(memberId)),
      );
    }),
  );
  $("#monthly-bill-dialog-title").textContent = bill
    ? "Edit monthly bill"
    : "Save a monthly bill";
  $("#monthly-bill-error").hidden = true;
  $("#monthly-bill-dialog").showModal();
}

async function removeCostRecord(collection, recordId, message) {
  if (!window.confirm(message)) return;
  await updateFlat((flat) => {
    flat[collection] = flat[collection].filter(
      (record) => record.id !== recordId,
    );
  });
  toast("Record removed.");
}

function renderCostExtras() {
  const canRepay = state.flat.members.length > 1;
  $("#add-repayment").disabled = !canRepay;
  $("#add-repayment").title = canRepay
    ? "Record money already paid back"
    : "Add another person in Flat & people first";
  $("#export-repayments").disabled = state.flat.repayments.length === 0;
  const repayments = [...state.flat.repayments].sort((a, b) =>
    b.date.localeCompare(a.date),
  );
  $("#repayment-list").replaceChildren(
    ...(repayments.length
      ? repayments.map((payment) => {
          const content = append(
            node("div", { class: "household-row-main" }),
            node(
              "h3",
              {},
              `${memberName(payment.from_id)} → ${memberName(payment.to_id)}`,
            ),
            node("p", {}, shortDate(payment.date)),
          );
          if (payment.notes) content.append(node("p", {}, payment.notes));
          return append(
            node("div", {
              class: "household-row",
              "data-repayment-id": payment.id,
            }),
            content,
            node(
              "strong",
              { class: "expense-amount" },
              moneyCents(payment.amount_cents),
            ),
            append(
              node("div", { class: "household-row-actions" }),
              recordButton("Edit", () => openRepayment(payment.id)),
              recordButton(
                "Remove",
                () =>
                  removeCostRecord(
                    "repayments",
                    payment.id,
                    "Remove this repayment record? Balances will be recalculated.",
                  ),
                "quiet-button",
              ),
            ),
          );
        })
      : [
          emptyRecord(
            "Nothing paid back yet.",
            canRepay
              ? "Record a repayment after the money has changed hands."
              : "Add the people in your flat to start sharing costs.",
          ),
        ]),
  );

  $("#monthly-bill-count").textContent = String(
    state.flat.monthly_bills.length,
  );
  $("#monthly-bill-list").replaceChildren(
    ...(state.flat.monthly_bills.length
      ? state.flat.monthly_bills.map((bill) => {
          const status = state.flat_summary.monthly_bills.find(
            (entry) => entry.bill_id === bill.id,
          );
          const content = append(
            node("div", { class: "household-row-main" }),
            node("h3", {}, bill.title),
            node(
              "p",
              {},
              `${moneyCents(bill.amount_cents)} · ${memberName(bill.paid_by)} usually pays`,
            ),
            node(
              "p",
              {},
              bill.active
                ? `This month: ${shortDate(status.due_date)}${status.expense_id ? " · Recorded" : " · Not recorded"}`
                : "Paused",
            ),
          );
          const record = recordButton("Record paid bill", () =>
            openExpense(null, {
              ...bill,
              bill_id: bill.id,
              date: status.due_date,
            }),
          );
          record.disabled = !bill.active || Boolean(status.expense_id);
          if (status.expense_id) record.textContent = "Recorded this month";
          return append(
            node("div", {
              class: "household-row",
              "data-monthly-bill-id": bill.id,
            }),
            content,
            append(
              node("div", { class: "household-row-actions" }),
              record,
              recordButton("Edit", () => openMonthlyBill(bill.id)),
              recordButton(bill.active ? "Pause" : "Resume", async () => {
                await updateFlat((flat) => {
                  const entry = flat.monthly_bills.find(
                    (entry) => entry.id === bill.id,
                  );
                  entry.active = !entry.active;
                });
              }),
              recordButton(
                "Remove",
                () =>
                  removeCostRecord(
                    "monthly_bills",
                    bill.id,
                    `Remove the saved details for “${bill.title}”? Recorded expenses will stay.`,
                  ),
                "quiet-button",
              ),
            ),
          );
        })
      : [
          emptyRecord(
            "Save rent, internet or another monthly bill.",
            "Nothing is added to your spending until you record a paid bill.",
          ),
        ]),
  );
}

async function saveCostRecord(event, collection) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  const repayment = collection === "repayments";
  const errorId = repayment ? "#repayment-error" : "#monthly-bill-error";
  const button = $("button[type=submit]", form);
  button.disabled = true;
  $(errorId).hidden = true;
  try {
    let record = {
      id: formValue(form, "id") || id(repayment ? "repayment" : "monthly"),
      amount_cents: eurosToCents(formValue(form, "amount")),
      notes: formValue(form, "notes"),
    };
    if (repayment) {
      record = {
        ...record,
        from_id: formValue(form, "from_id"),
        to_id: formValue(form, "to_id"),
        date: formValue(form, "date"),
      };
      if (record.from_id === record.to_id)
        throw new Error("Choose two different people.");
    } else {
      const participants = $$("#monthly-bill-participants input:checked").map(
        (input) => input.value,
      );
      if (!participants.length)
        throw new Error("Choose at least one person who shares this bill.");
      record = {
        ...record,
        title: formValue(form, "title"),
        paid_by: formValue(form, "paid_by"),
        split_between: participants,
        category: formValue(form, "category"),
        due_day: Number(formValue(form, "due_day")),
        active: form.elements.active.checked,
      };
    }
    await updateFlat((flat) => {
      const position = flat[collection].findIndex(
        (entry) => entry.id === record.id,
      );
      if (position < 0) flat[collection].push(record);
      else flat[collection][position] = record;
    });
    form.closest("dialog").close();
    toast(
      repayment
        ? "Repayment saved. Balances updated."
        : "Monthly bill saved. Record it when paid.",
    );
  } catch (error) {
    flatError(errorId, error);
  } finally {
    button.disabled = false;
  }
}

function wireCostEvents() {
  $("#add-repayment").addEventListener("click", () => openRepayment());
  $("#add-monthly-bill").addEventListener("click", () => openMonthlyBill());
  $("#export-repayments").addEventListener("click", () =>
    downloadData("/api/export?format=repayments"),
  );
  $("#repayment-form").addEventListener("submit", (event) =>
    saveCostRecord(event, "repayments"),
  );
  $("#monthly-bill-form").addEventListener("submit", (event) =>
    saveCostRecord(event, "monthly_bills"),
  );
}
