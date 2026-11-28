// SPDX-FileCopyrightText: 2026 Stefano Campanella
// SPDX-License-Identifier: MIT
//
// The web page's judgement of the historical downloads' progresses (docs/assets/js/status.js):
// node --test tests/js/*.test.js

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CARDS,
  DEFAULT_PROGRESS_PREFIX,
  assessRuns,
  assessProgress,
  card,
  dayBefore,
  fraction,
  percent,
  readDocument,
  period,
  progressUrls,
} from "../../docs/assets/js/status.js";
// A progress as `arco-ocean progress` publishes it (tests/python/test_js_fixtures.py checks it
// against the package's models): a download running at 12:28 on 24 Nov 2026.
import running from "./fixtures/progress.json" with { type: "json" };

const NOW = Date.parse("2026-11-24T12:30:00Z");

function progress(fields) {
  return { ...structuredClone(running), ...fields };
}

test("a running download with a recent update is downloading, with how far it is", () => {
  const verdict = assessProgress(progress({}), NOW);
  assert.equal(verdict.status, "downloading");
  // 1533 of the 12234 days of [1993-01-01, 2026-07-01).
  assert.match(verdict.detail, /^Stored up to 1997-03-13 \(12 %\), block after block\.$/);
});

test("a running download silent for three updates is stale", () => {
  assert.equal(assessProgress(progress({ updated_at: "2026-11-24T12:15:00Z" }), NOW).status, "downloading");
  const verdict = assessProgress(progress({ updated_at: "2026-11-24T12:14:00Z" }), NOW);
  assert.equal(verdict.status, "stale");
  assert.match(verdict.detail, /No update for 16 min/);
  assert.match(verdict.detail, /stored up to 1997-03-13 \(12 %\)/);
  assert.match(verdict.detail, /--resume/);
  // Longer beats, a longer silence.
  const slow = progress({ updated_at: "2026-11-24T11:40:00Z", heartbeat_seconds: 1200 });
  assert.equal(assessProgress(slow, NOW).status, "downloading");
});

test("a running download with no block committed for an hour is stalled", () => {
  // Reporting (its heartbeat recent), its last block at 12:20: stalled after 13:20.
  const at = (time) => Date.parse(`2026-11-24T${time}Z`);
  const fresh = (now) => progress({ updated_at: new Date(now - 60 * 1000).toISOString() });
  assert.equal(assessProgress(fresh(at("13:20:00")), at("13:20:00")).status, "downloading");
  const verdict = assessProgress(fresh(at("16:41:00")), at("16:41:00"));
  assert.equal(verdict.status, "stale");
  assert.equal(verdict.label, "Stalled");
  assert.match(verdict.detail, /^No block committed for 4 h 21 min, though the download still reports/);
  assert.match(verdict.detail, /stored up to 1997-03-13 \(12 %\)/);
  // Before its first block, from the run's start (09:00 on 20 Nov).
  const first = progress({ done_until: null, last_commit_at: null, updated_at: "2026-11-20T09:59:00Z" });
  assert.equal(assessProgress(first, Date.parse("2026-11-20T10:00:00Z")).status, "downloading");
  const late = { ...first, updated_at: "2026-11-20T10:01:00Z" };
  assert.equal(assessProgress(late, Date.parse("2026-11-20T10:02:00Z")).label, "Stalled");
  // A silent heartbeat is told first: the run is gone, not stuck.
  assert.equal(assessProgress(progress({ updated_at: "2026-11-24T12:28:00Z" }), at("16:41:00")).label, "Stale");
});

test("a download started again with --resume counts from its start, not the failed run's commit", () => {
  // The failed run's last block at 12:20 on 24 Nov; started again at 09:00 the next day.
  const resumed = (now) =>
    progress({ started_at: "2026-11-25T09:00:00Z", updated_at: new Date(now - 60 * 1000).toISOString() });
  const at = (time) => Date.parse(`2026-11-25T${time}Z`);
  assert.equal(assessProgress(resumed(at("09:30:00")), at("09:30:00")).status, "downloading");
  const verdict = assessProgress(resumed(at("10:30:00")), at("10:30:00"));
  assert.equal(verdict.label, "Stalled");
  assert.match(verdict.detail, /^No block committed for 1 h 30 min/);
});

