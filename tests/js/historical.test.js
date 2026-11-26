// SPDX-FileCopyrightText: 2026 Stefano Campanella
// SPDX-License-Identifier: MIT
//
// The web page's judgement of the historical download's progress (docs/assets/js/status.js):
// node --test tests/js/*.test.js

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CARDS,
  DEFAULT_PROGRESS_URL,
  assessProgress,
  card,
  dayBefore,
  fraction,
  percent,
  period,
  progressUrl,
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
  assert.match(verdict.detail, /^Stored up to 1997-03-14 \(12 %\), block after block\.$/);
});

test("a running download silent for three updates is stale", () => {
  assert.equal(assessProgress(progress({ updated_at: "2026-11-24T12:15:00Z" }), NOW).status, "downloading");
  const verdict = assessProgress(progress({ updated_at: "2026-11-24T12:14:00Z" }), NOW);
  assert.equal(verdict.status, "stale");
  assert.match(verdict.detail, /No update for 16 min/);
  assert.match(verdict.detail, /stored up to 1997-03-14 \(12 %\)/);
  assert.match(verdict.detail, /--resume/);
  // Longer beats, a longer silence.
  const slow = progress({ updated_at: "2026-11-24T11:40:00Z", heartbeat_seconds: 1200 });
  assert.equal(assessProgress(slow, NOW).status, "downloading");
});

test("a download without a block yet, or whose repository was not read", () => {
  const first = assessProgress(progress({ done_until: null, blocks: 0 }), NOW);
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
    "The download stopped (exit status 1): rerun it with --resume. Stored up to 1997-03-14 (12 %).",
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

test("the card is chosen by the directive's JSON, the progress by the page's address", () => {
  assert.equal(card(undefined), CARDS.forecast);
  assert.equal(card("historical"), CARDS.historical);
  assert.equal(card("climatology"), null);
  assert.equal(progressUrl(""), DEFAULT_PROGRESS_URL);
  assert.equal(progressUrl("?progress=https://x/p.json&status=y"), "https://x/p.json");
});
