/* Shared helpers: API wrapper, toast, scan progress strip, job rendering. */

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
  if (!res.ok) {
    const err = new Error(data.error || "Something went wrong — please try again.");
    err.status = res.status;
    throw err;
  }
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

/* ── Scan progress strip ──────────────────────────────────

   A scan runs for minutes — the Slovak boards are crawled with deliberate
   5–16 s delays — so its progress lives in a strip under the nav and the page
   underneath stays usable. Dismissing it hides that scan, not the next one. */

const scanStrip = {
  el: null,
  timer: null,
  watching: false,      // a scan was in progress the last time we looked
  dismissedScan: null,  // scan_id the user has told us to stop showing

  init() {
    this.el = document.getElementById("scan-strip");
    if (!this.el) return;
    this.dismissedScan = sessionStorage.getItem("scan-dismissed");

    const cancel = document.getElementById("scan-cancel");
    if (cancel) {
      cancel.addEventListener("click", async () => {
        cancel.disabled = true;
        try {
          await api("/api/scan/cancel", { method: "POST" });
          document.getElementById("scan-phase").textContent = "Stopping…";
        } catch (err) {
          cancel.disabled = false;
          toast(err.message);
        }
      });
    }
    document.getElementById("scan-dismiss").addEventListener("click", () => this.dismiss());
    // Reattach if a scan is already running (e.g. after a page reload)
    this.poll(true);
  },

  async start() {
    try {
      await api("/api/scan/start", { method: "POST" });
    } catch (err) {
      toast(err.message);
      return;
    }
    this.dismissedScan = null;
    sessionStorage.removeItem("scan-dismissed");
    document.getElementById("scan-phase").textContent = "Queued — waiting for a worker…";
    document.getElementById("scan-counts").textContent = "";
    this.open();
    this.schedule(300);
  },

  open() { this.el.classList.add("open"); },
  close() { this.el.classList.remove("open"); },

  dismiss() {
    this.close();
    if (this.currentScan) {
      this.dismissedScan = String(this.currentScan);
      sessionStorage.setItem("scan-dismissed", this.dismissedScan);
    }
  },

  schedule(delay = 2000) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.poll(false), delay);
  },

  async poll(initial) {
    let status;
    try {
      status = await api("/api/scan/status");
    } catch {
      if (!initial) this.schedule();
      return;
    }
    this.currentScan = status.scan_id;

    if (status.status === "running" || status.status === "queued") {
      // Scans are queued, not started, so a trigger shows "waiting for a
      // worker" for a poll or two before the phases start moving.
      if (String(status.scan_id) !== this.dismissedScan) this.open();
      const cancel = document.getElementById("scan-cancel");
      // Disabled while *this* scan is stopping; a later scan gets its own button
      // back, rather than inheriting the last one's greyed-out state.
      if (cancel) cancel.disabled = !!status.cancelling;
      document.getElementById("scan-phase").textContent =
        status.cancelling ? "Stopping the scan…" : (status.phase || "Scanning job boards…");
      document.getElementById("scan-counts").textContent =
        `${plural(status.found, "new job")} · ${status.enriched} analyzed` +
        (status.failed ? ` · ${status.failed} could not be read` : "");
      this.schedule();
      this.watching = true;
      return;
    }

    this.close();
    const wasWatching = this.watching;
    this.watching = false;
    if (initial) return;

    // A scheduled scan finishing still refreshes the page for everyone; only
    // the person who could have started it gets told about it in words.
    if (window.CAN_SCAN) {
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
    }
    if ((window.CAN_SCAN || wasWatching) && typeof window.onScanFinished === "function") {
      window.onScanFinished();
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
  // Pay, work mode and country are *not* in here any more: they are the three
  // things a person scans a job list for, and a dot-separated grey line is
  // where facts go to be skipped. They get their own row — see keyFacts().
  const parts = [
    job.company || "company not named",
    job.location || null,
    job.posted_display || null,
  ].filter(Boolean);
  return parts.map(esc).join(" · ");
}

/* ── The three facts a job list is actually read for ───────

   How much, from where, and can I do it from home. Each is its own chip, in
   the same order on every card, and each says something when the answer is
   missing — "no pay listed" is information, an empty space is an oversight. */

function payFact(job) {
  if (!job.salary_display) {
    return `<span class="keyfact pay none">No pay listed</span>`;
  }
  // Euros an hour is the only form in which a monthly Slovak salary, a Czech
  // one and an annual American one compare, so it rides along with the board's
  // own range rather than replacing it. Where the two are in different money
  // the title says what the conversion was — the server's sentence, with the
  // rate and the date it was read.
  const note = job.salary_hourly_title
    ? ` title="${esc(job.salary_hourly_title)}"` : "";
  const hourly = job.salary_hourly ? `<i${note}>${esc(job.salary_hourly)}</i>` : "";
  return `<span class="keyfact pay">${esc(job.salary_display)}${hourly}</span>`;
}

function modeFact(job) {
  if (!job.worktype_label) return `<span class="keyfact mode none">Mode unknown</span>`;
  return `<span class="keyfact mode ${esc(job.worktype)}">${esc(job.worktype_label)}</span>`;
}

function placeFact(job) {
  // An unplaced job still shows where the board said it was, rather than
  // pretending we know less than we do. A posting hiring in several places
  // reads "Europe +4" and carries the other four in its title — the words are
  // the server's, like every other label on a card.
  const text = job.country_label || job.location;
  if (!text) return "";
  const title = job.country_title ? ` title="${esc(job.country_title)}"` : "";
  return `<span class="keyfact place${job.country_label ? "" : " none"}"${title}>${esc(text)}</span>`;
}

function keyFacts(job) {
  return `<div class="keyfacts">${payFact(job)}${modeFact(job)}${placeFact(job)}</div>`;
}

function factTags(job) {
  // Labels come from the API (jobmatch/display.py) so every page words them
  // the same way — "Mid-level", never "medior". Worktype is deliberately not
  // repeated here; it is a key fact and lives in the row above.
  return [
    `<span class="tag src">${esc(job.source_label)}</span>`,
    job.seniority_label ? `<span class="tag fact">${esc(job.seniority_label)}</span>` : "",
    job.employment_label ? `<span class="tag fact">${esc(job.employment_label)}</span>` : "",
  ].join("");
}

/* ── The score, shown rather than hidden in a tooltip ──────

   Scoring is over *known* components only: a job whose seniority could not be
   parsed is not punished for it. That is the most interesting thing the app
   does, so "not known" has to look different from "scored zero" — a hatched
   track, never an empty one. */

const SCORE_PARTS = [
  ["skills", "Skills"],
  ["worktype", "Worktype"],
  ["location", "Location"],
  ["seniority", "Seniority"],
];

function hasBreakdown(bd) {
  return !!bd && SCORE_PARTS.some(([key]) => key in bd);
}

function miniBars(bd) {
  // Decorative: the same four numbers are readable as text in the panel below,
  // so a screen reader is told to skip the duplicate.
  if (!hasBreakdown(bd)) return "";
  return `<div class="minibars" aria-hidden="true">` + SCORE_PARTS.map(([key]) => {
    const value = bd[key];
    return value === null || value === undefined
      ? `<span class="minibar unknown"></span>`
      : `<span class="minibar"><i style="width:${Math.round(value * 100)}%"></i></span>`;
  }).join("") + `</div>`;
}

function breakdownPanel(bd) {
  if (!hasBreakdown(bd)) {
    return `<p class="hint">Not scored yet — the next scan will fetch the description.</p>`;
  }
  return `
    <p class="hint">The score is the average of what is <em>known</em> about this job,
       weighted by what you said matters. Anything unknown is left out, not counted as zero.</p>
    <dl class="breakdown-list">` + SCORE_PARTS.map(([key, name]) => {
    const value = bd[key];
    const unknown = value === null || value === undefined;
    return `
      <dt>${name}</dt>
      <dd>
        <span class="bar ${unknown ? "unknown" : ""}">${
          unknown ? "" : `<i style="width:${Math.round(value * 100)}%"></i>`}</span>
        <span class="bar-value">${unknown ? "not known" : Math.round(value * 100) + "%"}</span>
      </dd>`;
  }).join("") + `</dl>`;
}

function scoreLabel(job) {
  if (job.match_score === null || job.match_score === undefined) return "Not scored yet";
  return `Scores ${Math.round(job.match_score)} percent — show the breakdown`;
}

/* ── Job rows ─────────────────────────────────────────────

   One renderer, so the dashboard and the Jobs page cannot drift apart. */

function jobActions(job) {
  if (job.status === "new") return `
    <button class="btn small" data-act="applied">Applied ✓</button>
    <button class="btn small ghost" data-act="declined">Decline</button>`;
  if (job.status === "declined") return `
    <button class="btn small ghost" data-act="new">Restore</button>`;
  return `<button class="btn small ghost" data-act="new">Un-apply</button>`;
}

function jobCard(job, { actions = true, skills = true } = {}) {
  const skillTags = skills
    ? (job.skills || "").split(",").map(s => s.trim()).filter(Boolean).slice(0, 8)
        .map(s => `<span class="tag">${esc(s)}</span>`).join("")
    : "";
  return `
    <article class="job" data-id="${job.id}" tabindex="-1">
      <div class="score-cell">
        <button type="button" class="score ${scoreClass(job.match_score)}"
                aria-expanded="false" aria-controls="bd-${job.id}"
                aria-label="${esc(scoreLabel(job))}">${scoreText(job.match_score)}</button>
        ${miniBars(job.score_breakdown)}
      </div>
      <div class="job-main">
        <a class="title" href="/jobs/${job.id}">${esc(job.title)}</a>
        <a class="out" href="${esc(job.link)}" target="_blank" rel="noopener"
           aria-label="Open this posting on ${esc(job.source_label)}">↗</a>
        <div class="meta"${job.posted_exact ? ` title="Posted ${esc(job.posted_exact)}"` : ""}>${jobMeta(job)}</div>
        ${keyFacts(job)}
        <div class="tags">${factTags(job)}${skillTags}</div>
      </div>
      ${actions ? `<div class="actions">${jobActions(job)}</div>` : ""}
      <div class="breakdown" id="bd-${job.id}" hidden>${breakdownPanel(job.score_breakdown)}</div>
    </article>`;
}

/* Clicking a score toggles its breakdown. Delegated once per list, so it keeps
   working after the list is re-rendered. */
function wireBreakdownToggles(container) {
  container.addEventListener("click", (e) => {
    const btn = e.target.closest("button.score");
    if (!btn) return;
    toggleBreakdown(btn);
  });
}

function toggleBreakdown(btn) {
  const panel = document.getElementById(btn.getAttribute("aria-controls"));
  if (!panel) return;
  const open = panel.hasAttribute("hidden");
  panel.toggleAttribute("hidden", !open);
  btn.setAttribute("aria-expanded", open ? "true" : "false");
}

/* ── Loading states ───────────────────────────────────────

   "Loading…" in the middle of an empty page says nothing about what is coming.
   Skeleton rows keep the shape of the list that is about to arrive. */

function skeletonRows(n = 5) {
  return `<div class="skeletons" aria-hidden="true">` + Array.from({ length: n }, () => `
    <div class="job skeleton">
      <div class="score-cell"><span class="sk sk-score"></span></div>
      <div class="job-main">
        <span class="sk sk-line" style="width:${40 + Math.round(Math.random() * 40)}%"></span>
        <span class="sk sk-line short"></span>
        <span class="sk sk-line tags"></span>
      </div>
    </div>`).join("") + `</div>`;
}

function showLoading(el, rows = 5) {
  el.setAttribute("aria-busy", "true");
  el.innerHTML = skeletonRows(rows);
}

function showError(el, message, retry) {
  el.removeAttribute("aria-busy");
  el.innerHTML = `<div class="load-error" role="alert">
      <p>${esc(message)}</p>
      ${retry ? `<button type="button" class="btn small ghost" data-retry>Try again</button>` : ""}
    </div>`;
  if (retry) el.querySelector("[data-retry]").addEventListener("click", retry);
}

document.addEventListener("DOMContentLoaded", () => scanStrip.init());