test("a download without a block yet, or whose repository was not read", () => {
  const first = assessProgress(progress({ done_until: null }), NOW);
  assert.equal(first.detail, "Writing the first block.");
  const unread = assessProgress(
    progress({ error: "the repository could not be read: OSError" }),
    NOW,
  );
  assert.equal(unread.status, "downloading");
  assert.match(unread.detail, /could not be read: OSError: the next update tries again/);
});

test("a finished download stays finished", () => {
  const finished = progress({
    state: "finished",
    done_until: "2026-07-01",
    ended_at: "2026-11-30T08:00:00Z",
  });
  // Months later: it is run once.
  const verdict = assessProgress(finished, Date.parse("2027-06-01T00:00:00Z"));
  assert.equal(verdict.status, "finished");
  assert.equal(verdict.detail, "Every day from 1993-01-01 to 2026-06-30 is stored.");
  assert.equal(percent(fraction(finished)), "100 %");
});

test("a failed download says why, and how far it got", () => {
  const verdict = assessProgress(
    progress({
      state: "failed",
      detail: "The download stopped (exit status 1): rerun it with --resume.",
      ended_at: "2026-11-24T12:29:00Z",
    }),
    NOW,
  );
  assert.equal(verdict.status, "aborted");
  assert.equal(verdict.label, "Failed");
  assert.equal(
    verdict.detail,
    "The download stopped (exit status 1): rerun it with --resume. Stored up to 1997-03-13 (12 %).",
  );
});

test("an unreadable or unknown progress is unknown", () => {
  assert.equal(assessProgress(null, NOW).status, "unknown");
  assert.match(assessProgress(null, NOW).detail, /no download has published it yet/);
  assert.match(assessProgress(progress({ schema: 2 }), NOW).detail, /unknown format \(schema 2\)/);
  assert.match(assessProgress(progress({ state: "paused" }), NOW).detail, /unknown state \(paused\)/);
});

test("the share downloaded", () => {
  assert.equal(percent(fraction(progress({}))), "12 %");
  // Rounded down: 100 % only when every day is stored.
  assert.equal(percent(fraction(progress({ done_until: "2026-06-30" }))), "99 %");
  // An exact share is not taken down by its floating-point error (0.29 * 100 < 29).
  assert.equal(percent(0.29), "29 %");
  assert.equal(percent(29 / 100), "29 %");
  for (const fields of [{ start: null }, { done_until: null }, { end: "1993-01-01" }]) {
    assert.equal(fraction(progress(fields)), null);
  }
  // Within [0, 1].
  assert.equal(fraction(progress({ done_until: "2027-01-01" })), 1);
});

test("the period, its last day the one before the end", () => {
  assert.equal(period(progress({})), "1993-01-01 to 2026-06-30");
  assert.equal(dayBefore("2024-03-01"), "2024-02-29");
  assert.equal(period(progress({ start: null, end: "x" })), "– to –");
});

test("the card is chosen by the directive's JSON, the progresses by the page's address", () => {
  assert.equal(card(undefined), CARDS.forecast);
  assert.equal(card("historical"), CARDS.historical);
  assert.equal(card("climatology"), null);
  // Not an object's own property: not a card.
  assert.equal(card("toString"), null);
  assert.equal(card("constructor"), null);
  assert.deepEqual(
    progressUrls("").map(({ url }) => url),
    ["0p25", "0p5", "1p0"].map((res) => `${DEFAULT_PROGRESS_PREFIX}res=${res}.json`),
  );
  assert.deepEqual(progressUrls("?progress=/t/&status=y")[1], { res: "0p5", url: "/t/res=0p5.json" });
});

