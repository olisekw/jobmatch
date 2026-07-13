/* Shared helpers: API wrapper, toast, scan overlay with status polling. */

async function api(path, options = {}) {
  if (options.json !== undefined) {
    options.method = options.method || "POST";
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(options.json);
    delete options.json;
  }
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
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

  init() {
    this.el = document.getElementById("scan-overlay");
    document.getElementById("scan-cancel").addEventListener("click", async () => {
      await api("/api/scan/cancel", { method: "POST" });
      document.getElementById("scan-phase").textContent = "cancelling…";
    });
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

    if (status.status === "running") {
      this.open();
      document.getElementById("scan-phase").textContent = status.phase || "…";
      document.getElementById("scan-counts").textContent =
        `found ${status.found} · enriched ${status.enriched}` +
        (status.failed ? ` · failed ${status.failed}` : "");
      this.schedule();
      return;
    }

    if (!initial) {
      this.close();
      if (status.status === "done") {
        const errors = Object.entries(status.source_errors || {});
        toast(
          `Scan finished — ${status.found} new jobs, ${status.enriched} analyzed` +
          (errors.length ? ` (${errors.map(([s]) => s).join(", ")} had errors)` : "")
        );
      } else if (status.status === "cancelled") {
        toast("Scan cancelled");
      } else if (status.status === "failed") {
        toast("Scan failed — see server log");
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

function postedText(job) {
  const n = job.posted_days_ago;
  if (n === null || n === undefined) return job.freshness || "";
  if (n === 0) return "today";
  if (n === 1) return "yesterday";
  return `${n} days ago`;
}

function jobMeta(job) {
  const parts = [
    job.company || "unknown company",
    job.location || null,
    job.salary || null,
    job.salary_hourly || null,
    postedText(job) || null,
  ].filter(Boolean);
  return parts.map(esc).join(" · ");
}

function factTags(job) {
  return [
    `<span class="tag src">${esc(job.source_label)}</span>`,
    job.seniority ? `<span class="tag fact">${esc(job.seniority)}</span>` : "",
    job.worktype ? `<span class="tag fact">${esc(job.worktype)}</span>` : "",
    job.employment_type ? `<span class="tag fact">${esc(job.employment_type)}</span>` : "",
  ].join("");
}

function breakdownTitle(bd) {
  if (!bd) return "not scored yet — run a scan to fetch the description";
  const part = (name, value) =>
    `${name}: ${value === null ? "unknown" : Math.round(value * 100) + "%"}`;
  return [
    part("skills", bd.skills),
    part("worktype", bd.worktype),
    part("location", bd.location),
    part("seniority", bd.seniority),
  ].join("\n");
}

document.addEventListener("DOMContentLoaded", () => scanOverlay.init());
