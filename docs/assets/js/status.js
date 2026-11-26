// SPDX-FileCopyrightText: 2026 Stefano Campanella
// SPDX-License-Identifier: MIT
//
// The state of what makes ARCO-OCEAN, on the web page, a MyST `{anywidget}` (docs/index.md) with
// two cards, chosen by the directive's JSON:
// - {} or {"show": "forecast"}: the forecast collection, judged from its heartbeat (`arco-ocean
//   status` writes it; `arco-ocean heartbeat-schema` prints the document's schema);
// - {"show": "historical"}: the historical download, run once, judged from its progress
//   (`arco-ocean progress`, through scripts/download.sh --status-url; `arco-ocean
//   progress-schema`).
// One module: the directive copies this file alone, so it imports nothing. The judgements are
// pure functions, tested by tests/js/*.test.js; the widget reads its document every minute.
// `?status=URL` (the forecast's) and `?progress=URL` (the historical's) in the page's address read
// other documents (a test copy, say). Nothing here runs on import: Node's tests import it without
// a page.

export const DEFAULT_STATUS_URL =
  "https://ogs-arco-ocean.s3.eu-south-1.amazonaws.com/status/forecast.json";
export const DEFAULT_PROGRESS_URL =
  "https://ogs-arco-ocean.s3.eu-south-1.amazonaws.com/status/historical.json";

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

// --- The historical download -------------------------------------------------------------------

// The share of [start, end) downloaded, from 0 to 1, or null if a date is missing.
export function fraction(progress) {
  const start = day(progress?.start);
  const end = day(progress?.end);
  const done = day(progress?.done_until);
  if (start === null || end === null || done === null || !(end > start)) return null;
  return Math.min(1, Math.max(0, (done - start) / (end - start)));
}

// The day before "YYYY-MM-DD" (an end, excluded, as the last day), or "–".
export function dayBefore(value) {
  const time = day(value);
  return time === null ? "–" : new Date(time - DAY).toISOString().slice(0, 10);
}

// "1993-01-01 to 2026-06-30": the first and the last day.
export function period(progress) {
  return `${progress.start ?? "–"} to ${dayBefore(progress.end)}`;
}

// "12 %": rounded down, so that 100 % means every day.
export function percent(share) {
  return `${Math.floor(share * 100)} %`;
}

// "up to 1997-03-14 (12 %)", or "" if nothing is stored yet.
function doneText(progress) {
  if (!progress.done_until) return "";
  const share = fraction(progress);
  return `up to ${progress.done_until}${share === null ? "" : ` (${percent(share)})`}`;
}

