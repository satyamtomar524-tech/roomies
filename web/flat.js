/* Flat records are saved separately from the measured room. Money is entered as integer cents. */
"use strict";

let flatSavingPromise = null;
let flatRevision = 0;
let flatMembersDraft = [];

async function flushFlat() {
  while (flatSavingPromise) await flatSavingPromise;
}

function ensureHousehold() {
  state.flat ||= {
    name: "My flat",
    is_demo: true,
    members: [{ id: "me", name: "Me" }],
    inventory: [],
    fridge: [],
    expenses: [],
  };
  state.flat_summary ||= {
    inventory_count: 0,
    inventory_quantity: 0,
    locations: [],
    fridge_count: 0,
    fridge_counts: { stocked: 0, low: 0, out: 0 },
    expenses: { total_cents: 0, balances: [], settlements: [] },
  };
}

function memberName(memberId) {
  return memberId
    ? state.flat.members.find((person) => person.id === memberId)?.name ||
        "Missing person"
    : "Shared";
}

function moneyCents(cents) {
  return euro.format((cents || 0) / 100);
}

function eurosToCents(text) {
  const match = String(text)
    .trim()
    .match(/^(\d+)(?:[.,](\d{1,2}))?$/);
  if (!match)
    throw new Error(
      "Enter an amount such as 24.50, with no more than two decimal places.",
    );
  const cents =
    Number(match[1]) * 100 + Number((match[2] || "").padEnd(2, "0"));
  if (!Number.isSafeInteger(cents) || cents < 1 || cents > 100000000)
    throw new Error("The amount must be between €0.01 and €1,000,000.");
  return cents;
}

function expenseAmountInput(cents) {
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
}

