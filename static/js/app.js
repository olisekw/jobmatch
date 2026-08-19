/* Shared helpers: API wrapper, toast, scan overlay with status polling. */

const CSRF_TOKEN =
  document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

async function api(path, options = {}) {
  if (options.json !== undefined) {
    options.method = options.method || "POST";
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(options.json);
    delete options.json;
  }
  const method = (options.method || "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD") {
    // Flask-WTF looks for the token in this header when the body is JSON or a
    // FormData upload rather than a real <form>.
    options.headers = { ...(options.headers || {}), "X-CSRFToken": CSRF_TOKEN };
  }
  const res = await fetch(path, options);
  // An expired session answers every fetch with 401; sending the user to the
  // login page beats a toast on a page that can no longer load anything.
  if (res.status === 401) {
    window.location = "/login?next=" + encodeURIComponent(window.location.pathname);
    return new Promise(() => {});  // never resolves: the navigation is the outcome
  }
  const data = await res.json().catch(() => ({}));
  // The server phrases its own errors; anything else was never meant to be read.
  if (!res.ok) throw new Error(data.error || "Something went wrong — please try again.");
  return data;
}

let toastTimer;
function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3500);
}

/* ── Scan overlay ─────────────────────────────────────── */

const scanOverlay = {
  el: null,
  timer: null,
  watching: false,   // a scan was in progress the last time we looked

  init() {
    this.el = document.getElementById("scan-overlay");
    const cancel = document.getElementById("scan-cancel");
    if (cancel) {
      cancel.addEventListener("click", async () => {
        await api("/api/scan/cancel", { method: "POST" });
        document.getElementById("scan-phase").textContent = "Stopping…";
      });
    }
    // Reattach if a scan is already running (e.g. after page reload)
    this.poll(true);
  },

  async start() {
    try {
      await api("/api/scan/start", { method: "POST" });
    } catch (err) {
      toast(err.message);
      return;
    }
    this.open();
    this.schedule();
  },

  open() { this.el.classList.add("open"); },
  close() { this.el.classList.remove("open"); clearTimeout(this.timer); },

  schedule() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.poll(false), 2000);
  },

  async poll(initial) {
    let status;
    try {
      status = await api("/api/scan/status");
    } catch {
      if (!initial) this.schedule();
      return;
    }

    if (status.status === "running" || status.status === "queued") {
      // Scans are queued, not started, so a trigger shows "waiting for a
      // worker" for a poll or two before the phases start moving.
      if (window.CAN_SCAN) this.open();
      document.getElementById("scan-phase").textContent =
        status.cancelling ? "Stopping…" : (status.phase || "Working…");
      document.getElementById("scan-counts").textContent =
        `${plural(status.found, "new job")} · ${status.enriched} analyzed` +
        (status.failed ? ` · ${status.failed} could not be read` : "");
      this.schedule();
      this.watching = true;
      return;
    }

    // A scheduled scan finishing still refreshes the page for everyone; only
    // the person who could have started it gets told about it.
    if (!initial && !window.CAN_SCAN) {
      this.close();
      if (this.watching && typeof window.onScanFinished === "function") {
        window.onScanFinished();
      }
      this.watching = false;
      return;
    }

    if (!initial) {
      this.close();
      if (status.status === "done") {
        const boards = Object.keys(status.source_errors || {}).length;
        toast(
          `Scan finished — ${plural(status.found, "new job")}, ${status.enriched} analyzed` +
          (boards ? ` (${plural(boards, "board")} had trouble)` : "")
        );
      } else if (status.status === "cancelled") {
        toast("Scan cancelled.");
      } else if (status.status === "failed") {
        toast("The scan could not finish. Nothing already saved was lost.");
      }
      if (typeof window.onScanFinished === "function") window.onScanFinished();
    }
  },
};

/* ── Formatting helpers ───────────────────────────────── */

function scoreClass(score) {
  if (score === null || score === undefined) return "none";
  if (score >= 70) return "high";
  if (score >= 40) return "mid";
  return "low";
}

function scoreText(score) {
  return score === null || score === undefined ? "—" : `${Math.round(score)}%`;
}

function esc(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function jobMeta(job) {
  const parts = [
    job.company || "company not named",
    job.location || null,
    job.salary || null,
    job.salary_hourly || null,
    job.posted_display || null,
  ].filter(Boolean);
  return parts.map(esc).join(" · ");
}

function factTags(job) {
  // Labels come from the API (jobmatch/display.py) so every page words them
  // the same way — "Mid-level", never "medior".
  return [
    `<span class="tag src">${esc(job.source_label)}</span>`,
    job.seniority_label ? `<span class="tag fact">${esc(job.seniority_label)}</span>` : "",
    job.worktype_label ? `<span class="tag fact">${esc(job.worktype_label)}</span>` : "",
    job.employment_label ? `<span class="tag fact">${esc(job.employment_label)}</span>` : "",
  ].join("");
}

function breakdownTitle(bd) {
  if (!bd) return "Not scored yet — the next scan will fetch the description.";
  const part = (name, value) =>
    `${name} ${value === null ? "not known" : Math.round(value * 100) + "%"}`;
  return "How this score is made up:\n" + [
    part("Skills", bd.skills),
    part("Worktype", bd.worktype),
    part("Location", bd.location),
    part("Seniority", bd.seniority),
  ].join("\n");
}

document.addEventListener("DOMContentLoaded", () => scanOverlay.init());
