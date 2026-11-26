// SPDX-FileCopyrightText: 2026 Stefano Campanella
// SPDX-License-Identifier: MIT
//
// The forecast collection on the web page: its state, judged from its heartbeat (`arco-ocean
// status` writes it; `arco-ocean heartbeat-schema` prints the document's schema), and the
// dashboard that shows it, a MyST `{anywidget}` (docs/index.md). One module: the directive copies
// this file alone, so it imports nothing. The judgement is pure functions, tested by
// tests/js/forecast.test.js; the widget reads the heartbeat every minute.
// `?status=URL` in the page's address reads another heartbeat (a test copy, say).
// Nothing here runs on import: Node's tests import it without a page.

export const DEFAULT_STATUS_URL =
  "https://ogs-arco-ocean.s3.eu-south-1.amazonaws.com/status/forecast.json";

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

// A running collection is stale when its heartbeat has been silent for three beats (at least
// 15 minutes); a finished one when the next has not finished within `stale_after_hours`.
const MISSED_BEATS = 3;
const MIN_SILENCE = 15 * MINUTE;
// A finished collection is stale too when a resolution falls behind (`behind`), by more than the
// recipes' `missing_after`, which the heartbeat publishes (two days if it does not).
const DEFAULT_MISSING_AFTER_DAYS = 2;

// "3 min", "2 h 5 min", "1 d 3 h".
export function duration(ms) {
  const minutes = Math.max(0, Math.floor(ms / MINUTE));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
  const days = Math.floor(hours / 24);
  return hours % 24 ? `${days} d ${hours % 24} h` : `${days} d`;
}

