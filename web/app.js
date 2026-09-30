/* Roomies keeps room positions in centimetres. Python validates records and prices. */
"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const SVG_NS = "http://www.w3.org/2000/svg";
const MAX_BACKUP_BYTES = 32 * 1024 * 1024;
const euro = new Intl.NumberFormat("en-DE", {
  style: "currency",
  currency: "EUR",
});
const number = new Intl.NumberFormat("en-DE", { maximumFractionDigits: 2 });
let state = null;
let selectedId = null;
let selectedJournalId = null;
let wishlistFilter = "all";
let mutationRevision = 0;
let savedRevision = 0;
let saveTimer = null;
let savingPromise = null;
let toastTimer = null;
let importCandidate = null;
let dragging = null;
let settingsOpenings = [];
let currentView = "home";
let productEditId = null;
// Incomplete input belongs to its item until the user repairs or removes it.
const itemDrafts = new Map();

function node(tag, attributes = {}, text = null) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "class") element.className = value;
    else if (key === "type") element.type = value;
    else if (key === "value") element.value = value;
    else if (key === "hidden") element.hidden = value;
    else element.setAttribute(key, value);
  }
  if (text !== null) element.textContent = text;
  return element;
}

function svgNode(tag, attributes = {}, text = null) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes))
    element.setAttribute(key, value);
  if (text !== null) element.textContent = text;
  return element;
}

function append(parent, ...children) {
  children.filter(Boolean).forEach((child) => parent.appendChild(child));
  return parent;
}
function formValue(form, key) {
  return form.elements.namedItem(key).value;
}
function nullableNumber(value) {
  return value === "" || value === null || value === undefined
    ? null
    : Number(value);
}
function money(value) {
  return value === null ||
    value === undefined ||
    !Number.isFinite(Number(value))
    ? "Not known"
    : euro.format(Number(value));
}
function dimensions(item) {
  return Number(item.rotation) === 90
    ? [Number(item.depth_cm), Number(item.width_cm)]
    : [Number(item.width_cm), Number(item.depth_cm)];
}
function itemById(id) {
  return state?.room?.items.find((item) => item.id === id);
}
function productById(id) {
  return state?.products?.find((product) => product.id === id);
}
function id(prefix) {
  return `${prefix}-${crypto.randomUUID()}`;
}
function symbol(category) {
  return (
    {
      bed: "▰",
      desk: "▤",
      wardrobe: "▥",
      chair: "▧",
      shelf: "▥",
      lamp: "◉",
      rug: "▱",
      curtain: "≋",
      storage: "▣",
    }[category] || "▭"
  );
}
function safeUrl(value) {
  try {
    const parsed = new URL(value);
    return ["https:", "http:"].includes(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}
function friendlyDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date not known";
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function api(path, options = {}) {
  if (window.roomiesBrowser)
    return window.roomiesBrowser.request(path, options);
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(
      "The server returned an unreadable response. Your latest edit has not been confirmed saved.",
    );
  }
  if (!response.ok)
    throw new Error(
      data.error || data.message || `Request failed (${response.status}).`,
    );
  return data;
}

function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(
    () => {
      element.hidden = true;
    },
    error ? 8500 : 4500,
  );
}

function setSaveStatus(message, kind = "saved") {
  if (kind === "saved" && itemDrafts.size) {
    message = "Room edits not saved · fix invalid fields";
    kind = "error";
  } else if (kind === "saved" && flatSaveError) {
    message = "Flat changes not saved · try again";
    kind = "error";
  } else if (
    kind === "saved" &&
    (flatSavingPromise || savedRevision < mutationRevision)
  ) {
    message = "Saving your changes…";
    kind = "saving";
  }
  $("#save-status").textContent = message;
  $("#connection-dot").className =
    `status-dot${kind === "error" ? " error" : kind === "saving" ? " saving" : ""}`;
  if (kind === "saved" && $("#backup-recovery"))
    $("#backup-recovery").hidden = true;
}

function markDirty(delay = 450) {
  mutationRevision += 1;
  setSaveStatus("Saving your changes…", "saving");
  renderItemIssues();
  renderRoomIssues();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    flushRoom().catch((error) => toast(error.message, true));
  }, delay);
}

async function flushRoom() {
  clearTimeout(saveTimer);
  if (!state || savedRevision === mutationRevision) return;
  if (savingPromise) return savingPromise;
  savingPromise = (async () => {
    while (true) {
      while (savedRevision < mutationRevision) {
        const revision = mutationRevision;
        const payload = JSON.parse(JSON.stringify(state.room));
        try {
          const result = await api("/api/room", {
            method: "PUT",
            body: JSON.stringify(payload),
          });
          savedRevision = revision;
          if (revision === mutationRevision) {
            state.summary = result.summary || result.analysis || state.summary;
            renderMetrics();
            renderRoomIssues();
            renderInventory();
            renderItemIssues();
            renderPlan();
            renderHome();
          }
        } catch (error) {
          setSaveStatus("Not saved · try your edit again", "error");
          showBackupRecovery(error);
          throw error;
        }
      }
      const revision = mutationRevision;
      try {
        const refreshed = await api("/api/state");
        if (revision === mutationRevision) {
          state.products = refreshed.products || [];
          state.notifications = refreshed.notifications || [];
          state.tracker = refreshed.tracker;
          renderWishlist();
          renderJournal();
        }
      } catch {
        toast(
          "Your room was saved. The wishlist refresh failed; refresh the page to retry.",
          true,
        );
      }
      // A debounced call can join this promise during the read. Save edits it added.
      if (savedRevision < mutationRevision) continue;
      setSaveStatus("All changes saved locally");
      break;
    }
  })();
  try {
    await savingPromise;
  } finally {
    savingPromise = null;
  }
}

async function reload() {
  await flushRoom();
  await flushFlat();
  const roomVersion = mutationRevision,
    flatVersion = flatRevision;
  const refreshed = await api("/api/state");
  // A read started before a write must not replace that write's accepted state.
  if (state && (roomVersion !== mutationRevision || savingPromise)) {
    refreshed.room = state.room;
    refreshed.summary = state.summary;
  }
  if (state && (flatVersion !== flatRevision || flatSavingPromise)) {
    refreshed.flat = state.flat;
    refreshed.flat_summary = state.flat_summary;
  }
  state = refreshed;
  state.products ||= [];
  state.notifications ||= [];
  if (!itemById(selectedId)) selectedId = state.room.items[0]?.id || null;
  renderAll();
  showView(currentView);
  setSaveStatus("All changes saved locally");
}

