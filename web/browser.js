/* This transport is included only in the shareable, device-local build. */
"use strict";

(() => {
  const pending = new Map();
  let sequence = 0;
  let worker;
  let failure;
  let activeRequests = 0;
  let releaseEditor;
  const status = (message) => {
    const element = document.querySelector("#browser-loading");
    if (element) element.textContent = message;
  };
  const fail = (error) => {
    failure = error;
    for (const { reject } of pending.values()) reject(error);
    pending.clear();
    worker?.terminate();
    status(error.message);
  };
  const editorReady = new Promise((resolve, reject) => {
    if (!navigator.locks || !window.Worker || !window.indexedDB) {
      reject(
        new Error(
          "Use a current Chrome, Edge, Firefox or Safari browser with site storage enabled.",
        ),
      );
      return;
    }
    navigator.locks
      .request(
        "roomies-workspace-editor",
        { ifAvailable: true },
        async (lock) => {
          if (!lock)
            throw new Error(
              "Roomies is already open in another tab. Close that tab, then refresh here.",
            );
          worker = new Worker(
            new URL("./browser-worker.mjs", document.baseURI),
            { type: "module" },
          );
          worker.onmessage = ({ data }) => {
            if (data.progress) {
              status(data.progress);
              return;
            }
            const request = pending.get(data.id);
            if (!request) return;
            pending.delete(data.id);
            if (data.error) request.reject(new Error(data.error));
            else request.resolve(data.data);
          };
          worker.onerror = () =>
            fail(
              new Error(
                "Roomies could not load its app files. Check your connection, then refresh.",
              ),
            );
          resolve();
          await new Promise((release) => {
            releaseEditor = release;
          });
        },
      )
      .catch(reject);
  });
  // Initialization errors are shown by the existing workspace error surface.
  editorReady.catch(() => {});
  window.roomiesBrowser = {
    async request(path, options = {}) {
      await editorReady;
      if (failure) throw failure;
      activeRequests++;
      try {
        return await new Promise((resolve, reject) => {
          const id = ++sequence;
          pending.set(id, { resolve, reject });
          worker.postMessage({
            id,
            path,
            method: options.method || "GET",
            body: options.body,
          });
        });
      } finally {
        activeRequests--;
      }
    },
    async download(path) {
      const result = await this.request(path);
      const url = URL.createObjectURL(
        new Blob([result.text], { type: result.type }),
      );
      const link = Object.assign(document.createElement("a"), {
        href: url,
        download: result.filename,
      });
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    },
  };
  window.addEventListener("beforeunload", (event) => {
    if (activeRequests) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  window.addEventListener("pagehide", () => {
    worker?.terminate();
    releaseEditor?.();
    fail(new Error("This workspace was closed. Refresh to continue."));
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload();
  });
  document.addEventListener("DOMContentLoaded", () => {
    document
      .querySelector("#share-roomies")
      .addEventListener("click", async () => {
        const url = new URL("./", window.location.href).href;
        try {
          if (navigator.share)
            await navigator.share({
              title: "Roomies",
              text: "My room. My things. Our flat. Try Roomies.",
              url,
            });
          else {
            await navigator.clipboard.writeText(url);
            status("Link copied. Send it to your friends!");
          }
        } catch (error) {
          if (error.name !== "AbortError") status(`Share this link: ${url}`);
        }
      });
    const context = document.modelContext;
    if (context?.registerTool) {
      const lifecycle = new AbortController();
      window.addEventListener("pagehide", () => lifecycle.abort(), {
        once: true,
      });
      try {
        Promise.resolve(
          context.registerTool(
            {
              name: "read_roomies_overview",
              title: "Read Roomies overview",
              description:
                "Read the saved room area, flat totals and shared-cost balances in this browser. Does not change records.",
              inputSchema: {
                type: "object",
                properties: {},
                additionalProperties: false,
              },
              annotations: { readOnlyHint: true, untrustedContentHint: true },
              async execute(input) {
                if (
                  !input ||
                  Array.isArray(input) ||
                  typeof input !== "object" ||
                  Object.keys(input).length
                )
                  throw new Error("Use an empty object.");
                const saved = await window.roomiesBrowser.request("/api/state");
                return {
                  room: {
                    name: saved.room.name,
                    area_m2: saved.summary.area_m2,
                    is_sample: saved.room.is_demo,
                  },
                  flat: saved.flat_summary,
                };
              },
            },
            { signal: lifecycle.signal },
          ),
        ).catch(() => {});
      } catch {
        /* Browsers without the optional API still use the full UI. */
      }
    }
  });
})();
