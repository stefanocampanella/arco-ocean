// SPDX-FileCopyrightText: 2026 Stefano Campanella
// SPDX-License-Identifier: MIT
//
// The web page's judgement of the statistics' states (docs/assets/js/status.js):
// node --test tests/js/*.test.js

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CARDS,
  DEFAULT_STATISTICS_PREFIX,
  assessProgress,
  assessRuns,
  card,
  statisticsUrls,
} from "../../docs/assets/js/status.js";
// A state as `arco-ocean progress --kind statistics` publishes it (tests/python/test_js_fixtures.py
// checks it against the package's models): a computation running at 12:28 on 24 Nov 2026.
import running from "./fixtures/progress-statistics.json" with { type: "json" };

const NOW = Date.parse("2026-11-24T12:30:00Z");

function statistics(fields) {
  return { ...structuredClone(running), ...fields };
}

test("a running computation with a recent update is computing, for how long", () => {
  const verdict = assessProgress(statistics({}), NOW);
  assert.deepEqual(verdict, {
    status: "downloading",
    label: "Computing",
    detail: "Computing, for 3 h.",
  });
});

test("a running computation silent for three updates is stale", () => {
  const verdict = assessProgress(statistics({ updated_at: "2026-11-24T12:14:00Z" }), NOW);
  assert.equal(verdict.status, "stale");
  assert.match(verdict.detail, /^No update for 16 min: the computation stopped/);
});

test("finished statistics stay finished, failed ones say why", () => {
  const finished = statistics({
    state: "finished",
    ended_at: "2026-11-24T18:01:00Z",
    last_commit_at: "2026-11-24T18:00:00Z",
  });
  const verdict = assessProgress(finished, Date.parse("2027-06-01T00:00:00Z"));
  assert.equal(verdict.status, "finished");
  assert.equal(verdict.detail, "Stored at 2026-11-24 18:00 UTC.");
  const failed = assessProgress(
    statistics({ state: "failed", detail: "Stopped (exit status 1): rerun it." }),
    NOW,
  );
  assert.equal(failed.label, "Failed");
  assert.equal(failed.detail, "Stopped (exit status 1): rerun it.");
  assert.match(assessProgress(statistics({ state: "paused" }), NOW).detail, /unknown value/);
});

test("the statistics' headline", () => {
  const entries = (byRes) =>
    ["0p25", "0p5", "1p0"].map((res) => ({ res, progress: byRes[res] ?? null }));
  let verdict = assessRuns(entries({}), NOW, "statistics");
  assert.match(verdict.detail, /^No computation of statistics has published its state yet/);
  const finished = statistics({ state: "finished", last_commit_at: "2026-11-24T18:00:00Z" });
  verdict = assessRuns(entries({ "0p5": finished, "1p0": finished }), NOW, "statistics");
  assert.equal(verdict.detail, "0.5°, 1.0°: stored. Not started: 0.25°.");
  verdict = assessRuns(entries({ "0p25": statistics({}), "1p0": finished }), NOW, "statistics");
  assert.equal(verdict.label, "Computing");
  assert.equal(verdict.detail, "0.25°: Computing, for 3 h. Not started: 0.5°.");
});

test("the statistics' card and documents", () => {
  assert.equal(card("statistics"), CARDS.statistics);
  assert.equal(statisticsUrls("")[0].url, `${DEFAULT_STATISTICS_PREFIX}res=0p25.json`);
  assert.equal(statisticsUrls("?statistics=/s/&progress=/p/")[2].url, "/s/res=1p0.json");
});