// The resolutions' progresses, as the card reads them.
function entries(byRes) {
  return ["0p25", "0p5", "1p0"].map((res) => ({ res, progress: byRes[res] ?? null }));
}

test("the headline: none published is unknown", () => {
  const verdict = assessRuns(entries({}), NOW);
  assert.equal(verdict.status, "unknown");
  assert.match(verdict.detail, /No historical download has published its progress yet/);
  assert.equal(assessRuns(null, NOW).status, "unknown");
});

test("the headline: one downloading, named, and those not started", () => {
  const verdict = assessRuns(entries({ "0p25": progress({}) }), NOW);
  assert.equal(verdict.status, "downloading");
  assert.equal(
    verdict.detail,
    "0.25°: Stored up to 1997-03-13 (12 %), block after block. Not started: 0.5°, 1.0°.",
  );
});

test("the headline: the most worrying resolution", () => {
  const finished = progress({ state: "finished", done_until: "2026-07-01" });
  const stale = progress({ updated_at: "2026-11-24T11:00:00Z" });
  const failed = progress({ state: "failed", detail: "Stopped." });
  let verdict = assessRuns(entries({ "0p25": finished, "0p5": stale, "1p0": progress({}) }), NOW);
  assert.equal(verdict.status, "stale");
  assert.match(verdict.detail, /^0\.5°: No update for 1 h 30 min/);
  verdict = assessRuns(entries({ "0p25": stale, "0p5": failed, "1p0": finished }), NOW);
  assert.equal(verdict.status, "aborted");
  assert.match(verdict.detail, /^0\.5°: Stopped\. Stored up to 1997-03-13/);
});

test("a document not published is not started; one that cannot be read is unknown", async () => {
  const answer = (status, body) => async () => ({
    status,
    ok: status >= 200 && status < 300,
    json: async () => (body === undefined ? JSON.parse("not json") : body),
  });
  // S3 answers 403 for a missing key when listing is not allowed.
  assert.deepEqual(await readDocument("u", answer(403)), { progress: null });
  assert.deepEqual(await readDocument("u", answer(404)), { progress: null });
  assert.deepEqual(await readDocument("u", answer(200, { schema: 1 })), {
    progress: { schema: 1 },
  });
  const unreadable = { progress: null, unreadable: true };
  assert.deepEqual(await readDocument("u", answer(503)), unreadable);
  assert.deepEqual(await readDocument("u", answer(200)), unreadable);
  const offline = async () => {
    throw new TypeError("network");
  };
  assert.deepEqual(await readDocument("u", offline), unreadable);
});

test("the headline: a resolution that cannot be read is not taken for not started", () => {
  const failed = progress({ state: "failed", detail: "Stopped." });
  const finished = progress({ state: "finished", done_until: "2026-07-01" });
  const entries = [
    { res: "0p25", progress: null, unreadable: true },
    { res: "0p5", progress: finished },
    { res: "1p0", progress: null },
  ];
  let verdict = assessRuns(entries, NOW);
  assert.equal(verdict.status, "unknown");
  assert.equal(
    verdict.detail,
    "0.25°: Could not be read: the bucket out of reach, or the document damaged. Not started: 1.0°.",
  );
  // A failure still comes first.
  entries[2] = { res: "1p0", progress: failed };
  assert.equal(assessRuns(entries, NOW).status, "aborted");
});

test("the headline: finished when every one published is", () => {
  const finished = progress({ state: "finished", done_until: "2026-07-01" });
  let verdict = assessRuns(entries({ "0p25": finished, "0p5": finished, "1p0": finished }), NOW);
  assert.equal(verdict.status, "finished");
  assert.equal(verdict.detail, "0.25°, 0.5°, 1.0°: every day stored.");
  verdict = assessRuns(entries({ "0p25": finished }), NOW);
  assert.equal(verdict.detail, "0.25°: every day stored. Not started: 0.5°, 1.0°.");
});