// "2026-11-24 12:00 UTC".
export function utc(iso) {
  if (!iso) return "–";
  const time = new Date(iso);
  if (Number.isNaN(time.getTime())) return "–";
  return `${time.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

const RESOLUTION_STATES = {
  pending: "Waiting its turn",
  downloading: "Downloading",
  finished: "Finished",
  not_published: "Newest run not published yet",
  failed: "Failed",
};

export function resolutionState(state) {
  return RESOLUTION_STATES[state] ?? "Unknown";
}

// "0p25" -> "0.25°".
export function resolutionLabel(res) {
  return `${String(res).replace("p", ".")}°`;
}

// Flag variables name their component: "glo12_forecast" -> "GLO12", "ifs_forecast" -> "IFS".
export function componentLabel(flag) {
  return String(flag).replace(/_forecast$/, "").toUpperCase();
}

// "IFS 100 %, GLO12 0 %": the share of the newest run's lead times that are the
// run's own forecast, per component.
export function flagsSummary(flags) {
  const entries = Object.entries(flags ?? {});
  if (entries.length === 0) return "–";
  return entries
    .map(([flag, share]) => `${componentLabel(flag)} ${Math.round(Number(share) * 100)} %`)
    .join(", ");
}

// The collection's state as the page shows it: downloading, finished, stale or aborted
// (unknown if the heartbeat cannot be read), with a sentence.
export function assess(heartbeat, now = Date.now()) {
  if (!heartbeat || typeof heartbeat !== "object") {
    return { status: "unknown", label: "Unknown", detail: "The heartbeat could not be read." };
  }
  if (heartbeat.schema !== 1) {
    return {
      status: "unknown",
      label: "Unknown",
      detail: `The heartbeat has an unknown format (schema ${heartbeat.schema}).`,
    };
  }
  const updated = Date.parse(heartbeat.updated_at);
  const beat = (Number(heartbeat.heartbeat_seconds) || 300) * 1000;
  const staleAfter = (Number(heartbeat.stale_after_hours) || 30) * HOUR;
  if (heartbeat.state === "running") {
    const silence = now - updated;
    if (!(silence <= Math.max(MISSED_BEATS * beat, MIN_SILENCE))) {
      return {
        status: "stale",
        label: "Stale",
        detail:
          `No heartbeat for ${duration(silence)}: the collection stopped without reporting ` +
          "(the machine down or the process killed). The next collection resumes it.",
      };
    }
    const current = (heartbeat.resolutions ?? []).find((r) => r.state === "downloading");
    const where = current ? ` (now ${resolutionLabel(current.res)})` : "";
    return {
      status: "downloading",
      label: "Downloading",
      detail: `Collecting the runs up to ${heartbeat.target_run}${where}.`,
    };
  }
  if (heartbeat.state === "aborted") {
    return {
      status: "aborted",
      label: "Aborted",
      detail: heartbeat.detail ?? "The collection failed: the next collection resumes it.",
    };
  }
  if (heartbeat.state === "finished") {
    const ended = Date.parse(heartbeat.ended_at ?? heartbeat.updated_at);
    if (!(now - ended <= staleAfter)) {
      return {
        status: "stale",
        label: "Stale",
        detail: `No collection has finished for ${duration(now - ended)}: one runs every day.`,
      };
    }
    const reasons = behind(heartbeat, now);
    if (reasons.length > 0) {
      return {
        status: "stale",
        label: "Stale",
        detail:
          `The collection finished, but ${reasons.join("; ")}: a source may have stopped ` +
          "publishing (the flags tell which), or the runs are not stored.",
      };
    }
    return {
      status: "finished",
      label: "Finished",
      detail: heartbeat.detail ?? `Every run up to ${heartbeat.target_run} is stored.`,
    };
  }
  return {
    status: "unknown",
    label: "Unknown",
    detail: `The heartbeat has an unknown state (${heartbeat.state}).`,
  };
}

// "YYYY-MM-DD" as the time of its midnight UTC, or null.
function day(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const time = Date.parse(`${value}T00:00:00Z`);
  return Number.isNaN(time) ? null : time;
}

// How many days the newest stored run is before the newest asked for (null if either is missing).
export function lagDays(latestRun, targetRun) {
  const run = day(latestRun);
  const target = day(targetRun);
  if (run === null || target === null) return null;
  return Math.round((target - run) / DAY);
}

// Why the resolutions of a finished collection are behind, if they are: a newest stored run older
// than the recipes' `missing_after` (runs that old are stored even without a source, flagged), or
// a resolution waiting for its sources for longer than that (a source that stopped publishing
// keeps it waiting every day, while its older runs are stored without it).
export function behind(heartbeat, now = Date.now()) {
  const limit = Number(heartbeat.missing_after_days) || DEFAULT_MISSING_AFTER_DAYS;
  const target = day(heartbeat.target_run);
  const reasons = [];
  for (const entry of heartbeat.resolutions ?? []) {
    const label = resolutionLabel(entry.res);
    if (target !== null) {
      const lag = lagDays(entry.latest_run, heartbeat.target_run);
      if (lag === null) {
        reasons.push(`${label} has no run stored`);
        continue;
      }
      if (lag > limit) {
        reasons.push(`${label}'s newest run is ${entry.latest_run}, ${lag} days before the newest`);
        continue;
      }
    }
    const since = Date.parse(entry.waiting_since ?? "");
    if (!Number.isNaN(since) && now - since > limit * DAY) {
      reasons.push(`${label} has waited for a source for ${duration(now - since)}`);
    }
  }
  return reasons;
}

// How old the newest stored run is, in whole days, at `now` (UTC dates).
export function runAgeDays(latestRun, now = Date.now()) {
  const run = day(latestRun);
  if (run === null) return null;
  const today = day(new Date(now).toISOString().slice(0, 10));
  return Math.round((today - run) / DAY);
}

// --- The dashboard -------------------------------------------------------------------------------

const REFRESH_MS = 60 * 1000;
const ICONS = { downloading: "⟳", finished: "✓", stale: "!", aborted: "✕", unknown: "?" };

