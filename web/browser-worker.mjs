import { loadPyodide } from "./vendor/pyodide/pyodide.mjs";

const databasePath = "/roomies.sqlite3";
let python;
let workspace;
let database;
let queue = Promise.resolve();

function openDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("roomies-browser-v1", 1);
    request.onupgradeneeded = () =>
      request.result.createObjectStore("workspace");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () =>
      reject(
        new Error(
          "Browser storage is unavailable. Enable site storage, then reload.",
        ),
      );
    request.onblocked = () =>
      reject(new Error("Close other Roomies tabs, then reload."));
  });
}

function storedDatabase(bytes) {
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(
      "workspace",
      bytes ? "readwrite" : "readonly",
    );
    const store = transaction.objectStore("workspace");
    const request = bytes ? store.put(bytes, "main") : store.get("main");
    transaction.oncomplete = () => resolve(request.result);
    transaction.onabort = transaction.onerror = () =>
      reject(
        new Error(
          "Your browser could not save this change. Export a backup and free some storage before trying again.",
        ),
      );
  });
}

async function initialize() {
  self.postMessage({
    progress: "Loading your workspace… The first visit may take a few seconds.",
  });
  database = await openDatabase();
  const saved = await storedDatabase();
  const sourceResponse = await fetch(
    new URL("./roomies-python.zip", import.meta.url),
  );
  if (!sourceResponse.ok)
    throw new Error(
      "The app files could not load. Check your connection and refresh.",
    );
  const source = await sourceResponse.arrayBuffer();
  python = await loadPyodide({
    indexURL: new URL("./vendor/pyodide/", import.meta.url).href,
  });
  python.unpackArchive(source, "zip", { extractDir: "/home/pyodide" });
  if (saved) python.FS.writeFile(databasePath, saved);
  workspace = python.runPython(
    "from roommate.browser import BrowserWorkspace\nBrowserWorkspace('/roomies.sqlite3')",
  );
  // A fresh workspace must also be durable before the editor is enabled.
  if (!saved) await storedDatabase(python.FS.readFile(databasePath));
  self.postMessage({ progress: "Your workspace is ready." });
}

async function handle({ id, path, method = "GET", body }) {
  try {
    if (!python) await initialize();
    const changesData = method !== "GET" && path !== "/api/suggest";
    const before = changesData ? python.FS.readFile(databasePath) : null;
    let result;
    try {
      result = JSON.parse(workspace.dispatch(path, method, body || null));
      if (result.error) throw new Error(result.error);
      if (changesData) await storedDatabase(python.FS.readFile(databasePath));
    } catch (error) {
      // Keep memory and persisted data identical when validation or storage fails.
      if (before) python.FS.writeFile(databasePath, before);
      throw error;
    }
    self.postMessage({ id, data: result.data });
  } catch (error) {
    self.postMessage({
      id,
      error: error.message || "The workspace could not load. Please refresh.",
    });
  }
}

self.onmessage = ({ data }) => {
  // The UI can request refreshes while a save is running. Never let them race.
  queue = queue.then(() => handle(data)).catch(() => {});
};