function showView(view) {
  if (
    ![
      "home",
      "room",
      "flat",
      "kitchen",
      "expenses",
      "wishlist",
      "journal",
    ].includes(view)
  )
    return;
  currentView = view;
  $$(".view").forEach((section) => {
    const active = section.id === `view-${view}`;
    section.hidden = !active;
    section.classList.toggle("active", active);
  });
  $$("[data-view]").forEach((button) => {
    const active =
      button.dataset.view === view ||
      (button.dataset.navGroup === "upgrades" && view === "journal");
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $("#breadcrumb").textContent =
    `Roomies / ${{ home: "Home", room: "My room", flat: "My flat", kitchen: "Kitchen", expenses: "Shared costs", wishlist: "Upgrades · Wishlist", journal: "Upgrades · Price journal" }[view]}`;
  if (view === "journal") renderJournal();
}

function renderAll() {
  ensureHousehold();
  renderMetrics();
  renderPlan();
  renderInspector();
  renderInventory();
  renderRoomIssues();
  renderWishlist();
  renderJournal();
  renderHousehold();
}
function renderMetrics() {
  const room = state.room,
    summary = state.summary || {};
  $("#metric-area").textContent =
    `${number.format(summary.area_m2 ?? (room.width_cm * room.depth_cm) / 10000)} m²`;
  $("#metric-dimensions").textContent =
    `${number.format(room.width_cm / 100)} × ${number.format(room.depth_cm / 100)} m`;
  $("#metric-owned").textContent =
    `${number.format(summary.occupied_m2 ?? 0)} m²`;
  $("#metric-planned").textContent =
    `${number.format(summary.reserved_m2 ?? 0)} m²`;
  $("#metric-free").textContent = `${number.format(summary.free_m2 ?? 0)} m²`;
  $("#free-caption").textContent =
    summary.valid === false
      ? "check conflicts below"
      : "before access clearances";
  $("#sample-note").hidden = !room.is_demo;
  if (room.is_demo) {
    const text = $("#sample-note>span:nth-child(2)");
    text.replaceChildren(
      document.createTextNode("This is a "),
      node(
        "strong",
        {},
        `sample ${number.format(room.width_cm / 100)} × ${number.format(room.depth_cm / 100)} m room`,
      ),
      document.createTextNode(
        ". Add your measurements before using its placements or fit results.",
      ),
    );
  }
  $("#plan-subtitle").textContent =
    `${room.name} · positions measured in centimetres.`;
  $("#wish-count").textContent = String(state.products.length);
}

function openingRectangle(opening) {
  const room = state.room,
    width = Number(opening.width_cm),
    depth = Number(opening.depth_cm || 0),
    offset = Number(opening.offset_cm);
  if (opening.wall === "north") return [offset, 0, width, depth];
  if (opening.wall === "south")
    return [offset, Number(room.depth_cm) - depth, width, depth];
  if (opening.wall === "west") return [0, offset, depth, width];
  return [Number(room.width_cm) - depth, offset, depth, width];
}

function itemRectangle(item) {
  let x = Number(item.x_cm),
    y = Number(item.y_cm);
  if (item.placement === "surface") {
    const parent = itemById(item.parent_id);
    if (parent) {
      x += Number(parent.x_cm);
      y += Number(parent.y_cm);
    }
  }
  const [width, depth] = dimensions(item);
  return [x, y, width, depth];
}

function drawFurniture(group, item, w, d, thumbnail = false) {
  const planned = item.status === "planned";
  const rawColor = /^#[0-9a-f]{6}$/i.test(item.color || "")
    ? item.color
    : "#caa077";
  const stroke = planned ? "#87996d" : "#a58d71";
  const fill = planned ? "#ecf0df" : rawColor;
  group.append(
    svgNode("rect", {
      x: 0,
      y: 0,
      width: w,
      height: d,
      rx: 3,
      fill,
      stroke,
      "stroke-width": 1.1,
      "stroke-dasharray": planned ? "5 3" : "",
      class: "furniture-base",
    }),
  );
  const detail = {
    stroke: planned ? "#a7b58e" : "#f5eddf",
    "stroke-width": 0.8,
    fill: "none",
    opacity: 0.75,
    "pointer-events": "none",
  };
  if (item.category === "bed") {
    const pillowWidth = Math.max(12, w * 0.34),
      pillowDepth = Math.max(12, Math.min(26, d * 0.17));
    group.append(
      svgNode("rect", {
        x: w * 0.08,
        y: d * 0.05,
        width: pillowWidth,
        height: pillowDepth,
        rx: 3,
        ...detail,
        fill: planned ? "#f8f9f0" : "#e8dfca",
      }),
    );
    if (w > 85)
      group.append(
        svgNode("rect", {
          x: w * 0.58,
          y: d * 0.05,
          width: pillowWidth,
          height: pillowDepth,
          rx: 3,
          ...detail,
          fill: planned ? "#f8f9f0" : "#e8dfca",
        }),
      );
    group.append(
      svgNode("path", {
        d: `M 5 ${d * 0.28} H ${w - 5} M 5 ${d * 0.82} H ${w - 5}`,
        ...detail,
      }),
    );
  } else if (item.category === "desk") {
    group.append(
      svgNode("rect", {
        x: w * 0.34,
        y: d * 0.15,
        width: w * 0.3,
        height: d * 0.35,
        rx: 2,
        ...detail,
        fill: "#f7f7ec",
      }),
    );
    group.append(
      svgNode("path", {
        d: `M ${w * 0.3} ${d * 0.62} H ${w * 0.68} M ${w * 0.36} ${d * 0.68} H ${w * 0.6}`,
        ...detail,
      }),
    );
    group.append(
      svgNode("circle", {
        cx: w * 0.84,
        cy: d * 0.23,
        r: Math.min(w, d) * 0.06,
        ...detail,
      }),
    );
  } else if (["wardrobe", "storage", "shelf"].includes(item.category)) {
    group.append(
      svgNode("line", { x1: w / 2, y1: 3, x2: w / 2, y2: d - 3, ...detail }),
    );
    group.append(
      svgNode("line", {
        x1: w / 2 - 4,
        y1: d * 0.43,
        x2: w / 2 - 4,
        y2: d * 0.59,
        ...detail,
      }),
    );
    group.append(
      svgNode("line", {
        x1: w / 2 + 4,
        y1: d * 0.43,
        x2: w / 2 + 4,
        y2: d * 0.59,
        ...detail,
      }),
    );
  } else if (item.category === "lamp") {
    group.append(
      svgNode("circle", {
        cx: w / 2,
        cy: d / 2,
        r: Math.max(2, Math.min(w, d) * 0.32),
        fill: planned ? "#dce4c6" : "#efe3b8",
        stroke: planned ? "#9fae82" : "#ab9261",
        "stroke-width": 1,
      }),
    );
    group.append(
      svgNode("circle", {
        cx: w / 2,
        cy: d / 2,
        r: Math.max(1, Math.min(w, d) * 0.08),
        fill: stroke,
      }),
    );
  } else if (item.category === "chair") {
    group.append(
      svgNode("rect", {
        x: w * 0.15,
        y: d * 0.2,
        width: w * 0.7,
        height: d * 0.55,
        rx: 5,
        ...detail,
      }),
    );
    group.append(
      svgNode("path", {
        d: `M ${w * 0.15} ${d * 0.13} H ${w * 0.85}`,
        ...detail,
      }),
    );
  } else if (["rug", "curtain"].includes(item.category)) {
    for (let x = 5; x < w; x += 8)
      group.append(
        svgNode("line", { x1: x, y1: 3, x2: x, y2: d - 3, ...detail }),
      );
  }
  if (!thumbnail && w > 38 && d > 28) {
    const label =
      item.name.length > 18 ? `${item.name.slice(0, 16)}…` : item.name;
    group.append(
      svgNode(
        "text",
        {
          x: w / 2,
          y: d * 0.59,
          "text-anchor": "middle",
          fill: planned ? "#788d5e" : "#6f624e",
          "font-size": Math.min(10, w / Math.max(label.length * 0.65, 6)),
          "font-family": "Segoe UI,Arial,sans-serif",
          class: "furniture-text",
        },
        label,
      ),
    );
    if (d > 45)
      group.append(
        svgNode(
          "text",
          {
            x: w / 2,
            y: d * 0.59 + 12,
            "text-anchor": "middle",
            fill: planned ? "#9da989" : "#968268",
            "font-size": 6.5,
            "font-family": "Segoe UI,Arial,sans-serif",
            class: "furniture-text",
          },
          `${number.format(item.width_cm)} × ${number.format(item.depth_cm)} cm`,
        ),
      );
  }
}

function renderPlan(focusId = null) {
  if (!state) return;
  focusId ||=
    document.activeElement?.closest?.(".furniture-group")?.dataset.itemId;
  const svg = $("#room-plan"),
    room = state.room;
  const width = Number(room.width_cm),
    depth = Number(room.depth_cm),
    margin = 55;
  svg.setAttribute(
    "viewBox",
    `0 0 ${width + margin * 2} ${depth + margin * 2 + 15}`,
  );
  svg.replaceChildren();
  const defs = svgNode("defs");
  const pattern = svgNode("pattern", {
    id: "floor-grid",
    width: 25,
    height: 25,
    patternUnits: "userSpaceOnUse",
  });
  pattern.append(
    svgNode("path", {
      d: "M 25 0 L 0 0 0 25",
      fill: "none",
      stroke: "#e5eadd",
      "stroke-width": 0.55,
    }),
  );
  defs.append(pattern);
  svg.append(defs);
  svg.append(
    svgNode(
      "text",
      {
        x: margin + width / 2,
        y: 25,
        "text-anchor": "middle",
        class: "room-dimension",
      },
      `${number.format(width)} cm`,
    ),
  );
  svg.append(
    svgNode("line", {
      x1: margin,
      y1: 33,
      x2: margin + width,
      y2: 33,
      stroke: "#c6ceb8",
      "stroke-width": 0.7,
    }),
  );
  [margin, margin + width].forEach((x) =>
    svg.append(
      svgNode("line", {
        x1: x,
        y1: 29,
        x2: x,
        y2: 37,
        stroke: "#c6ceb8",
        "stroke-width": 0.7,
      }),
    ),
  );
  svg.append(
    svgNode(
      "text",
      {
        x: 20,
        y: margin + depth / 2,
        transform: `rotate(-90 20 ${margin + depth / 2})`,
        "text-anchor": "middle",
        class: "room-dimension",
      },
      `${number.format(depth)} cm`,
    ),
  );
  svg.append(
    svgNode("line", {
      x1: 31,
      y1: margin,
      x2: 31,
      y2: margin + depth,
      stroke: "#c6ceb8",
      "stroke-width": 0.7,
    }),
  );
  [margin, margin + depth].forEach((y) =>
    svg.append(
      svgNode("line", {
        x1: 27,
        y1: y,
        x2: 35,
        y2: y,
        stroke: "#c6ceb8",
        "stroke-width": 0.7,
      }),
    ),
  );
  const plan = svgNode("g", { transform: `translate(${margin} ${margin})` });
  svg.append(plan);
  plan.append(
    svgNode("rect", {
      x: 0,
      y: 0,
      width,
      height: depth,
      rx: 0,
      fill: room.floor_color || "#f4f6ed",
      stroke: room.wall_color || "#a4b497",
      "stroke-width": 5,
    }),
  );
  plan.append(
    svgNode("rect", {
      x: 2,
      y: 2,
      width: Math.max(0, width - 4),
      height: Math.max(0, depth - 4),
      fill: "url(#floor-grid)",
    }),
  );
  for (const opening of room.openings || []) {
    const [x, y, w, d] = openingRectangle(opening);
    if (opening.kind === "obstacle") {
      plan.append(
        svgNode("rect", {
          x,
          y,
          width: w,
          height: d,
          fill: "#d4dacb",
          stroke: "#a5b399",
          "stroke-width": 1,
        }),
      );
      plan.append(
        svgNode(
          "text",
          {
            x: x + w / 2,
            y: y + d / 2 + 3,
            "text-anchor": "middle",
            "font-size": 7,
            fill: "#7c8a72",
          },
          "fixed",
        ),
      );
      continue;
    }
    if (
      opening.kind === "door" &&
      opening.swing === "in" &&
      $("#show-clearance").checked
    ) {
      plan.append(
        svgNode("rect", {
          x,
          y,
          width: w,
          height: d,
          fill: "#f3e8d780",
          stroke: "#d8bf98",
          "stroke-width": 0.7,
          "stroke-dasharray": "3 3",
        }),
      );
    }
    const offset = Number(opening.offset_cm),
      length = Number(opening.width_cm);
    const coords =
      opening.wall === "north"
        ? [offset, 0, offset + length, 0]
        : opening.wall === "south"
          ? [offset, depth, offset + length, depth]
          : opening.wall === "west"
            ? [0, offset, 0, offset + length]
            : [width, offset, width, offset + length];
    plan.append(
      svgNode("line", {
        x1: coords[0],
        y1: coords[1],
        x2: coords[2],
        y2: coords[3],
        stroke: "#fcfcf8",
        "stroke-width": 6,
      }),
    );
    if (opening.kind === "window") {
      plan.append(
        svgNode("line", {
          x1: coords[0],
          y1: coords[1],
          x2: coords[2],
          y2: coords[3],
          stroke: "#a9c1ad",
          "stroke-width": 2,
        }),
      );
      plan.append(
        svgNode("line", {
          x1:
            coords[0] +
            (opening.wall === "east" ? -3 : opening.wall === "west" ? 3 : 0),
          y1:
            coords[1] +
            (opening.wall === "north" ? 3 : opening.wall === "south" ? -3 : 0),
          x2:
            coords[2] +
            (opening.wall === "east" ? -3 : opening.wall === "west" ? 3 : 0),
          y2:
            coords[3] +
            (opening.wall === "north" ? 3 : opening.wall === "south" ? -3 : 0),
          stroke: "#c4d5bd",
          "stroke-width": 1,
        }),
      );
    } else {
      const vertical = ["east", "west"].includes(opening.wall);
      const inward =
        opening.wall === "north" || opening.wall === "west" ? 1 : -1;
      const cx = coords[0],
        cy = coords[1];
      if (opening.swing !== "none") {
        const direction = opening.swing === "out" ? -inward : inward;
        const ex = vertical ? cx + length * direction : cx;
        const ey = vertical ? cy : cy + length * direction;
        plan.append(
          svgNode("line", {
            x1: cx,
            y1: cy,
            x2: ex,
            y2: ey,
            stroke: "#b6bdac",
            "stroke-width": 1,
          }),
        );
        const sweep = vertical
          ? direction > 0
            ? 0
            : 1
          : direction > 0
            ? 1
            : 0;
        plan.append(
          svgNode("path", {
            d: `M ${coords[2]} ${coords[3]} A ${length} ${length} 0 0 ${sweep} ${ex} ${ey}`,
            fill: "none",
            stroke: "#b6bdac",
            "stroke-width": 0.8,
            "stroke-dasharray": "3 2",
          }),
        );
      }
    }
  }
  const order = { overlay: 0, floor: 1, wall: 2, surface: 3 };
  const items = [...room.items].sort(
    (a, b) => (order[a.placement] ?? 1) - (order[b.placement] ?? 1),
  );
  for (const item of items) {
    const [x, y, w, d] = itemRectangle(item);
    if (
      $("#show-clearance").checked &&
      item.placement === "floor" &&
      Number(item.clearance_cm) > 0
    ) {
      const c = Number(item.clearance_cm);
      plan.append(
        svgNode("rect", {
          x: x - c,
          y: y - c,
          width: w + c * 2,
          height: d + c * 2,
          fill: "#f4e8d825",
          stroke: "#d5bd91",
          "stroke-width": 0.6,
          "stroke-dasharray": "3 3",
          "pointer-events": "none",
        }),
      );
    }
    const group = svgNode("g", {
      transform: `translate(${x} ${y})`,
      class: "furniture-group",
      tabindex: 0,
      role: "button",
      "data-item-id": item.id,
      "aria-label": `${item.name}, ${item.status === "planned" ? "reserved for later" : "owned"}, ${item.width_cm} by ${item.depth_cm} centimetres, position ${item.x_cm}, ${item.y_cm}. Arrow keys move, R rotates.`,
    });
    group.append(
      svgNode(
        "title",
        {},
        `${item.name} · ${number.format(item.width_cm)} × ${number.format(item.depth_cm)} cm · ${item.status === "planned" ? "For later" : "Already mine"}`,
      ),
    );
    const invalid = (state.summary?.issues || []).some(
      (issue) => issue.item_id === item.id && issue.severity !== "warning",
    );
    const selected = item.id === selectedId;
    group.append(
      svgNode("rect", {
        x: -3,
        y: -3,
        width: w + 6,
        height: d + 6,
        rx: 5,
        fill: "none",
        stroke: invalid ? "#bb7958" : selected ? "#567249" : "transparent",
        "stroke-width": selected ? 1.6 : 1,
        "stroke-dasharray": invalid ? "3 2" : "",
        class: "selection-ring",
        "pointer-events": "none",
      }),
    );
    drawFurniture(group, item, w, d);
    if (selected)
      [
        [0, 0],
        [w, 0],
        [0, d],
        [w, d],
      ].forEach(([cx, cy]) =>
        group.append(
          svgNode("circle", {
            cx,
            cy,
            r: 1.9,
            fill: "#fcfcf8",
            stroke: "#58744b",
            "stroke-width": 0.8,
            "pointer-events": "none",
          }),
        ),
      );
    group.addEventListener("pointerdown", (event) => beginDrag(event, item));
    group.addEventListener("focus", () => {
      if (selectedId !== item.id) selectItem(item.id, false);
    });
    group.addEventListener("keydown", (event) => itemKeydown(event, item));
    group.addEventListener("click", () => selectItem(item.id, false));
    plan.append(group);
  }
  svg.append(
    svgNode(
      "text",
      {
        x: margin + width / 2,
        y: margin + depth + 24,
        "text-anchor": "middle",
        class: "room-text",
      },
      "NORTH = TOP · NOT A CONSTRUCTION DRAWING",
    ),
  );
  const north = svgNode("g", {
    transform: `translate(${width + margin + 23} ${margin + 7})`,
  });
  north.append(
    svgNode("path", { d: "M0 0 L-4 10 L0 7 L4 10 Z", class: "north-arrow" }),
  );
  north.append(
    svgNode(
      "text",
      { x: 0, y: -6, "text-anchor": "middle", class: "room-text" },
      "N",
    ),
  );
  svg.append(north);
  if (focusId)
    for (const group of $$("[data-item-id]", svg))
      if (group.dataset.itemId === focusId)
        group.focus({ preventScroll: true });
}

function pointerInRoom(event) {
  const svg = $("#room-plan"),
    point = svg.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  const matrix = svg.getScreenCTM();
  if (!matrix) return null;
  const mapped = point.matrixTransform(matrix.inverse());
  return { x: mapped.x - 55, y: mapped.y - 55 };
}

function beginDrag(event, item) {
  if (event.button !== 0) return;
  event.preventDefault();
  if (itemDrafts.has(item.id)) {
    selectItem(item.id, false);
    toast("Fix this item's invalid fields before moving it.", true);
    return;
  }
  if (item.locked) {
    selectItem(item.id, false);
    toast(
      "This item is fixed. Uncheck “Keep this item fixed” before dragging it.",
    );
    return;
  }
  selectItem(item.id, false);
  const point = pointerInRoom(event);
  if (!point) return;
  dragging = {
    id: item.id,
    pointerId: event.pointerId,
    startX: point.x,
    startY: point.y,
    x: Number(item.x_cm),
    y: Number(item.y_cm),
    moved: false,
  };
  $("#room-plan").setPointerCapture(event.pointerId);
}

function dragMove(event) {
  if (!dragging || event.pointerId !== dragging.pointerId) return;
  const point = pointerInRoom(event);
  if (!point) return;
  const item = itemById(dragging.id);
  if (!item) return;
  item.x_cm = Math.round((dragging.x + point.x - dragging.startX) / 0.5) * 0.5;
  item.y_cm = Math.round((dragging.y + point.y - dragging.startY) / 0.5) * 0.5;
  dragging.moved = true;
  const group = $$("[data-item-id]", $("#room-plan")).find(
    (element) => element.dataset.itemId === item.id,
  );
  const [x, y] = itemRectangle(item);
  if (group) {
    group.setAttribute("transform", `translate(${x} ${y})`);
    group.classList.add("dragging");
  }
  const form = $("#item-form");
  form.elements.x_cm.value = item.x_cm;
  form.elements.y_cm.value = item.y_cm;
}

function endDrag(event) {
  if (!dragging || event.pointerId !== dragging.pointerId) return;
  const wasMoved = dragging.moved;
  dragging = null;
  if ($("#room-plan").hasPointerCapture(event.pointerId))
    $("#room-plan").releasePointerCapture(event.pointerId);
  renderPlan();
  if (wasMoved) markDirty(80);
}

function selectItem(itemId, updatePlan = true) {
  selectedId = itemId;
  renderInspector();
  if (updatePlan) renderPlan();
  else {
    for (const group of $$("[data-item-id]", $("#room-plan"))) {
      const selected = group.dataset.itemId === selectedId;
      const ring = $(".selection-ring", group);
      if (ring) {
        ring.setAttribute("stroke", selected ? "#567249" : "transparent");
        ring.setAttribute("stroke-width", selected ? 1.6 : 1);
      }
    }
  }
}

function itemKeydown(event, item) {
  const increments = {
    ArrowLeft: [-5, 0],
    ArrowRight: [5, 0],
    ArrowUp: [0, -5],
    ArrowDown: [0, 5],
  };
  if (
    !increments[event.key] &&
    event.key.toLowerCase() !== "r" &&
    event.key !== "Enter" &&
    event.key !== " "
  )
    return;
  event.preventDefault();
  selectedId = item.id;
  if (itemDrafts.has(item.id)) {
    toast("Fix this item's invalid fields before moving it.", true);
    return;
  }
  if (item.locked) return;
  if (increments[event.key]) {
    const [x, y] = increments[event.key];
    const factor = event.shiftKey ? 5 : 1;
    item.x_cm = Number(item.x_cm) + x * factor;
    item.y_cm = Number(item.y_cm) + y * factor;
  } else if (event.key.toLowerCase() === "r")
    item.rotation = Number(item.rotation) === 90 ? 0 : 90;
  else {
    renderInspector();
    return;
  }
  renderPlan(item.id);
  renderInspector();
  markDirty(250);
}

function renderInspector() {
  const item = itemById(selectedId),
    form = $("#item-form");
  $("#inspector-empty").hidden = Boolean(item);
  form.hidden = !item;
  $("#inspector-heading").textContent = item ? "Make it fit" : "Pick a piece";
  $("#suggestions").hidden = true;
  if (!item) return;
  $("#selected-name").textContent = item.name;
  $("#selected-symbol").textContent = symbol(item.category);
  $("#selected-status").textContent =
    item.status === "planned" ? "Reserved for later" : "Already mine";
  for (const field of [
    "name",
    "category",
    "status",
    "width_cm",
    "depth_cm",
    "height_cm",
    "x_cm",
    "y_cm",
    "placement",
    "clearance_cm",
    "color",
    "notes",
  ]) {
    const input = form.elements.namedItem(field);
    if (input) input.value = item[field] ?? (field === "clearance_cm" ? 0 : "");
  }
  form.elements.target_price.value = item.target_eur || "";
  form.elements.locked.checked = Boolean(item.locked);
  const parents = state.room.items.filter(
    (candidate) => candidate.id !== item.id && candidate.placement === "floor",
  );
  form.elements.parent_id.replaceChildren(
    node("option", { value: "" }, "Choose an item"),
    ...parents.map((parent) =>
      node("option", { value: parent.id }, parent.name),
    ),
  );
  form.elements.parent_id.value = item.parent_id || "";
  const draft = itemDrafts.get(item.id);
  if (draft)
    for (const [key, value] of Object.entries(draft)) {
      const input = form.elements.namedItem(key);
      if (input.type === "checkbox") input.checked = value;
      else input.value = value;
    }
  updatePlacementFields();
  $("#rotation-value").textContent = `Rotation ${item.rotation || 0}°`;
  renderItemIssues();
}

function updatePlacementFields() {
  const surface = $("#item-form").elements.placement.value === "surface";
  $("#parent-label").hidden = !surface;
  $("#budget-label").hidden = surface;
  $("#position-origin").textContent = surface
    ? "from top-left of the parent footprint"
    : "from top-left of room";
}

function renderItemIssues() {
  const root = $("#item-issues"),
    item = itemById(selectedId);
  root.replaceChildren();
  if (!item) return;
  if (itemDrafts.has(item.id)) {
    root.append(
      node(
        "p",
        {},
        "These edits are not saved. Correct the invalid fields; your draft is kept when you select another item.",
      ),
    );
    return;
  }
  if (savedRevision < mutationRevision) {
    root.append(
      node("p", {}, "Your latest position has not been saved and checked yet."),
    );
    return;
  }
  const issues = (state.summary?.issues || []).filter(
    (issue) => issue.item_id === item.id,
  );
  if (issues.length)
    issues.forEach((issue) => root.append(node("p", {}, issue.message)));
  else
    root.append(
      node(
        "p",
        { class: "good" },
        state.room.is_demo
          ? "No geometry conflict in the sample. Confirm your actual room before using this placement."
          : "No placement conflict found for this item.",
      ),
    );
}

function renderInventory() {
  const list = $("#inventory-list");
  list.replaceChildren();
  if (!state.room.items.length) {
    list.append(
      node(
        "p",
        { class: "muted" },
        "Start with one item you already own, then reserve your next place.",
      ),
    );
    return;
  }
  for (const item of state.room.items) {
    const row = node("button", { type: "button", class: "inventory-row" });
    const main = append(
      node("span", { class: "inventory-main" }),
      node("strong", {}, item.name),
      node(
        "small",
        {},
        `${number.format(item.width_cm)} × ${number.format(item.depth_cm)} cm${item.placement === "surface" ? ` · on ${itemById(item.parent_id)?.name || "missing parent"}` : ""}`,
      ),
    );
    const meta = node("span", { class: "inventory-meta" });
    meta.append(
      node(
        "span",
        { class: `item-chip ${item.status === "owned" ? "owned" : ""}` },
        item.status === "owned" ? "Already mine" : "For later",
      ),
    );
    const conflicts = (state.summary?.issues || []).filter(
      (issue) => issue.item_id === item.id,
    );
    if (conflicts.length)
      meta.append(
        node(
          "span",
          {},
          `${conflicts.length} ${conflicts.length === 1 ? "check" : "checks"}`,
        ),
      );
    append(
      row,
      node(
        "span",
        { class: "item-symbol", "aria-hidden": "true" },
        symbol(item.category),
      ),
      main,
      meta,
      node("span", { "aria-hidden": "true" }, "↗"),
    );
    row.addEventListener("click", () => {
      selectItem(item.id);
      $("#inspector-heading").scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    });
    list.append(row);
  }
}

function renderRoomIssues() {
  const issues = state.summary?.issues || [],
    list = $("#room-issues");
  list.replaceChildren();
  if (itemDrafts.size) {
    $("#room-check-heading").textContent = "Room edits need attention";
    $("#room-check-icon").textContent = "!";
    $("#room-check-icon").classList.add("warning");
    list.append(
      node(
        "p",
        { class: "muted" },
        "Some item fields are invalid. Their drafts are kept, but the plan still uses the last valid values.",
      ),
    );
    return;
  }
  if (savedRevision < mutationRevision) {
    $("#room-check-heading").textContent = "Checking your changes";
    $("#room-check-icon").textContent = "…";
    $("#room-check-icon").classList.add("warning");
    list.append(
      node(
        "p",
        { class: "muted" },
        "Your latest room edits need to be saved before placement results are confirmed.",
      ),
    );
    return;
  }
  $("#room-check-heading").textContent = issues.length
    ? `${issues.length} ${issues.length === 1 ? "thing" : "things"} to check`
    : "Everything has a place";
  $("#room-check-icon").textContent = issues.length ? "!" : "✓";
  $("#room-check-icon").classList.toggle("warning", Boolean(issues.length));
  if (!issues.length)
    list.append(
      node(
        "p",
        { class: "muted" },
        state.room.is_demo
          ? "The sample layout passes the defined geometry checks. Your actual room still needs measuring."
          : "No overlaps, boundary problems or defined access-space conflicts were found.",
      ),
    );
  for (const issue of issues) {
    const row = node("div", { class: "room-issue" });
    if (issue.item_id) {
      const button = node("button", { type: "button" }, issue.message);
      button.addEventListener("click", () => selectItem(issue.item_id));
      row.append(button);
    } else row.append(node("span", {}, issue.message));
    list.append(row);
  }
}

function addItem() {
  const item = {
    id: id("item"),
    name: "A future desk",
    category: "desk",
    width_cm: 100,
    depth_cm: 50,
    height_cm: 75,
    x_cm: 0,
    y_cm: 0,
    rotation: 0,
    status: "planned",
    placement: "floor",
    parent_id: null,
    color: "#cba67a",
    locked: false,
    clearance_cm: 0,
    target_eur: 100,
    notes: "",
  };
  state.room.items.push(item);
  selectedId = item.id;
  renderAll();
  markDirty();
  $("#item-form").elements.name.focus();
  $("#item-form").elements.name.select();
}

function updateItemFromForm() {
  const form = $("#item-form"),
    item = itemById(selectedId);
  if (!item) return;
  if (!form.checkValidity()) {
    itemDrafts.set(
      item.id,
      Object.fromEntries(
        [...form.elements]
          .filter((input) => input.name)
          .map((input) => [
            input.name,
            input.type === "checkbox" ? input.checked : input.value,
          ]),
      ),
    );
    setSaveStatus("Room edits not saved · fix invalid fields", "error");
    renderItemIssues();
    renderRoomIssues();
    return;
  }
  itemDrafts.delete(item.id);
  for (const key of [
    "name",
    "category",
    "status",
    "placement",
    "color",
    "notes",
  ])
    item[key] = formValue(form, key);
  for (const key of [
    "width_cm",
    "depth_cm",
    "height_cm",
    "x_cm",
    "y_cm",
    "clearance_cm",
  ])
    item[key] = Number(formValue(form, key));
  item.parent_id =
    item.placement === "surface" ? formValue(form, "parent_id") || null : null;
  item.target_eur = nullableNumber(formValue(form, "target_price")) || 0;
  item.locked = form.elements.locked.checked;
  $("#selected-name").textContent = item.name;
  $("#selected-symbol").textContent = symbol(item.category);
  $("#selected-status").textContent =
    item.status === "planned" ? "Reserved for later" : "Already mine";
  updatePlacementFields();
  renderPlan();
  renderInventory();
  markDirty();
}

async function suggestPositions() {
  if (!selectedId) return;
  const requestedId = selectedId;
  if (itemDrafts.has(requestedId)) {
    $("#item-form").reportValidity();
    toast("Fix this item's invalid fields before requesting positions.", true);
    return;
  }
  const button = $("#suggest-positions"),
    root = $("#suggestions");
  button.disabled = true;
  try {
    await flushRoom();
    if (selectedId !== requestedId) return;
    const requestedRevision = mutationRevision;
    const result = await api("/api/suggest", {
      method: "POST",
      body: JSON.stringify({ item_id: requestedId }),
    });
    if (
      selectedId !== requestedId ||
      mutationRevision !== requestedRevision ||
      itemDrafts.has(requestedId) ||
      !itemById(requestedId)
    )
      return;
    root.replaceChildren();
    root.hidden = false;
    if (!result.placements?.length)
      root.append(
        node(
          "p",
          { class: "field-help" },
          "No clear alternative was found. Adjust the item dimensions or other furniture first.",
        ),
      );
    for (const placement of result.placements || []) {
      const option = node("button", {
        type: "button",
        class: "suggestion-button",
      });
      option.append(
        document.createTextNode(
          `X ${number.format(placement.x_cm)} · Y ${number.format(placement.y_cm)} · ${placement.rotation}°`,
        ),
      );
      const reason =
        placement.reason ||
        placement.reasons?.join(" ") ||
        "A position that passes the defined room checks.";
      option.append(node("span", {}, reason));
      option.addEventListener("click", () => {
        if (
          selectedId !== requestedId ||
          mutationRevision !== requestedRevision ||
          itemDrafts.has(requestedId)
        ) {
          root.hidden = true;
          toast("The room changed. Request new positions for this item.");
          return;
        }
        const item = itemById(requestedId);
        if (!item) return;
        Object.assign(item, {
          x_cm: placement.x_cm,
          y_cm: placement.y_cm,
          rotation: placement.rotation,
        });
        renderAll();
        markDirty(50);
      });
      root.append(option);
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function openRoomSettings() {
  if (!state) return;
  const form = $("#room-settings-form"),
    room = state.room;
  for (const key of [
    "name",
    "width_cm",
    "depth_cm",
    "height_cm",
    "budget_eur",
    "style",
    "notes",
  ])
    form.elements.namedItem(key).value = room[key];
  form.elements.wall_color.value = room.wall_color || "#a4b497";
  form.elements.floor_color.value = room.floor_color || "#f4f6ed";
  form.elements.confirmed.checked = !room.is_demo;
  settingsOpenings = JSON.parse(JSON.stringify(room.openings || []));
  renderOpeningsEditors();
  $("#room-settings-error").hidden = true;
  $("#room-dialog").showModal();
}

function openingField(opening, key, label, type = "number", options = null) {
  const wrapper = node("label", {}, label);
  let input;
  if (options) {
    input = node("select");
    options.forEach(([value, text]) =>
      input.append(node("option", { value }, text)),
    );
  } else input = node("input", { type, step: 0.5, min: 0, required: true });
  input.value = opening[key] ?? 0;
  input.addEventListener("change", () => {
    opening[key] =
      type === "number" && !options ? Number(input.value) : input.value;
    if (key === "kind") {
      opening.swing = opening.kind === "door" ? "in" : "none";
      opening.depth_cm = opening.kind === "door" ? opening.width_cm : 0;
      renderOpeningsEditors();
    }
  });
  wrapper.append(input);
  return wrapper;
}

function renderOpeningsEditors() {
  $("#openings-editor").replaceChildren();
  $("#obstacles-editor").replaceChildren();
  for (const opening of settingsOpenings) {
    const row = node("div", { class: "repeater-row" });
    if (opening.kind !== "obstacle")
      row.append(
        openingField(opening, "kind", "Type", "text", [
          ["door", "Door"],
          ["window", "Window"],
        ]),
      );
    else row.append(node("strong", { class: "field-help" }, "Fixed obstacle"));
    row.append(
      openingField(opening, "wall", "Wall", "text", [
        ["north", "North / top"],
        ["east", "East / right"],
        ["south", "South / bottom"],
        ["west", "West / left"],
      ]),
    );
    row.append(openingField(opening, "offset_cm", "Offset along wall · cm"));
    row.append(openingField(opening, "width_cm", "Width along wall · cm"));
    row.append(
      openingField(
        opening,
        "depth_cm",
        opening.kind === "obstacle"
          ? "Depth into room · cm"
          : "Keep-clear depth · cm",
      ),
    );
    if (opening.kind === "door")
      row.append(
        openingField(opening, "swing", "Door swing", "text", [
          ["in", "Into the room"],
          ["out", "Out of the room"],
          ["none", "No swing / sliding"],
        ]),
      );
    else opening.swing = "none";
    const actions = node("div", { class: "repeater-actions wide-field" });
    const remove = node(
      "button",
      { type: "button", class: "small-button" },
      "Remove",
    );
    remove.addEventListener("click", () => {
      settingsOpenings = settingsOpenings.filter(
        (candidate) => candidate.id !== opening.id,
      );
      renderOpeningsEditors();
    });
    actions.append(remove);
    row.append(actions);
    $(
      opening.kind === "obstacle" ? "#obstacles-editor" : "#openings-editor",
    ).append(row);
  }
}

async function saveRoomSettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  const oldRoom = JSON.parse(JSON.stringify(state.room));
  const oldRevision = mutationRevision;
  state.room.name = formValue(form, "name");
  state.room.width_cm = Number(formValue(form, "width_cm"));
  state.room.depth_cm = Number(formValue(form, "depth_cm"));
  state.room.is_demo = !form.elements.confirmed.checked;
  state.room.height_cm = Number(formValue(form, "height_cm"));
  state.room.budget_eur = Number(formValue(form, "budget_eur"));
  state.room.style = formValue(form, "style");
  state.room.wall_color = formValue(form, "wall_color");
  state.room.floor_color = formValue(form, "floor_color");
  state.room.notes = formValue(form, "notes");
  state.room.openings = settingsOpenings.map((opening) => ({
    ...opening,
    swing: opening.kind === "door" ? opening.swing : "none",
  }));
  markDirty(10000);
  const submit = $("button[type=submit]", form);
  submit.disabled = true;
  try {
    await flushRoom();
    $("#room-dialog").close();
    renderAll();
    toast("Room saved. Check the plan for any new placement conflicts.");
  } catch (error) {
    state.room = oldRoom;
    mutationRevision = Math.max(oldRevision, savedRevision);
    if (mutationRevision > savedRevision) markDirty(100);
    $("#room-settings-error").textContent = error.message;
    $("#room-settings-error").hidden = false;
  } finally {
    submit.disabled = false;
  }
}

function productIllustration(product, item) {
  const holder = node("div", { class: "product-illustration" });
  holder.append(
    node(
      "span",
      { class: "product-slot" },
      item ? `Reserved for ${item.name}` : "Choose a reserved place",
    ),
  );
  const svg = svgNode("svg", {
    viewBox: "0 0 200 130",
    role: "img",
    "aria-label": "Illustration of the item category; not a product photo",
  });
  const category = item?.category || "other";
  const stroke = "#8e987c",
    fill = "#d8c4a8",
    pale = "#f7f5ec";
  svg.append(
    svgNode("ellipse", {
      cx: 100,
      cy: 114,
      rx: 66,
      ry: 7,
      fill: "#d9ddce",
      opacity: 0.45,
    }),
  );
  if (category === "desk") {
    svg.append(
      svgNode("path", {
        d: "M 35 57 L 142 43 L 174 68 L 68 84 Z",
        fill,
        stroke,
        "stroke-width": 1.3,
      }),
    );
    svg.append(
      svgNode("path", {
        d: "M 35 57 V 65 L 68 91 V 84 M 68 84 L174 68 V75 L68 91",
        fill: "#c8b293",
        stroke,
        "stroke-width": 1.2,
      }),
    );
    svg.append(
      svgNode("path", {
        d: "M 43 66 V 102 M 73 91 V 115 M 167 75 V 106 M 139 45 V 72",
        stroke,
        "stroke-width": 3,
        fill: "none",
      }),
    );
    svg.append(
      svgNode("path", {
        d: "M 79 52 L 126 46 L143 59 L 96 66 Z",
        fill: pale,
        stroke: "#a9b69a",
        "stroke-width": 0.8,
      }),
    );
  } else if (category === "lamp") {
    svg.append(
      svgNode("ellipse", {
        cx: 102,
        cy: 111,
        rx: 30,
        ry: 7,
        fill: "#b8c3a2",
        stroke,
      }),
    );
    svg.append(
      svgNode("path", { d: "M 102 111 V 53", stroke, "stroke-width": 4 }),
    );
    svg.append(
      svgNode("path", {
        d: "M 85 27 L 118 27 L 139 61 L 65 61 Z",
        fill: "#ead9b4",
        stroke,
        "stroke-width": 1.3,
      }),
    );
    svg.append(
      svgNode("ellipse", {
        cx: 102,
        cy: 61,
        rx: 37,
        ry: 7,
        fill: "#f2e4bd",
        stroke,
        "stroke-width": 1,
      }),
    );
  } else if (category === "bed") {
    svg.append(
      svgNode("path", {
        d: "M 30 57 L 94 31 L174 80 L111 111 Z",
        fill: "#d2dcc1",
        stroke,
        "stroke-width": 1.3,
      }),
    );
    svg.append(
      svgNode("path", {
        d: "M 30 57 V75 L111 124 L174 94 V80 L111 111 Z",
        fill,
        stroke,
        "stroke-width": 1.2,
      }),
    );
    svg.append(
      svgNode("path", {
        d: "M 40 57 L91 39 L113 52 L62 73 Z",
        fill: pale,
        stroke,
        "stroke-width": 0.8,
      }),
    );
    svg.append(
      svgNode("path", {
        d: "M 72 81 L134 55",
        stroke: "#9ba887",
        "stroke-width": 1.2,
      }),
    );
  } else if (category === "rug") {
    svg.append(
      svgNode("path", {
        d: "M 25 67 L111 37 L177 77 L88 111 Z",
        fill: "#dfbc9a",
        stroke,
        "stroke-width": 1,
      }),
    );
    for (let i = 0; i < 5; i++)
      svg.append(
        svgNode("path", {
          d: `M ${35 + i * 12} ${64 - i * 4} L ${100 + i * 12} ${105 - i * 5}`,
          stroke: "#f8e6d0",
          "stroke-width": 3,
        }),
      );
  } else if (category === "curtain") {
    svg.append(
      svgNode("path", { d: "M 45 20 H 157", stroke, "stroke-width": 3 }),
    );
    svg.append(
      svgNode("path", {
        d: "M 49 23 H91 L80 109 H48 Z M 115 23 H155 V109 H123 Z",
        fill: "#d4d9bd",
        stroke,
        "stroke-width": 1.2,
      }),
    );
    for (let i = 0; i < 3; i++)
      svg.append(
        svgNode("path", {
          d: `M ${55 + i * 10} 25 L ${51 + i * 10} 105 M ${123 + i * 10} 25 L ${127 + i * 10} 105`,
          stroke: "#aeb996",
          "stroke-width": 0.8,
        }),
      );
  } else {
    svg.append(
      svgNode("path", {
        d: "M 57 31 L131 22 L150 35 V110 L77 121 L57 105 Z",
        fill,
        stroke,
        "stroke-width": 1.3,
      }),
    );
    svg.append(
      svgNode("path", {
        d: "M 57 31 L77 43 L150 35 M77 43 V121 M113 39 V116",
        stroke,
        "stroke-width": 1.1,
        fill: "none",
      }),
    );
    svg.append(
      svgNode("path", {
        d: "M 106 72 V84 M120 71 V83",
        stroke,
        "stroke-width": 1.8,
      }),
    );
  }
  holder.append(
    svg,
    node("span", { class: "illustration-note" }, "Category sketch"),
  );
  return holder;
}

function evaluationLabel(product) {
  const evaluation = product.evaluation || {};
  if (evaluation.eligible) return ["Fits your plan & price", ""];
  if (evaluation.fit === "fail") return ["Doesn’t fit this place", "blocked"];
  if (product.is_demo || product.latest_observation?.source === "demo")
    return ["Demo · no deal alert", "waiting"];
  if (evaluation.fit === "pass")
    return ["Fits · still checking the details", "waiting"];
  return ["A few details to confirm", "waiting"];
}

function productMetadata(product) {
  const keys = [
    "id",
    "name",
    "url",
    "item_id",
    "width_cm",
    "depth_cm",
    "height_cm",
    "rotation_allow90",
    "variant",
    "color",
    "retailer",
    "sku",
    "identity_notes",
    "variant_confirmed",
    "price_eur",
    "shipping_eur",
    "target_eur",
    "availability",
    "monitor",
    "is_demo",
  ];
  return Object.fromEntries(
    keys.filter((key) => key in product).map((key) => [key, product[key]]),
  );
}

async function checkProduct(productId, button) {
  const oldText = button.textContent;
  button.disabled = true;
  button.textContent = "Checking…";
  try {
    await flushRoom();
    await api(`/api/products/${encodeURIComponent(productId)}/check`, {
      method: "POST",
      body: "{}",
    });
    await reload();
    toast(
      "Price check recorded. Review delivery, stock and variant before buying.",
    );
  } catch (error) {
    await reload().catch(() => {});
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = oldText;
  }
}

async function downloadData(path) {
  try {
    if (itemDrafts.size)
      throw new Error(
        "Correct the invalid item fields to include your latest room edits.",
      );
    do {
      await flushRoom();
      await flushFlat({ requireSaved: true });
    } while (savedRevision < mutationRevision || flatSavingPromise);
    if (itemDrafts.size)
      throw new Error(
        "Correct the invalid item fields to include your latest room edits.",
      );
  } catch (error) {
    showBackupRecovery(error);
    toast(
      `Export stopped because your latest changes could not be saved. ${error.message}`,
      true,
    );
    return;
  }
  try {
    await downloadExport(path);
  } catch (error) {
    toast(`Export failed. ${error.message}`, true);
  }
}

async function downloadExport(path) {
  if (window.roomiesBrowser) return window.roomiesBrowser.download(path);
  const response = await fetch(path);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(
      data.error || `The export request failed (${response.status}).`,
    );
  }
  const format = new URL(path, window.location.href).searchParams.get("format");
  const filename =
    {
      csv: "roomies-price-history.csv",
      expenses: "roomies-expense-shares.csv",
      repayments: "roomies-repayments.csv",
    }[format] || "roomies-backup.json";
  const url = URL.createObjectURL(await response.blob());
  const link = node("a", { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function showBackupRecovery(error) {
  let recovery = $("#backup-recovery");
  if (!recovery) {
    recovery = node("div", {
      id: "backup-recovery",
      class: "sample-note",
      role: "alert",
    });
    const content = node("div");
    content.append(
      node(
        "p",
        {},
        "Latest edits are not saved. This backup contains only the last saved workspace and excludes those edits.",
      ),
    );
    const button = node(
      "button",
      { type: "button", class: "small-button", id: "export-saved-backup" },
      "Export last saved backup",
    );
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await downloadExport("/api/export?format=json");
        toast(
          "Last saved backup exported. Your latest edits are still unsaved.",
          true,
        );
      } catch (failure) {
        toast(
          `The last saved backup could not be exported. ${failure.message}`,
          true,
        );
      } finally {
        button.disabled = false;
      }
    });
    content.append(button);
    recovery.append(content);
    $("#data-dialog .data-actions").before(recovery);
  }
  recovery.hidden = false;
  recovery.title = error.message;
}

function renderWishlist() {
  if (!state) return;
  const root = $("#wishlist-grid");
  root.replaceChildren();
  const products = state.products.filter(
    (product) =>
      wishlistFilter === "all" ||
      (wishlistFilter === "ready"
        ? product.evaluation?.eligible
        : !product.evaluation?.eligible),
  );
  $("#wishlist-empty").hidden = state.products.length > 0;
  if (!products.length && state.products.length)
    root.append(node("p", { class: "muted" }, "No finds in this view yet."));
  for (const product of products) {
    const item = itemById(product.item_id),
      card = node("article", { class: "product-card" });
    card.append(productIllustration(product, item));
    const body = node("div", { class: "product-card-content" });
    body.append(
      node("h2", {}, product.name),
      node(
        "p",
        { class: "product-variant" },
        [product.variant, product.color].filter(Boolean).join(" · "),
      ),
    );
    const priceRow = node("div", { class: "price-row" });
    const delivered = product.evaluation?.delivered_eur;
    const price = node(
      "div",
      { class: "product-price" },
      delivered === null || delivered === undefined ? "—" : money(delivered),
    );
    price.append(
      node(
        "small",
        {},
        delivered === null || delivered === undefined
          ? "delivered price not confirmed"
          : "including known delivery",
      ),
    );
    const target = append(
      node("div", { class: "target-price" }, "your target"),
      node("strong", {}, money(product.target_eur)),
    );
    append(priceRow, price, target);
    body.append(priceRow);
    const [label, klass] = evaluationLabel(product);
    body.append(node("span", { class: `eligibility-pill ${klass}` }, label));
    const reasons = node("div", { class: "product-reasons" });
    const reasonList = product.evaluation?.reasons || [
      "Record a price and confirm the exact variant.",
    ];
    reasonList
      .slice(0, 3)
      .forEach((reason) => reasons.append(node("p", {}, reason)));
    if (reasonList.length > 3)
      reasons.append(
        node(
          "p",
          {},
          `+ ${reasonList.length - 3} more checks in the price journal`,
        ),
      );
    body.append(reasons);
    const watchRow = node("div", { class: "product-watch-row" });
    const watch = node("label", { class: "watch-label" });
    const checkbox = node("input", { type: "checkbox" });
    checkbox.checked = Boolean(product.monitor);
    watch.append(checkbox, document.createTextNode("Watch this link"));
    checkbox.addEventListener("change", async () => {
      checkbox.disabled = true;
      try {
        const payload = productMetadata(product);
        payload.monitor = checkbox.checked;
        await api("/api/products", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        await reload();
        toast(
          checkbox.checked
            ? "Watch enabled. Supported links are checked while the local server runs."
            : "Watch paused for this product.",
        );
      } catch (error) {
        checkbox.checked = !checkbox.checked;
        toast(error.message, true);
      } finally {
        checkbox.disabled = false;
      }
    });
    const check = node(
      "button",
      { type: "button", class: "text-button" },
      "↻ Check price",
    );
    check.addEventListener("click", () => checkProduct(product.id, check));
    append(watchRow, watch, check);
    body.append(watchRow);
    const source = node("p", { class: "product-source" });
    if (product.latest_observation)
      source.append(
        document.createTextNode(
          `Last observation ${friendlyDate(product.latest_observation.observed_at)}`,
        ),
      );
    else source.append(document.createTextNode("No price observations yet"));
    if (product.is_demo)
      source.append(node("span", { class: "demo-label" }, "DEMO"));
    body.append(source);
    const footer = node("div", { class: "product-footer" });
    const record = node("button", { type: "button" }, "+ Record price");
    record.addEventListener("click", () => openObservation(product.id));
    const details = node("button", { type: "button" }, "Details");
    details.addEventListener("click", () =>
      openProduct(product.item_id, product.id),
    );
    const href = safeUrl(product.url);
    const store = href
      ? node(
          "a",
          { href, target: "_blank", rel: "noopener noreferrer" },
          "Store ↗",
        )
      : null;
    append(footer, record, details, store);
    body.append(footer);
    const journal = node(
      "button",
      { type: "button", class: "text-button full-width" },
      "See price history →",
    );
    journal.addEventListener("click", () => {
      selectedJournalId = product.id;
      showView("journal");
    });
    body.append(journal);
    card.append(body);
    root.append(card);
  }
  $("#wish-count").textContent = String(state.products.length);
}

function openProduct(itemId = null, editId = null) {
  const form = $("#product-form");
  form.reset();
  productEditId = editId;
  const product = productById(editId);
  const products = state.room.items.filter((item) => item.status === "planned");
  const options = products.length
    ? state.room.items.filter(
        (item) =>
          item.status === "planned" ||
          item.id === product?.item_id ||
          item.id === itemId,
      )
    : state.room.items;
  form.elements.item_id.replaceChildren(
    node("option", { value: "" }, "Choose a reserved place"),
    ...options.map((item) =>
      node(
        "option",
        { value: item.id },
        `${item.name}${item.status !== "planned" ? " (owned)" : ""}`,
      ),
    ),
  );
  form.elements.item_id.value = itemId || "";
  const item = itemById(itemId);
  if (item) form.elements.target_price.value = item.target_eur || "";
  $("#product-dialog-title").textContent = editId
    ? "The details of this find"
    : "Add a find";
  if (product) {
    for (const key of [
      "name",
      "url",
      "width_cm",
      "depth_cm",
      "height_cm",
      "color",
      "variant",
      "retailer",
      "sku",
    ])
      form.elements.namedItem(key).value = product[key] ?? "";
    form.elements.item_id.value = product.item_id;
    form.elements.target_price.value = product.target_eur;
    form.elements.notes.value = product.identity_notes || "";
    form.elements.variant_confirmed.checked = Boolean(
      product.variant_confirmed,
    );
    form.elements.rotation_allow90.checked = product.rotation_allow90 !== false;
    form.elements.monitor.checked = Boolean(product.monitor);
  }
  $("#delete-product").hidden = !product;
  $("#product-error").hidden = true;
  $("#product-dialog").showModal();
}

async function saveProduct(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  const payload = {
    name: formValue(form, "name"),
    item_id: formValue(form, "item_id"),
    url: formValue(form, "url"),
    width_cm: Number(formValue(form, "width_cm")),
    depth_cm: Number(formValue(form, "depth_cm")),
    height_cm: nullableNumber(formValue(form, "height_cm")),
    target_eur: Number(formValue(form, "target_price")),
    color: formValue(form, "color"),
    variant: formValue(form, "variant"),
    variant_confirmed: form.elements.variant_confirmed.checked,
    rotation_allow90: form.elements.rotation_allow90.checked,
    identity_notes: formValue(form, "notes"),
    currency: "EUR",
    monitor: form.elements.monitor.checked,
    is_demo: false,
  };
  payload.sku = formValue(form, "sku");
  payload.retailer = formValue(form, "retailer");
  const button = $("button[type=submit]", form);
  button.disabled = true;
  try {
    await flushRoom();
    if (productEditId) payload.id = productEditId;
    await api("/api/products", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    $("#product-dialog").close();
    await reload();
    showView("wishlist");
    toast(
      productEditId
        ? "Find updated. Its fit and price checks were recalculated."
        : "Find saved. Record a price whenever you have checked it.",
    );
  } catch (error) {
    $("#product-error").textContent = error.message;
    $("#product-error").hidden = false;
  } finally {
    button.disabled = false;
  }
}

function localDateValue(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}
function openObservation(productId = null) {
  if (!state.products.length) {
    toast("Add a product to your wishlist first.");
    showView("wishlist");
    return;
  }
  const form = $("#observation-form");
  form.reset();
  form.elements.product_id.replaceChildren(
    ...state.products.map((product) =>
      node("option", { value: product.id }, product.name),
    ),
  );
  form.elements.product_id.value =
    productId || selectedJournalId || state.products[0].id;
  form.elements.observed_at.value = localDateValue();
  form.elements.observed_at.max = localDateValue();
  form.elements.source_url.value =
    productById(form.elements.product_id.value)?.url || "";
  $("#observation-error").hidden = true;
  $("#observation-dialog").showModal();
}

async function saveObservation(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  const productId = formValue(form, "product_id");
  const payload = {
    observed_at: new Date(formValue(form, "observed_at")).toISOString(),
    price_eur: Number(formValue(form, "price")),
    shipping_eur: nullableNumber(formValue(form, "shipping")),
    currency: "EUR",
    availability: formValue(form, "availability"),
    variant_confirmed: form.elements.variant_confirmed.checked,
    source_url: formValue(form, "source_url"),
    notes: formValue(form, "notes"),
    is_demo: false,
  };
  const button = $("button[type=submit]", form);
  button.disabled = true;
  try {
    await flushRoom();
    await api(`/api/products/${encodeURIComponent(productId)}/observations`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    selectedJournalId = productId;
    $("#observation-dialog").close();
    await reload();
    toast("Observation recorded with its source and variant check.");
  } catch (error) {
    $("#observation-error").textContent = error.message;
    $("#observation-error").hidden = false;
  } finally {
    button.disabled = false;
  }
}

function observationsFor(product) {
  return [...(product?.observations || [])].sort(
    (a, b) => new Date(a.observed_at) - new Date(b.observed_at),
  );
}
function deliveredObservation(observation) {
  return observation.price_eur !== null &&
    observation.price_eur !== undefined &&
    observation.shipping_eur !== null &&
    observation.shipping_eur !== undefined
    ? Number(observation.price_eur) + Number(observation.shipping_eur)
    : null;
}

function renderJournal() {
  if (!state) return;
  const select = $("#journal-product");
  if (!productById(selectedJournalId))
    selectedJournalId = state.products[0]?.id || null;
  select.replaceChildren(
    ...state.products.map((product) =>
      node("option", { value: product.id }, product.name),
    ),
  );
  if (!state.products.length)
    select.append(node("option", { value: "" }, "No products yet"));
  select.value = selectedJournalId || "";
  select.disabled = !state.products.length;
  const product = productById(selectedJournalId);
  renderPriceChart(product);
  renderHistory(product);
  renderNotifications();
  renderTracker();
}

function renderPriceChart(product) {
  const root = $("#price-chart");
  root.replaceChildren();
  const observations = observationsFor(product).filter(
    (observation) => deliveredObservation(observation) !== null,
  );
  $("#chart-caption").textContent = product?.is_demo
    ? "Demo observations are illustrations, not retailer offers."
    : "Only observations with a known product and delivery price are plotted. Entries are not a full market history.";
  if (!observations.length) {
    root.append(
      node(
        "div",
        { class: "chart-empty" },
        product
          ? "Record a product price and known delivery cost to start your price history."
          : "Your first find will start its own price story here.",
      ),
    );
    return;
  }
  const svg = svgNode("svg", {
    viewBox: "0 0 620 250",
    role: "img",
    "aria-label": `Delivered-price history for ${product.name}. ${observations.length} observations. Latest ${money(deliveredObservation(observations.at(-1)))}`,
  });
  const values = observations.map(deliveredObservation),
    target = Number(product.target_eur || 0);
  const lower = Math.min(...values, ...(target > 0 ? [target] : []));
  const upper = Math.max(...values, target);
  const range = Math.max(upper - lower, Math.max(10, upper * 0.12));
  const min = Math.max(0, lower - range * 0.25),
    max = upper + range * 0.2;
  const left = 62,
    right = 598,
    top = 23,
    bottom = 202;
  const dates = observations.map((observation) =>
      new Date(observation.observed_at).getTime(),
    ),
    first = Math.min(...dates),
    last = Math.max(...dates);
  const x = (value) =>
    first === last
      ? (left + right) / 2
      : left + ((value - first) / (last - first)) * (right - left);
  const y = (value) => bottom - ((value - min) / (max - min)) * (bottom - top);
  for (let i = 0; i < 4; i++) {
    const value = min + ((max - min) * i) / 3,
      cy = y(value);
    svg.append(
      svgNode("line", {
        x1: left,
        y1: cy,
        x2: right,
        y2: cy,
        stroke: "#e7ecdd",
        "stroke-width": 1,
      }),
    );
    svg.append(
      svgNode(
        "text",
        {
          x: left - 12,
          y: cy + 4,
          "text-anchor": "end",
          fill: "#9ba58c",
          "font-size": 10,
          "font-family": "Segoe UI,Arial,sans-serif",
        },
        money(value),
      ),
    );
  }
  if (target > 0) {
    const ty = y(target);
    svg.append(
      svgNode("line", {
        x1: left,
        y1: ty,
        x2: right,
        y2: ty,
        stroke: "#c79568",
        "stroke-width": 1,
        "stroke-dasharray": "5 4",
      }),
    );
    svg.append(
      svgNode(
        "text",
        {
          x: right,
          y: Math.max(top + 9, ty - 6),
          "text-anchor": "end",
          fill: "#b2875c",
          "font-size": 9,
          "font-family": "Segoe UI,Arial,sans-serif",
        },
        `Your target ${money(target)}`,
      ),
    );
  }
  const path = observations
    .map(
      (observation, index) =>
        `${index ? "L" : "M"} ${x(dates[index])} ${y(values[index])}`,
    )
    .join(" ");
  if (observations.length > 1) {
    svg.append(
      svgNode("path", {
        d: `${path} L ${x(dates.at(-1))} ${bottom} L ${x(dates[0])} ${bottom} Z`,
        fill: "#e4eed8",
        opacity: 0.7,
      }),
    );
    svg.append(
      svgNode("path", {
        d: path,
        fill: "none",
        stroke: "#759a5a",
        "stroke-width": 2.2,
        "stroke-linejoin": "round",
      }),
    );
  }
  observations.forEach((observation, index) => {
    const dot = svgNode("circle", {
      cx: x(dates[index]),
      cy: y(values[index]),
      r: 4,
      fill: observation.source === "demo" ? "#c39d71" : "#7b9d5b",
      stroke: "#fffefa",
      "stroke-width": 2,
    });
    dot.append(
      svgNode(
        "title",
        {},
        `${friendlyDate(observation.observed_at)} · ${money(values[index])}${observation.source === "demo" ? " · DEMO" : ""}`,
      ),
    );
    svg.append(dot);
  });
  const labels = dates.length > 1 ? [dates[0], dates.at(-1)] : [dates[0]];
  labels.forEach((date) =>
    svg.append(
      svgNode(
        "text",
        {
          x: x(date),
          y: 229,
          "text-anchor": "middle",
          fill: "#97a388",
          "font-size": 9,
          "font-family": "Segoe UI,Arial,sans-serif",
        },
        new Date(date).toLocaleDateString("en-GB", {
          day: "numeric",
          month: "short",
        }),
      ),
    ),
  );
  root.append(svg);
}

function renderHistory(product) {
  const root = $("#history-body");
  root.replaceChildren();
  const observations = observationsFor(product).reverse();
  if (!observations.length) {
    const row = node("tr");
    row.append(
      node(
        "td",
        { colspan: 7 },
        "No observations yet. A recorded price always keeps its source.",
      ),
    );
    root.append(row);
    return;
  }
  for (const observation of observations) {
    const row = node("tr"),
      source = node("td");
    const href = safeUrl(observation.source_url);
    if (href) {
      const a = node(
        "a",
        { href, target: "_blank", rel: "noopener noreferrer" },
        observation.source === "manual"
          ? "Manual entry ↗"
          : observation.source === "demo"
            ? "Demo entry ↗"
            : "Public page ↗",
      );
      source.append(a);
    } else source.textContent = observation.source || "Not recorded";
    append(
      row,
      node("td", {}, friendlyDate(observation.observed_at)),
      node("td", {}, money(observation.price_eur)),
      node("td", {}, money(observation.shipping_eur)),
      append(
        node("td"),
        node("strong", {}, money(deliveredObservation(observation))),
      ),
      node(
        "td",
        {},
        observation.availability === "in_stock"
          ? "In stock"
          : observation.availability === "out_of_stock"
            ? "Out of stock"
            : "Unknown",
      ),
      source,
      node(
        "td",
        {},
        observation.variant_confirmed ? "Confirmed" : "Not confirmed",
      ),
    );
    if (observation.notes || observation.note)
      row.title = observation.notes || observation.note;
    root.append(row);
  }
}

function renderTracker() {
  const root = $("#tracker-status");
  root.replaceChildren();
  const tracker = state.tracker || {};
  if (tracker.mode === "browser") {
    root.append(node("p", {}, tracker.description));
    return;
  }
  root.append(
    append(
      node("p"),
      node(
        "strong",
        {},
        tracker.background_running
          ? "Local scheduler is running."
          : "Scheduled checks are stopped.",
      ),
    ),
  );
  root.append(
    node(
      "p",
      {},
      tracker.description ||
        "Use Check price to request a public-page check, or record a price manually.",
    ),
  );
  const monitored = state.products.filter(
    (product) => product.monitor && !product.is_demo,
  ).length;
  root.append(
    node(
      "p",
      {},
      `${monitored} ${monitored === 1 ? "link is" : "links are"} being watched.`,
    ),
  );
  if (tracker.next_check_at)
    root.append(
      node("p", {}, `Next due: ${friendlyDate(tracker.next_check_at)}`),
    );
  root.append(
    node(
      "p",
      {},
      "Price alerts appear in this workspace. This app does not send email or browser push notifications.",
    ),
  );
  const product = productById(selectedJournalId);
  if (product?.last_check_error || product?.error)
    root.append(
      node(
        "p",
        {},
        `Last product check: ${product.last_check_error || product.error}`,
      ),
    );
  if (product?.evaluation?.reasons?.length) {
    root.append(node("strong", {}, "Checks for this find"));
    product.evaluation.reasons.forEach((reason) =>
      root.append(node("p", {}, `• ${reason}`)),
    );
  }
}

function renderNotifications() {
  const root = $("#notification-list");
  root.replaceChildren();
  const unread = state.notifications.filter(
    (notification) => !notification.read,
  ).length;
  $("#notification-count").textContent = `${unread} new`;
  if (!state.notifications.length) {
    root.append(
      node(
        "p",
        { class: "no-notifications" },
        "No updates yet. A price drop is recorded separately from a find that passes all the purchase checks.",
      ),
    );
    return;
  }
  for (const notification of [...state.notifications].reverse()) {
    const informational =
      notification.type === "price_drop_info" ||
      notification.type === "price_drop";
    const row = node("div", { class: "notification-row" }),
      content = node("div");
    content.append(
      node(
        "span",
        { class: `eligibility-pill ${informational ? "waiting" : ""}` },
        informational ? "Item price changed" : "Fits plan & target",
      ),
      node("h3", {}, notification.message),
      node("small", {}, friendlyDate(notification.created_at)),
    );
    append(
      row,
      node(
        "span",
        {
          class: `check-icon ${informational ? "warning" : ""}`,
          "aria-hidden": "true",
        },
        informational ? "↓" : "✓",
      ),
      content,
    );
    if (!notification.read) {
      const button = node(
        "button",
        { type: "button", class: "small-button" },
        "Mark read",
      );
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await api(
            `/api/notifications/${encodeURIComponent(notification.id)}/read`,
            {
              method: "POST",
              body: "{}",
            },
          );
          await reload();
        } catch (error) {
          toast(error.message, true);
          button.disabled = false;
        }
      });
      row.append(button);
    }
    root.append(row);
  }
}

async function checkAll(button) {
  if (!state.products.length) {
    toast("Add a product link before running a check.");
    return;
  }
  if (!state.products.some((product) => product.monitor)) {
    toast(
      "Enable “Watch this link” for a product, or use its individual Check price button.",
    );
    return;
  }
  button.disabled = true;
  const previous = button.textContent;
  button.textContent = "Checking public pages…";
  try {
    await flushRoom();
    const result = await api("/api/check-all", { method: "POST", body: "{}" });
    await reload();
    const failures = result.errors?.length || 0;
    toast(
      failures
        ? `Check finished. ${failures} ${failures === 1 ? "link needs" : "links need"} attention; previous prices were kept.`
        : `Checked ${result.checked ?? state.products.length} product ${result.checked === 1 ? "link" : "links"}.`,
      Boolean(failures),
    );
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = previous;
  }
}

function downloadPlan() {
  const clone = $("#room-plan").cloneNode(true);
  clone.setAttribute("xmlns", SVG_NS);
  const styles = svgNode(
    "style",
    {},
    ".room-dimension{fill:#8c987e;font:11px Arial}.room-text{fill:#9aa58a;font:9px Arial}.north-arrow{fill:#8e9b7e}.furniture-text{font-family:Arial}.selection-ring{display:none}",
  );
  clone.insertBefore(styles, clone.firstChild);
  clone.removeAttribute("tabindex");
  const blob = new Blob([new XMLSerializer().serializeToString(clone)], {
    type: "image/svg+xml;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = node("a", { href: url, download: "roomies-room-plan.svg" });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function readImport(event) {
  const file = event.target.files[0];
  importCandidate = null;
  $("#import-preview").hidden = true;
  $("#import-error").hidden = true;
  if (!file) return;
  try {
    if (file.size > MAX_BACKUP_BYTES)
      throw new Error(
        "This backup is larger than 32 MiB. Roomies backups must stay within 32 MiB.",
      );
    const data = JSON.parse(await file.text());
    if (
      !data.room ||
      !Array.isArray(data.room.items) ||
      !Array.isArray(data.products)
    )
      throw new Error(
        "This file needs a room, an items array and a products array.",
      );
    importCandidate = data;
    const flatCopy =
      data.schema_version >= 2 && data.flat
        ? ` Its flat contains ${data.flat.members?.length || 0} people, ${data.flat.inventory?.length || 0} belongings, ${data.flat.expenses?.length || 0} shared costs and ${data.flat.repayments?.length || 0} repayments. The room, price journal and flat will be replaced.${data.schema_version === 2 && (!data.flat.repayments || !data.flat.monthly_bills) ? " This older backup has no repayments or monthly bills; those lists will be cleared." : ""}`
        : " This is a room-only backup: the room and price journal will be replaced; your current flat, kitchen and shared costs stay unchanged.";
    $("#import-description").textContent =
      `This file contains “${data.room.name || "a room"}”, ${data.room.items.length} room items and ${data.products.length} products.${flatCopy}`;
    $("#import-preview").hidden = false;
  } catch (error) {
    $("#import-error").textContent = error.message;
    $("#import-error").hidden = false;
  }
}

async function confirmImport() {
  if (!importCandidate) return;
  const button = $("#confirm-import");
  button.disabled = true;
  try {
    // Confirmed replacement can recover from a failed save; drain active writes first.
    await flushRoom().catch(() => {});
    await flushFlat().catch(() => {});
    await api("/api/import", {
      method: "POST",
      body: JSON.stringify(importCandidate),
    });
    selectedId = null;
    selectedJournalId = null;
    itemDrafts.clear();
    mutationRevision += 1;
    savedRevision = mutationRevision;
    if (importCandidate.schema_version >= 2 && importCandidate.flat)
      flatSaveError = null;
    await reload();
    $("#data-dialog").close();
    toast(
      "Workspace imported. Check the room and linked finds before using them.",
    );
  } catch (error) {
    $("#import-error").textContent = error.message;
    $("#import-error").hidden = false;
  } finally {
    button.disabled = false;
  }
}

function wireEvents() {
  wireHouseholdEvents();
  $$("[data-view]").forEach((button) =>
    button.addEventListener("click", () => showView(button.dataset.view)),
  );
  $$(".close-dialog").forEach((button) =>
    button.addEventListener("click", () => button.closest("dialog").close()),
  );
  $("#room-settings-top").addEventListener("click", openRoomSettings);
  $("#sample-settings").addEventListener("click", openRoomSettings);
  $("#show-clearance").addEventListener("change", () => renderPlan());
  $("#add-item").addEventListener("click", addItem);
  $("#add-item-bottom").addEventListener("click", addItem);
  $("#item-form").addEventListener("submit", (event) => event.preventDefault());
  $("#item-form").addEventListener("input", updateItemFromForm);
  $("#item-form").elements.placement.addEventListener("change", () => {
    updatePlacementFields();
    updateItemFromForm();
  });
  $("#rotate-item").addEventListener("click", () => {
    const item = itemById(selectedId);
    if (!item) return;
    if (itemDrafts.has(item.id)) {
      toast("Fix this item's invalid fields before rotating it.", true);
      return;
    }
    item.rotation = Number(item.rotation) === 90 ? 0 : 90;
    renderAll();
    markDirty();
  });
  $("#delete-item").addEventListener("click", () => {
    const item = itemById(selectedId);
    if (!item) return;
    const children = state.room.items.filter(
      (candidate) => candidate.parent_id === item.id,
    );
    if (children.length) {
      toast(
        `Move or remove ${children.map((child) => child.name).join(", ")} first; ${item.name} is their parent.`,
        true,
      );
      return;
    }
    if (
      !window.confirm(
        `Remove “${item.name}” from the plan? Linked products will need a new reserved place.`,
      )
    )
      return;
    state.room.items = state.room.items.filter(
      (candidate) => candidate.id !== item.id,
    );
    itemDrafts.delete(item.id);
    selectedId = state.room.items[0]?.id || null;
    renderAll();
    markDirty();
  });
  $("#suggest-positions").addEventListener("click", suggestPositions);
  $("#shop-item").addEventListener("click", () => openProduct(selectedId));
  $("#room-plan").addEventListener("pointermove", dragMove);
  $("#room-plan").addEventListener("pointerup", endDrag);
  $("#room-plan").addEventListener("pointercancel", endDrag);
  $("#download-plan").addEventListener("click", downloadPlan);
  $("#room-settings-form").addEventListener("submit", saveRoomSettings);
  $("#add-opening").addEventListener("click", () => {
    settingsOpenings.push({
      id: id("opening"),
      kind: "door",
      wall: "north",
      offset_cm: 0,
      width_cm: 80,
      depth_cm: 80,
      swing: "in",
    });
    renderOpeningsEditors();
  });
  $("#add-obstacle").addEventListener("click", () => {
    settingsOpenings.push({
      id: id("obstacle"),
      kind: "obstacle",
      wall: "west",
      offset_cm: 100,
      width_cm: 40,
      depth_cm: 30,
      swing: "none",
    });
    renderOpeningsEditors();
  });
  $("#add-product").addEventListener("click", () => openProduct());
  $("#add-product-empty").addEventListener("click", () => openProduct());
  $("#product-form").addEventListener("submit", saveProduct);
  $("#delete-product").addEventListener("click", async () => {
    const product = productById(productEditId);
    if (
      !product ||
      !window.confirm(`Remove “${product.name}” and its saved observations?`)
    )
      return;
    try {
      await api(`/api/products/${encodeURIComponent(product.id)}`, {
        method: "DELETE",
      });
      $("#product-dialog").close();
      await reload();
      toast("Find removed from your wishlist.");
    } catch (error) {
      $("#product-error").textContent = error.message;
      $("#product-error").hidden = false;
    }
  });
  $("#product-form").elements.item_id.addEventListener("change", (event) => {
    const item = itemById(event.target.value);
    if (item && !$("#product-form").elements.target_price.value)
      $("#product-form").elements.target_price.value = item.target_eur || "";
  });
  $("#observation-form").addEventListener("submit", saveObservation);
  $("#observation-form").elements.product_id.addEventListener(
    "change",
    (event) => {
      $("#observation-form").elements.source_url.value =
        productById(event.target.value)?.url || "";
    },
  );
  $("#journal-add-observation").addEventListener("click", () =>
    openObservation(selectedJournalId),
  );
  $("#journal-product").addEventListener("change", (event) => {
    selectedJournalId = event.target.value;
    renderJournal();
  });
  $$("[data-wish-filter]").forEach((button) =>
    button.addEventListener("click", () => {
      wishlistFilter = button.dataset.wishFilter;
      $$("[data-wish-filter]").forEach((candidate) =>
        candidate.classList.toggle("active", candidate === button),
      );
      renderWishlist();
    }),
  );
  $("#check-all").addEventListener("click", (event) =>
    checkAll(event.currentTarget),
  );
  $("#journal-check-all").addEventListener("click", (event) =>
    checkAll(event.currentTarget),
  );
  $("#export-prices").addEventListener("click", () =>
    downloadData("/api/export?format=csv"),
  );
  $$("a[href^='/api/export']").forEach((link) =>
    link.addEventListener("click", (event) => {
      event.preventDefault();
      downloadData(link.getAttribute("href"));
    }),
  );
  [$("#data-menu-button"), $("#data-menu-top")].forEach((button) =>
    button.addEventListener("click", () => {
      $("#import-preview").hidden = true;
      $("#import-error").hidden = true;
      $("#data-dialog").showModal();
    }),
  );
  $("#import-file").addEventListener("change", readImport);
  $("#confirm-import").addEventListener("click", confirmImport);
  window.addEventListener("beforeunload", (event) => {
    if (
      savedRevision < mutationRevision ||
      flatSavingPromise ||
      flatSaveError ||
      itemDrafts.size
    ) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
}

async function start() {
  wireEvents();
  setWorkspaceAvailable(false);
  try {
    await reload();
    setWorkspaceAvailable(true);
    setInterval(pollWorkspace, 30000);
  } catch (error) {
    $("#load-error").textContent =
      `Could not load the workspace. ${error.message}${window.roomiesBrowser ? "" : " Refresh once the local server is running."}`;
    $("#load-error").hidden = false;
    setSaveStatus("Workspace unavailable", "error");
  }
}

function setWorkspaceAvailable(available) {
  const controls = [
    "add-item",
    "add-item-bottom",
    "add-product",
    "add-product-empty",
    "journal-add-observation",
    "check-all",
    "journal-check-all",
    "download-plan",
    "data-menu-button",
    "data-menu-top",
    "room-settings-top",
    "sample-settings",
    "room-settings-local",
    "flat-settings-button",
    "flat-setup-button",
    "expense-people-button",
    "add-flat-item",
    "add-kitchen-item",
    "add-fridge-item",
    "add-expense",
    "export-expenses",
    "add-monthly-bill",
  ];
  controls.forEach((identity) => {
    const control = document.getElementById(identity);
    if (control) control.disabled = !available;
  });
}

async function pollWorkspace() {
  if (
    document.hidden ||
    dragging ||
    savingPromise ||
    flatSavingPromise ||
    mutationRevision !== savedRevision ||
    $$("dialog").some((dialog) => dialog.open)
  )
    return;
  try {
    const revision = mutationRevision,
      flatVersion = flatRevision,
      refreshed = await api("/api/state");
    if (
      revision !== mutationRevision ||
      flatVersion !== flatRevision ||
      dragging ||
      savingPromise ||
      flatSavingPromise ||
      $$("dialog").some((dialog) => dialog.open)
    )
      return;
    const previousUnread = new Set(
      state.notifications
        .filter((notification) => !notification.read)
        .map((notification) => notification.id),
    );
    state.products = refreshed.products || [];
    state.notifications = refreshed.notifications || [];
    state.tracker = refreshed.tracker;
    state.flat = refreshed.flat || state.flat;
    state.flat_summary = refreshed.flat_summary || state.flat_summary;
    renderWishlist();
    renderJournal();
    renderHousehold();
    const newAlerts = state.notifications.filter(
      (notification) =>
        !notification.read && !previousUnread.has(notification.id),
    );
    if (newAlerts.length)
      toast(
        `${newAlerts.length} new ${newAlerts.length === 1 ? "price update" : "price updates"}. See the price journal.`,
      );
  } catch {
    setSaveStatus("Saved locally · update check failed", "error");
  }
}
start();