const MARKUP = `
  <div class="status-card" data-status="unknown" aria-live="polite">
    <div class="status-head">
      <span class="status-icon" aria-hidden="true">?</span>
      <span class="status-label">Checking…</span>
    </div>
    <p class="status-detail">Reading the heartbeat.</p>
    <dl class="status-times">
      <div><dt>Newest run asked for</dt><dd data-field="target">–</dd></div>
      <div><dt>Started</dt><dd data-field="started">–</dd></div>
      <div><dt>Last heartbeat</dt><dd data-field="beat">–</dd></div>
      <div><dt>Ended</dt><dd data-field="ended">–</dd></div>
    </dl>
  </div>
  <div class="table-wrap">
    <table>
      <caption>Each resolution's repository</caption>
      <thead>
        <tr><th scope="col">Resolution</th><th scope="col">This collection</th><th scope="col">Newest run stored</th><th scope="col">Runs stored</th><th scope="col">Own forecast in the newest run</th></tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>
  <p class="note">Checked at <span data-field="checked">–</span>; checked again every minute.</p>
`;

async function fetchHeartbeat(url) {
  try {
    const answer = await fetch(url, { cache: "no-store" });
    if (!answer.ok) return null;
    return await answer.json();
  } catch {
    return null;
  }
}

function cell(row, text) {
  const td = document.createElement("td");
  td.textContent = text;
  row.append(td);
  return td;
}

// Show the heartbeat in the widget's element, as judged at `now`.
export function show(el, heartbeat, now) {
  const verdict = assess(heartbeat, now);
  const field = (name) => el.querySelector(`[data-field="${name}"]`);
  el.querySelector(".status-card").dataset.status = verdict.status;
  el.querySelector(".status-icon").textContent = ICONS[verdict.status];
  el.querySelector(".status-label").textContent = verdict.label;
  el.querySelector(".status-detail").textContent = verdict.detail;

  const ok = heartbeat && heartbeat.schema === 1;
  const updated = ok ? Date.parse(heartbeat.updated_at) : NaN;
  field("started").textContent = ok ? utc(heartbeat.started_at) : "–";
  field("beat").textContent = Number.isNaN(updated)
    ? "–"
    : `${utc(heartbeat.updated_at)} (${duration(now - updated)} ago)`;
  field("ended").textContent = ok && heartbeat.ended_at ? utc(heartbeat.ended_at) : "–";
  field("target").textContent = ok ? heartbeat.target_run : "–";

  const body = el.querySelector("tbody");
  body.replaceChildren();
  for (const entry of ok ? (heartbeat.resolutions ?? []) : []) {
    const row = document.createElement("tr");
    cell(row, resolutionLabel(entry.res));
    cell(row, resolutionState(entry.state)).dataset.state = entry.state;
    const age = runAgeDays(entry.latest_run, now);
    const ageText = age === null ? "" : age === 0 ? " (today)" : ` (${age} d ago)`;
    cell(row, entry.latest_run ? `${entry.latest_run}${ageText}` : "–");
    cell(row, entry.runs ?? "–");
    cell(row, entry.error ?? flagsSummary(entry.flags));
    body.append(row);
  }
  field("checked").textContent = utc(new Date(now).toISOString());
}

// The heartbeat's URL: the page's ?status=, else the bucket's (written once, here).
export function statusUrl(search) {
  return new URLSearchParams(search).get("status") || DEFAULT_STATUS_URL;
}

function render({ el }) {
  // Appended, not el.innerHTML: the page's renderer puts the widget's stylesheet in el.
  const root = document.createElement("div");
  root.innerHTML = MARKUP;
  el.append(root);
  const url = statusUrl(window.location.search);
  // Only the newest refresh shows: a slow answer does not overwrite a later one.
  let latest = 0;
  let stopped = false;
  const refresh = async () => {
    const mine = ++latest;
    const heartbeat = await fetchHeartbeat(url);
    if (stopped || mine !== latest) return;
    try {
      show(root, heartbeat, Date.now());
    } catch (error) {
      // A document it cannot show: said so, not left at "Checking…".
      show(root, null, Date.now());
      console.error("forecast dashboard:", error);
    }
  };
  refresh();
  const timer = setInterval(refresh, REFRESH_MS);
  // Called when the widget leaves the page (or is rendered again): nothing left behind.
  return () => {
    stopped = true;
    clearInterval(timer);
    root.remove();
  };
}

export default { render };