function shortDate(value) {
  if (!value) return "";
  return new Date(`${value}T12:00:00`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function flatError(selector, error) {
  const box = $(selector);
  box.textContent = error.message;
  box.hidden = false;
}

function recordButton(label, action, klass = "small-button") {
  const button = node("button", { type: "button", class: klass }, label);
  button.addEventListener("click", async () => {
    try {
      await action(button);
    } catch (error) {
      toast(error.message, true);
    }
  });
  return button;
}

async function updateFlat(mutate) {
  // Serialize whole-flat writes so two quick checklist actions cannot replace one another.
  while (flatSavingPromise) await flatSavingPromise;
  const candidate = JSON.parse(JSON.stringify(state.flat));
  mutate(candidate);
  setSaveStatus("Saving flat changes…", "saving");
  const operation = (async () => {
    const result = await api("/api/flat", {
      method: "PUT",
      body: JSON.stringify(candidate),
    });
    flatRevision += 1;
    state.flat = result.flat;
    state.flat_summary = result.flat_summary;
    renderHousehold();
    if (savedRevision === mutationRevision)
      setSaveStatus("All changes saved locally");
    return result;
  })();
  flatSavingPromise = operation;
  try {
    return await operation;
  } catch (error) {
    setSaveStatus("Flat changes not saved · try again", "error");
    throw error;
  } finally {
    if (flatSavingPromise === operation) flatSavingPromise = null;
  }
}

function metricCard(label, value, caption = "") {
  return append(
    node("div", { class: "mini-metric" }),
    node("span", {}, label),
    node("strong", {}, value),
    node("small", {}, caption),
  );
}

function emptyRecord(title, copy) {
  return append(
    node("div", { class: "empty-inline" }),
    node("strong", {}, title),
    node("p", {}, copy),
  );
}

function overviewCard(label, text, view, icon, indigo = false) {
  const card = node("button", {
    type: "button",
    class: `overview-card${indigo ? " indigo" : ""}`,
  });
  append(
    card,
    node("span", { class: "card-icon", "aria-hidden": "true" }, icon),
    node("span", { class: "card-arrow", "aria-hidden": "true" }, "↗"),
    node("strong", {}, label),
    node("p", {}, text),
  );
  card.addEventListener("click", () => showView(view));
  return card;
}

function nextAction(title, copy, action, icon = "→") {
  const button = node("button", { type: "button", class: "action-row" });
  append(
    button,
    node("span", { class: "action-icon", "aria-hidden": "true" }, icon),
    append(node("div"), node("strong", {}, title), node("small", {}, copy)),
    node("span", { "aria-hidden": "true" }, "→"),
  );
  button.addEventListener("click", action);
  return button;
}

function renderHome() {
  const flat = state.flat;
  const owned = state.room.items.filter(
    (item) => item.status === "owned",
  ).length;
  const planned = state.room.items.filter(
    (item) => item.status === "planned",
  ).length;
  const shopping = flat.fridge.filter((item) => item.status !== "stocked");
  $("#home-date").textContent = new Date().toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  $("#home-flat-name").textContent = flat.name;
  $("#home-overview").replaceChildren(
    overviewCard(
      "My room",
      `${owned} owned · ${planned} planned${state.room.is_demo ? " · sample plan" : ""}`,
      "room",
      "▦",
    ),
    overviewCard(
      "My flat",
      `${flat.inventory.length} ${flat.inventory.length === 1 ? "thing" : "things"} · ${flat.members.length} ${flat.members.length === 1 ? "person" : "people"}`,
      "flat",
      "▤",
    ),
    overviewCard(
      "Kitchen",
      `${shopping.length} ${shopping.length === 1 ? "item" : "items"} marked low or out`,
      "kitchen",
      "◫",
      true,
    ),
    overviewCard(
      "Shared costs",
      `${flat.expenses.length} ${flat.expenses.length === 1 ? "bill" : "bills"} · ${moneyCents(state.flat_summary.expenses?.total_cents)} recorded`,
      "expenses",
      "€",
      true,
    ),
  );
  const actions = [];
  if (state.room.is_demo)
    actions.push(
      nextAction(
        "Start with your measurements",
        "Replace the example room with your actual walls and openings.",
        openRoomSettings,
        "▦",
      ),
    );
  else
    actions.push(
      nextAction(
        "Arrange your room",
        "Check positions and keep space for what comes next.",
        () => showView("room"),
        "▦",
      ),
    );
  if (flat.is_demo || flat.members.length === 1)
    actions.push(
      nextAction(
        "Make the flat yours",
        "Name your flat and add the people you share it with.",
        openFlatSettings,
        "▤",
      ),
    );
  else
    actions.push(
      nextAction(
        "Find something in the flat",
        "Search by item, location or the exact spot.",
        () => showView("flat"),
        "▤",
      ),
    );
  if (shopping.length)
    actions.push(
      nextAction(
        `Check ${shopping.length} shopping-list ${shopping.length === 1 ? "item" : "items"}`,
        "Your kitchen checklist says these are running low or out.",
        () => showView("kitchen"),
        "◫",
      ),
    );
  else
    actions.push(
      nextAction(
        "Keep a kitchen checklist",
        "Record the staples you want to keep an eye on.",
        () => showView("kitchen"),
        "◫",
      ),
    );
  $("#home-next").replaceChildren(...actions);
}

function fillOwnerSelect(select, selected = "") {
  select.replaceChildren(
    node("option", { value: "" }, "Shared / everyone"),
    ...state.flat.members.map((person) =>
      node("option", { value: person.id }, person.name),
    ),
  );
  select.value = selected || "";
}

function refreshFlatFilters() {
  const location = $("#flat-location-filter"),
    oldLocation = location.value;
  const places = [
    ...new Set(state.flat.inventory.map((item) => item.location)),
  ].sort((a, b) => a.localeCompare(b));
  location.replaceChildren(
    node("option", { value: "" }, "Everywhere"),
    ...places.map((place) => node("option", { value: place }, place)),
  );
  location.value = places.includes(oldLocation) ? oldLocation : "";
  const owner = $("#flat-owner-filter"),
    oldOwner = owner.value;
  owner.replaceChildren(
    node("option", { value: "" }, "Everyone"),
    node("option", { value: "shared" }, "Shared items"),
    ...state.flat.members.map((person) =>
      node("option", { value: person.id }, person.name),
    ),
  );
  owner.value = [...owner.options].some((option) => option.value === oldOwner)
    ? oldOwner
    : "";
  $("#flat-locations").replaceChildren(
    ...places.map((place) => node("option", { value: place })),
  );
}

function inventoryRecord(item, compact = false) {
  const row = node("div", {
    class: "household-row",
    "data-flat-item-id": item.id,
    role: "group",
    "aria-label": item.name,
  });
  const content = append(
    node("div", { class: "household-row-main" }),
    node("h3", {}, item.name),
    node(
      "p",
      { class: "where-line" },
      `${item.location}${item.spot ? ` · ${item.spot}` : ""}`,
    ),
    node(
      "p",
      {},
      `${memberName(item.owner_id)} · ${item.quantity} ${item.quantity === 1 ? "item" : "items"}${compact ? "" : ` · ${item.category}`}`,
    ),
  );
  if (item.notes && !compact) content.append(node("p", {}, item.notes));
  const actions = append(
    node("div", { class: "household-row-actions" }),
    recordButton("Edit", () => openFlatItem(item.id)),
    recordButton(
      "Remove",
      async (button) => {
        if (!window.confirm(`Remove “${item.name}” from the flat list?`))
          return;
        button.disabled = true;
        try {
          await updateFlat((flat) => {
            flat.inventory = flat.inventory.filter(
              (record) => record.id !== item.id,
            );
          });
          toast("Thing removed from the flat list.");
        } finally {
          button.disabled = false;
        }
      },
      "quiet-button",
    ),
  );
  return append(
    row,
    node("span", { class: "row-symbol", "aria-hidden": "true" }, "▣"),
    content,
    actions,
  );
}

function renderFlatInventory() {
  if (!state?.flat) return;
  const flat = state.flat;
  const search = $("#flat-search").value.trim().toLocaleLowerCase();
  const location = $("#flat-location-filter").value,
    owner = $("#flat-owner-filter").value;
  const filtered = flat.inventory.filter(
    (item) =>
      (!search ||
        [
          item.name,
          item.location,
          item.spot,
          item.category,
          memberName(item.owner_id),
        ]
          .join(" ")
          .toLocaleLowerCase()
          .includes(search)) &&
      (!location || item.location === location) &&
      (!owner ||
        (owner === "shared" ? !item.owner_id : item.owner_id === owner)),
  );
  $("#flat-list-caption").textContent =
    `${filtered.length} of ${flat.inventory.length} ${flat.inventory.length === 1 ? "thing" : "things"} shown`;
  $("#flat-inventory").replaceChildren(
    ...(filtered.length
      ? filtered.map((item) => inventoryRecord(item))
      : [
          emptyRecord(
            flat.inventory.length
              ? "No things match this search."
              : "Start with one thing.",
            flat.inventory.length
              ? "Try another location or search term."
              : "Add a belonging and the spot where you keep it.",
          ),
        ]),
  );
}

function renderFlat() {
  $("#flat-sample-note").hidden = !state.flat.is_demo;
  const places = new Set(state.flat.inventory.map((item) => item.location));
  $("#flat-summary").replaceChildren(
    metricCard(
      "Things recorded",
      String(state.flat.inventory.length),
      "distinct entries",
    ),
    metricCard(
      "Total quantity",
      String(state.flat_summary.inventory_quantity ?? 0),
      "across flat belongings",
    ),
    metricCard("Locations", String(places.size), "where things live"),
    metricCard("People", String(state.flat.members.length), state.flat.name),
  );
  refreshFlatFilters();
  renderFlatInventory();
}

function stockLabel(status) {
  return { stocked: "Stocked", low: "Running low", out: "Out" }[status];
}

async function setStock(itemId, status) {
  await updateFlat((flat) => {
    const item = flat.fridge.find((record) => record.id === itemId);
    if (!item) throw new Error("This checklist item no longer exists.");
    item.status = status;
  });
  toast(`Checklist updated: ${stockLabel(status).toLowerCase()}.`);
}

function fridgeRecord(item) {
  const row = node("div", {
    class: "household-row",
    "data-fridge-id": item.id,
    role: "group",
    "aria-label": item.name,
  });
  const content = append(
    node("div", { class: "household-row-main" }),
    node("h3", {}, item.name),
    node(
      "p",
      {},
      `${item.storage[0].toUpperCase()}${item.storage.slice(1)}${item.quantity ? ` · ${item.quantity}` : ""} · ${memberName(item.owner_id)}`,
    ),
  );
  const details = node("div", { class: "row-details" });
  details.append(
    node(
      "span",
      { class: `stock-pill ${item.status}` },
      stockLabel(item.status),
    ),
  );
  if (item.best_before) {
    const past = item.best_before < localDateValue().slice(0, 10);
    details.append(
      node(
        "span",
        { class: `planning-tag${past ? " past" : ""}` },
        `${past ? "Date passed · " : "Planning date · "}${shortDate(item.best_before)}`,
      ),
    );
  }
  content.append(details);
  if (item.notes) content.append(node("p", {}, item.notes));
  const actions = node("div", { class: "household-row-actions" });
  const nextStatus = { stocked: "low", low: "out", out: "stocked" }[
    item.status
  ];
  actions.append(
    recordButton(
      { stocked: "Mark low", low: "Mark out", out: "Restocked" }[item.status],
      async (button) => {
        button.disabled = true;
        try {
          await setStock(item.id, nextStatus);
        } finally {
          button.disabled = false;
        }
      },
    ),
  );
  actions.append(
    recordButton("Edit", () => openFridgeItem(item.id), "quiet-button"),
  );
  actions.append(
    recordButton(
      "Remove",
      async (button) => {
        if (
          !window.confirm(`Remove “${item.name}” from the kitchen checklist?`)
        )
          return;
        button.disabled = true;
        try {
          await updateFlat((flat) => {
            flat.fridge = flat.fridge.filter((record) => record.id !== item.id);
          });
          toast("Checklist item removed.");
        } finally {
          button.disabled = false;
        }
      },
      "quiet-button",
    ),
  );
  return append(
    row,
    node("span", { class: "row-symbol", "aria-hidden": "true" }, "◫"),
    content,
    actions,
  );
}

function renderKitchen() {
  if (!state?.flat) return;
  const storage = $("#fridge-storage-filter").value,
    status = $("#fridge-status-filter").value;
  const items = state.flat.fridge.filter(
    (item) =>
      (!storage || item.storage === storage) &&
      (!status || item.status === status),
  );
  $("#fridge-list").replaceChildren(
    ...(items.length
      ? items.map(fridgeRecord)
      : [
          emptyRecord(
            state.flat.fridge.length
              ? "Nothing matches these filters."
              : "Your kitchen checklist starts here.",
            state.flat.fridge.length
              ? "Choose another storage or stock status."
              : "Add the food and staples you want to track.",
          ),
        ]),
  );
  const shopping = state.flat.fridge.filter(
    (item) => item.status === "low" || item.status === "out",
  );
  $("#shopping-count").textContent = String(shopping.length);
  $("#shopping-list").replaceChildren(
    ...(shopping.length
      ? shopping.map((item) => {
          const row = node("div", { class: "shopping-row" });
          append(
            row,
            append(
              node("div"),
              node("strong", {}, item.name),
              node(
                "small",
                {},
                `${stockLabel(item.status)} · ${memberName(item.owner_id)}`,
              ),
            ),
            recordButton("Restocked", async (button) => {
              button.disabled = true;
              try {
                await setStock(item.id, "stocked");
              } finally {
                button.disabled = false;
              }
            }),
          );
          return row;
        })
      : [
          emptyRecord(
            "Nothing marked low or out.",
            "The list updates from your stock notes.",
          ),
        ]),
  );
  const kitchenThings = state.flat.inventory.filter(
    (item) =>
      item.category.toLowerCase().includes("kitchen") ||
      item.location.toLowerCase().includes("kitchen"),
  );
  $("#kitchen-inventory").replaceChildren(
    ...(kitchenThings.length
      ? kitchenThings.map((item) => inventoryRecord(item, true))
      : [
          emptyRecord(
            "Give kitchen things a home.",
            "Add them with category ‘kitchen’ or a kitchen location.",
          ),
        ]),
  );
}

function renderExpenses() {
  const summary = state.flat_summary.expenses || {
    total_cents: 0,
    balances: [],
    settlements: [],
  };
  $("#expense-total").textContent =
    `${moneyCents(summary.total_cents)} across ${state.flat.expenses.length} shared ${state.flat.expenses.length === 1 ? "cost" : "costs"}`;
  $("#balances-list").replaceChildren(
    ...(summary.balances.length
      ? summary.balances.map((balance) => {
          const result = append(
            node("div", { class: "balance-row" }),
            append(
              node("div"),
              node("strong", {}, balance.name),
              node(
                "small",
                {},
                `${moneyCents(balance.paid_cents)} paid · ${moneyCents(balance.share_cents)} share`,
              ),
            ),
          );
          const label =
            balance.balance_cents > 0
              ? "to receive"
              : balance.balance_cents < 0
                ? "to pay"
                : "balanced";
          result.append(
            append(
              node("div", {
                class: `balance-amount ${balance.balance_cents > 0 ? "positive" : balance.balance_cents < 0 ? "negative" : ""}`,
              }),
              node("strong", {}, moneyCents(Math.abs(balance.balance_cents))),
              node("small", {}, label),
            ),
          );
          return result;
        })
      : [
          emptyRecord(
            "No balance yet.",
            "Add people and a shared cost to see the split.",
          ),
        ]),
  );
  $("#settlements-list").replaceChildren(
    ...(summary.settlements.length
      ? summary.settlements.map((payment) =>
          append(
            node("div", { class: "settlement-row" }),
            node(
              "span",
              {},
              `${memberName(payment.from_id)} → ${memberName(payment.to_id)}`,
            ),
            node("strong", {}, moneyCents(payment.amount_cents)),
          ),
        )
      : [
          emptyRecord(
            "All recorded shares are balanced.",
            state.flat.expenses.length
              ? "No payment is suggested by this ledger."
              : "No bills have been recorded yet.",
          ),
        ]),
  );
  const records = [...state.flat.expenses].sort((a, b) =>
    b.date.localeCompare(a.date),
  );
  $("#expense-list").replaceChildren(
    ...(records.length
      ? records.map((expense) => {
          const content = append(
            node("div", { class: "household-row-main" }),
            node("h3", {}, expense.title),
            node(
              "p",
              {},
              `${shortDate(expense.date)} · ${memberName(expense.paid_by)} paid · ${expense.category}`,
            ),
            node(
              "p",
              {},
              `Shared by ${expense.split_between.map(memberName).join(", ")}`,
            ),
          );
          if (expense.notes) content.append(node("p", {}, expense.notes));
          const actions = append(
            node("div", { class: "household-row-actions" }),
            recordButton("Edit", () => openExpense(expense.id)),
            recordButton(
              "Remove",
              async (button) => {
                if (
                  !window.confirm(
                    `Remove “${expense.title}” from shared costs? Balances will be recalculated.`,
                  )
                )
                  return;
                button.disabled = true;
                try {
                  await updateFlat((flat) => {
                    flat.expenses = flat.expenses.filter(
                      (record) => record.id !== expense.id,
                    );
                  });
                  toast("Shared cost removed. Balances updated.");
                } finally {
                  button.disabled = false;
                }
              },
              "quiet-button",
            ),
          );
          return append(
            node("div", {
              class: "household-row",
              "data-expense-id": expense.id,
            }),
            node("span", { class: "row-symbol", "aria-hidden": "true" }, "€"),
            content,
            node(
              "span",
              { class: "expense-amount" },
              moneyCents(expense.amount_cents),
            ),
            actions,
          );
        })
      : [
          emptyRecord(
            "Your first shared bill goes here.",
            "Choose the payer and only the people who shared that cost.",
          ),
        ]),
  );
}

function renderHousehold() {
  ensureHousehold();
  renderHome();
  renderFlat();
  renderKitchen();
  renderExpenses();
}

function memberReferenced(memberId) {
  return (
    state.flat.inventory.some((record) => record.owner_id === memberId) ||
    state.flat.fridge.some((record) => record.owner_id === memberId) ||
    state.flat.expenses.some(
      (record) =>
        record.paid_by === memberId || record.split_between.includes(memberId),
    )
  );
}

function renderMembersEditor() {
  $("#flat-members-editor").replaceChildren(
    ...flatMembersDraft.map((person, index) => {
      const row = node("div", { class: "member-row" });
      const input = node("input", {
        value: person.name,
        required: "",
        maxlength: "80",
        "aria-label": `Person ${index + 1} name`,
      });
      input.addEventListener("input", () => {
        person.name = input.value;
      });
      append(
        row,
        node(
          "span",
          { class: "member-number", "aria-hidden": "true" },
          String(index + 1),
        ),
        input,
        recordButton(
          "×",
          () => {
            if (flatMembersDraft.length <= 1) {
              flatError(
                "#flat-settings-error",
                new Error("Keep at least one person in the flat."),
              );
              return;
            }
            if (memberReferenced(person.id)) {
              flatError(
                "#flat-settings-error",
                new Error(
                  `${person.name || "This person"} is referenced by belongings or shared costs. Update those records first.`,
                ),
              );
              return;
            }
            flatMembersDraft = flatMembersDraft.filter(
              (member) => member.id !== person.id,
            );
            renderMembersEditor();
          },
          "icon-button",
        ),
      );
      $("button", row).setAttribute(
        "aria-label",
        `Remove ${person.name || `person ${index + 1}`}`,
      );
      return row;
    }),
  );
}

function openFlatSettings() {
  const form = $("#flat-settings-form");
  form.elements.name.value = state.flat.name;
  form.elements.confirmed.checked = !state.flat.is_demo;
  flatMembersDraft = JSON.parse(JSON.stringify(state.flat.members));
  renderMembersEditor();
  $("#flat-settings-error").hidden = true;
  $("#flat-dialog").showModal();
}

function openFlatItem(itemId = null, kitchen = false) {
  const form = $("#flat-item-form");
  form.reset();
  const item = state.flat.inventory.find((record) => record.id === itemId);
  const data = item || {
    id: "",
    name: "",
    category: kitchen ? "kitchen" : "other",
    location: kitchen ? "Kitchen" : "",
    spot: "",
    quantity: 1,
    notes: "",
  };
  for (const key of [
    "id",
    "name",
    "category",
    "location",
    "spot",
    "quantity",
    "notes",
  ])
    form.elements.namedItem(key).value = data[key];
  fillOwnerSelect(form.elements.owner_id, item?.owner_id);
  $("#flat-item-title").textContent = item
    ? "Edit this thing"
    : kitchen
      ? "Add a kitchen thing"
      : "Add a thing";
  $("#flat-item-error").hidden = true;
  $("#flat-item-dialog").showModal();
}

function openFridgeItem(itemId = null) {
  const form = $("#fridge-form");
  form.reset();
  const item = state.flat.fridge.find((record) => record.id === itemId);
  const data = item || {
    id: "",
    name: "",
    quantity: "",
    storage: "fridge",
    status: "stocked",
    best_before: "",
    notes: "",
  };
  for (const key of [
    "id",
    "name",
    "quantity",
    "storage",
    "status",
    "best_before",
    "notes",
  ])
    form.elements.namedItem(key).value = data[key] || "";
  fillOwnerSelect(form.elements.owner_id, item?.owner_id);
  $("#fridge-dialog-title").textContent = item
    ? "Edit checklist item"
    : "Add food or a staple";
  $("#fridge-error").hidden = true;
  $("#fridge-dialog").showModal();
}

function openExpense(expenseId = null) {
  const form = $("#expense-form");
  form.reset();
  const expense = state.flat.expenses.find((record) => record.id === expenseId);
  form.elements.id.value = expense?.id || "";
  form.elements.title.value = expense?.title || "";
  form.elements.amount.value = expense
    ? expenseAmountInput(expense.amount_cents)
    : "";
  form.elements.date.value = expense?.date || localDateValue().slice(0, 10);
  form.elements.category.value = expense?.category || "groceries";
  form.elements.notes.value = expense?.notes || "";
  form.elements.paid_by.replaceChildren(
    ...state.flat.members.map((person) =>
      node("option", { value: person.id }, person.name),
    ),
  );
  form.elements.paid_by.value = expense?.paid_by || state.flat.members[0].id;
  // Preserve the recorded participant order because it determines any remainder cent.
  const participantMembers = expense
    ? [
        ...expense.split_between.map((memberId) =>
          state.flat.members.find((person) => person.id === memberId),
        ),
        ...state.flat.members.filter(
          (person) => !expense.split_between.includes(person.id),
        ),
      ]
    : state.flat.members;
  $("#expense-participants").replaceChildren(
    ...participantMembers.map((person) => {
      const checkbox = node("input", {
        type: "checkbox",
        value: person.id,
        "data-member-id": person.id,
      });
      checkbox.checked = expense
        ? expense.split_between.includes(person.id)
        : true;
      return append(
        node("label"),
        checkbox,
        document.createTextNode(person.name),
      );
    }),
  );
  $("#expense-dialog-title").textContent = expense
    ? "Edit shared cost"
    : "Add a shared cost";
  $("#expense-error").hidden = true;
  $("#expense-dialog").showModal();
}

async function submitFlatRecord(event, kind) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  const button = $("button[type=submit]", form);
  button.disabled = true;
  const errorId = {
    settings: "#flat-settings-error",
    inventory: "#flat-item-error",
    fridge: "#fridge-error",
    expenses: "#expense-error",
  }[kind];
  $(errorId).hidden = true;
  try {
    let record;
    if (kind === "settings") {
      await updateFlat((flat) => {
        flat.name = formValue(form, "name");
        flat.is_demo = !form.elements.confirmed.checked;
        flat.members = flatMembersDraft.map((person) => ({
          id: person.id,
          name: person.name.trim(),
        }));
      });
    } else {
      const recordId =
        formValue(form, "id") ||
        id(kind === "expenses" ? "bill" : kind === "fridge" ? "food" : "thing");
      if (kind === "inventory")
        record = {
          id: recordId,
          name: formValue(form, "name"),
          category: formValue(form, "category"),
          location: formValue(form, "location"),
          spot: formValue(form, "spot"),
          owner_id: formValue(form, "owner_id") || null,
          quantity: Number(formValue(form, "quantity")),
          notes: formValue(form, "notes"),
        };
      if (kind === "fridge")
        record = {
          id: recordId,
          name: formValue(form, "name"),
          quantity: formValue(form, "quantity"),
          storage: formValue(form, "storage"),
          owner_id: formValue(form, "owner_id") || null,
          status: formValue(form, "status"),
          best_before: formValue(form, "best_before") || null,
          notes: formValue(form, "notes"),
        };
      if (kind === "expenses") {
        const participants = $$("#expense-participants input:checked").map(
          (input) => input.value,
        );
        if (!participants.length)
          throw new Error("Choose at least one person who shares this cost.");
        record = {
          id: recordId,
          title: formValue(form, "title"),
          amount_cents: eurosToCents(formValue(form, "amount")),
          paid_by: formValue(form, "paid_by"),
          split_between: participants,
          date: formValue(form, "date"),
          category: formValue(form, "category"),
          notes: formValue(form, "notes"),
        };
      }
      await updateFlat((flat) => {
        const position = flat[kind].findIndex((item) => item.id === record.id);
        if (position === -1) flat[kind].push(record);
        else flat[kind][position] = record;
      });
    }
    form.closest("dialog").close();
    toast(
      {
        settings: "Flat and people saved.",
        inventory: "Thing saved with its location.",
        fridge: "Kitchen checklist updated.",
        expenses: "Shared cost saved. Balances recalculated.",
      }[kind],
    );
  } catch (error) {
    flatError(errorId, error);
  } finally {
    button.disabled = false;
  }
}

function wireHouseholdEvents() {
  $("#room-settings-local").addEventListener("click", openRoomSettings);
  [
    "flat-settings-button",
    "flat-setup-button",
    "expense-people-button",
  ].forEach((key) => $(`#${key}`).addEventListener("click", openFlatSettings));
  $("#add-flat-item").addEventListener("click", () => openFlatItem());
  $("#add-kitchen-item").addEventListener("click", () =>
    openFlatItem(null, true),
  );
  $("#add-fridge-item").addEventListener("click", () => openFridgeItem());
  $("#add-expense").addEventListener("click", () => openExpense());
  $("#export-expenses").addEventListener("click", () =>
    downloadData("/api/export?format=expenses"),
  );
  $("#add-flat-member").addEventListener("click", () => {
    flatMembersDraft.push({ id: id("person"), name: "" });
    renderMembersEditor();
    $("#flat-members-editor .member-row:last-child input").focus();
  });
  $("#flat-search").addEventListener("input", renderFlatInventory);
  ["flat-location-filter", "flat-owner-filter"].forEach((key) =>
    $(`#${key}`).addEventListener("change", renderFlatInventory),
  );
  ["fridge-storage-filter", "fridge-status-filter"].forEach((key) =>
    $(`#${key}`).addEventListener("change", renderKitchen),
  );
  $("#flat-settings-form").addEventListener("submit", (event) =>
    submitFlatRecord(event, "settings"),
  );
  $("#flat-item-form").addEventListener("submit", (event) =>
    submitFlatRecord(event, "inventory"),
  );
  $("#fridge-form").addEventListener("submit", (event) =>
    submitFlatRecord(event, "fridge"),
  );
  $("#expense-form").addEventListener("submit", (event) =>
    submitFlatRecord(event, "expenses"),
  );
}