// The download's state as the page shows it: downloading, finished, failed (status "aborted"),
// stale or unknown, with a sentence. A finished download stays finished: it is run once.
export function assessProgress(progress, now = Date.now()) {
  if (!progress || typeof progress !== "object") {
    return {
      status: "unknown",
      label: "Unknown",
      detail:
        "The progress could not be read: no download has published it yet, or the bucket " +
        "cannot be reached.",
    };
  }
  if (progress.schema !== 1) {
    return {
      status: "unknown",
      label: "Unknown",
      detail: `The progress has an unknown format (schema ${progress.schema}).`,
    };
  }
  const done = doneText(progress);
  const unread = progress.error ? ` (${progress.error}: the next update tries again)` : "";
  if (progress.state === "running") {
    const silence = now - Date.parse(progress.updated_at);
    const beat = (Number(progress.heartbeat_seconds) || 300) * 1000;
    if (!(silence <= Math.max(MISSED_BEATS * beat, MIN_SILENCE))) {
      return {
        status: "stale",
        label: "Stale",
        detail:
          `No update for ${duration(silence)}: the download stopped without reporting (the ` +
          `machine down or the process killed)${done ? `, stored ${done}` : ""}. Rerun it with ` +
          "--resume.",
      };
    }
    return {
      status: "downloading",
      label: "Downloading",
      detail: done
        ? `Stored ${done}, block after block.${unread}`
        : `Writing the first block.${unread}`,
    };
  }
  if (progress.state === "finished") {
    return {
      status: "finished",
      label: "Finished",
      detail: progress.detail ?? `Every day from ${period(progress)} is stored.`,
    };
  }
  if (progress.state === "failed") {
    const stored = done ? ` Stored ${done}.` : "";
    return {
      status: "aborted",
      label: "Failed",
      detail: `${progress.detail ?? "The download failed: rerun it with --resume."}${stored}`,
    };
  }
  return {
    status: "unknown",
    label: "Unknown",
    detail: `The progress has an unknown state (${progress.state}).`,
  };
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

const PROGRESS_MARKUP = `
  <div class="status-card" data-status="unknown" aria-live="polite">
    <div class="status-head">
      <span class="status-icon" aria-hidden="true">?</span>
      <span class="status-label">Checking…</span>
    </div>
    <p class="status-detail">Reading the progress.</p>
    <progress class="status-progress" max="1" aria-label="Share of the period stored"></progress>
    <dl class="status-times">
      <div><dt>Period</dt><dd data-field="period">–</dd></div>
      <div><dt>Stored up to</dt><dd data-field="done">–</dd></div>
      <div><dt>Last block committed</dt><dd data-field="commit">–</dd></div>
      <div><dt>Started</dt><dd data-field="started">–</dd></div>
      <div><dt>Last update</dt><dd data-field="updated">–</dd></div>
      <div><dt>Ended</dt><dd data-field="ended">–</dd></div>
    </dl>
  </div>
  <p class="note">Checked at <span data-field="checked">–</span>; checked again every minute.</p>
`;

// "2026-11-24 12:00 UTC (5 min ago)", or "–".
function ago(iso, now) {
  const time = Date.parse(iso);
  return Number.isNaN(time) ? "–" : `${utc(iso)} (${duration(now - time)} ago)`;
}

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

// Set a field's text, each date in it kept on one line (a line may break at a hyphen).
function setDates(element, text) {
  element.replaceChildren(
    ...text.split(/(\d{4}-\d{2}-\d{2})/).map((piece, i) => {
      if (i % 2 === 0) return piece;
      const date = document.createElement("span");
      date.className = "date";
      date.textContent = piece;
      return date;
    }),
  );
}

// Show the download's progress in the widget's element, as judged at `now`.
export function showProgress(el, progress, now) {
  const verdict = assessProgress(progress, now);
  const field = (name) => el.querySelector(`[data-field="${name}"]`);
  el.querySelector(".status-card").dataset.status = verdict.status;
  el.querySelector(".status-icon").textContent = ICONS[verdict.status];
  el.querySelector(".status-label").textContent = verdict.label;
  el.querySelector(".status-detail").textContent = verdict.detail;

  const ok = progress && progress.schema === 1;
  const bar = el.querySelector(".status-progress");
  const share = ok ? fraction(progress) : null;
  // No value: an indeterminate bar (nothing stored yet, or unknown).
  if (share === null) {
    bar.removeAttribute("value");
  } else {
    bar.value = share;
  }
  bar.textContent = share === null ? "" : percent(share);
  setDates(field("period"), ok ? period(progress) : "–");
  setDates(
    field("done"),
    ok && progress.done_until
      ? `${progress.done_until}${share === null ? "" : ` (${percent(share)})`}`
      : "–",
  );
  setDates(field("commit"), ok ? ago(progress.last_commit_at, now) : "–");
  setDates(field("started"), ok ? utc(progress.started_at) : "–");
  setDates(field("updated"), ok ? ago(progress.updated_at, now) : "–");
  setDates(field("ended"), ok && progress.ended_at ? utc(progress.ended_at) : "–");
  field("checked").textContent = utc(new Date(now).toISOString());
}

// The heartbeat's URL: the page's ?status=, else the bucket's (written once, here).
export function statusUrl(search) {
  return new URLSearchParams(search).get("status") || DEFAULT_STATUS_URL;
}

// The progress's URL: the page's ?progress=, else the bucket's.
export function progressUrl(search) {
  return new URLSearchParams(search).get("progress") || DEFAULT_PROGRESS_URL;
}

// The cards, by the directive's "show".
export const CARDS = {
  forecast: { markup: MARKUP, url: statusUrl, show },
  historical: { markup: PROGRESS_MARKUP, url: progressUrl, show: showProgress },
};

// The card a widget shows: its model's "show" (the directive's JSON), the forecast's by default.
export function card(name) {
  return CARDS[name ?? "forecast"] ?? null;
}

function render({ model, el }) {
  const name = model?.get?.("show");
  const chosen = card(name);
  if (chosen === null) {
    el.textContent = `Unknown card "${name}": give "forecast" or "historical".`;
    return () => el.replaceChildren();
  }
  // Appended, not el.innerHTML: the page's renderer puts the widget's stylesheet in el.
  const root = document.createElement("div");
  root.innerHTML = chosen.markup;
  el.append(root);
  const url = chosen.url(window.location.search);
  // Only the newest refresh shows: a slow answer does not overwrite a later one.
  let latest = 0;
  let stopped = false;
  const refresh = async () => {
    const mine = ++latest;
    const heartbeat = await fetchHeartbeat(url);
    if (stopped || mine !== latest) return;
    try {
      chosen.show(root, heartbeat, Date.now());
    } catch (error) {
      // A document it cannot show: said so, not left at "Checking…".
      chosen.show(root, null, Date.now());
      console.error(`${name ?? "forecast"} card:`, error);
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
