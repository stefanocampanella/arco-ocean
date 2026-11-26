#!/usr/bin/env bats
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
#
# scripts/forecast.sh and its heartbeat (the package's `arco-ocean status`, really run), with a
# stand-in for scripts/download.sh: the states it publishes when the downloads succeed, wait for
# a run, fail, or when the collection is killed, and its exit status when the collection
# finishes behind.

setup() {
    load common
    common_setup
    needs_package
    copy_scripts forecast.sh .env
    # Records its arguments; stores in its repository (DATA_ROOT/forecast/res=RES, from
    # --data-root) runs up to the day given for its resolution (FAKE_LATEST="1p0=2026-11-24";
    # default none); exits with the code given for it (FAKE_CODES="1p0=75,0p5=1"; default 0),
    # after FAKE_SLEEP seconds.
    stub_at "${PROJECT}/scripts/download.sh" '
RECIPE="${*: -1}"
RES="${RECIPE#forecast_res-}"
ROOT=""
while [[ $# -gt 0 ]]; do
    if [[ "$1" == --data-root ]]; then ROOT="$2"; fi
    shift
done
sleep "${FAKE_SLEEP:-0}"
for PAIR in ${FAKE_LATEST//,/ }; do
    if [[ "${PAIR%%=*}" == "${RES}" ]]; then
        "${TEST_CHECKOUT}/.venv/bin/python" "${BATS_TEST_DIRNAME}/fixtures/store.py" \
            "${ROOT}/forecast/res=${RES}" "${PAIR#*=}" || exit 1
    fi
done
for PAIR in ${FAKE_CODES//,/ }; do
    if [[ "${PAIR%%=*}" == "${RES}" ]]; then exit "${PAIR#*=}"; fi
done
exit 0'
    # Not REPO: forecast.sh has a REPO of its own, which the stand-in would inherit.
    export TEST_CHECKOUT="${REPO}" BATS_TEST_DIRNAME
    export DATA_ROOT="${PROJECT}"
    PUBLISHED="${PROJECT}/www/forecast.json"
}

# Every run stored, up to the newest asked for (--end 2026-11-25: the run of the 24th).
STORED="0p5=2026-11-24,1p0=2026-11-24"

# The collection, as the unit runs it but with a local heartbeat and two resolutions.
forecast() {
    run bash "${PROJECT}/scripts/forecast.sh" --project-dir "${PROJECT}" \
        --status-url "${PUBLISHED}" --res 0p5,1p0 --end 2026-11-25 "$@"
}

# A field of the published document: python's expression on `d`, the document.
published() {
    "${REPO}/.venv/bin/python" -c 'import json, sys; d = json.load(open(sys.argv[1])); print(eval(sys.argv[2]))' \
        "${PUBLISHED}" "$1"
}

@test "a collection that finishes" {
    FAKE_LATEST="${STORED}" forecast
    assert_success
    assert_equal "$(published 'd["state"], d["detail"], d["target_run"]')" "('finished', None, '2026-11-24')"
    assert_equal "$(published '[(r["res"], r["state"], r["latest_run"]) for r in d["resolutions"]]')" \
        "[('0p5', 'finished', '2026-11-24'), ('1p0', 'finished', '2026-11-24')]"
    # No path is published.
    run grep -c "${PROJECT}" "${PUBLISHED}"
    assert_output 0
}

@test "a collection finished behind fails with 3" {
    # Stored, but a source stopped: its runs come in without it, days late; or nothing stored.
    # The page calls it stale, and the unit fails, for its alert (scripts/alert.sh).
    FAKE_LATEST="0p5=2026-11-24,1p0=2026-11-20" forecast
    assert_failure 3
    assert_output --partial "finished behind: 1.0°'s newest run is 2026-11-20, 4 days before the newest"
    assert_equal "$(published 'd["state"]')" finished
    forecast --data-root "${PROJECT}/empty"
    assert_failure 3
    assert_output --partial "0.5° has no run stored"
}

@test "a run not published yet finishes with a detail, and 75" {
    # 75, not a failure: the systemd unit counts it a success.
    FAKE_CODES="1p0=75" FAKE_LATEST="0p5=2026-11-24,1p0=2026-11-23" forecast
    assert_failure 75
    assert_equal "$(published '"not published the newest run yet (1p0)" in d["detail"]')" True
    assert_equal "$(published '[r["state"] for r in d["resolutions"]]')" "['finished', 'not_published']"
}

@test "a failed download aborts" {
    FAKE_CODES="0p5=1" forecast
    assert_failure 1
    assert_equal "$(published 'd["state"], "failed at 0p5" in d["detail"]')" "('aborted', True)"
    assert_equal "$(published '[r["state"] for r in d["resolutions"]]')" "['failed', 'finished']"
}

@test "the heartbeat beats, and a killed collection aborts" {
    # Its own process group, signalled as a whole (Ctrl-C, systemd, kill of the job); fd 3 closed,
    # as bats asks of background processes.
    FAKE_SLEEP=30 setsid bash "${PROJECT}/scripts/forecast.sh" --project-dir "${PROJECT}" \
        --status-url "${PUBLISHED}" --res 0p5,1p0 --end 2026-11-25 --heartbeat 1 \
        > "${BATS_TEST_TMPDIR}/output" 2>&1 3>&- &
    local pid=$! first=""
    for _ in $(seq 300); do
        if [[ -f "${PUBLISHED}" ]] && [[ "$(published 'd["resolutions"][0]["state"]')" == downloading ]]; then
            break
        fi
        sleep 0.2
    done
    first="$(published 'd["updated_at"]')"
    # The beat moves the heartbeat on (to the second) while the download runs.
    for _ in $(seq 150); do
        [[ "$(published 'd["updated_at"]')" != "${first}" ]] && break
        sleep 0.2
    done
    assert_not_equal "$(published 'd["updated_at"]')" "${first}"
    assert_equal "$(published 'd["state"]')" running

    kill -TERM -- "-${pid}"
    # Not `run wait`: its subshell cannot wait for this shell's job.
    local code=0
    wait "${pid}" || code=$?
    assert_equal "${code}" 143
    assert_equal "$(published 'd["state"], "exit status 143" in d["detail"]')" "('aborted', True)"
    assert_equal "$(published 'd["resolutions"][0]["state"]')" failed
    # No beat is left behind, and the heartbeat stays as it ended.
    local ended
    ended="$(cat "${PUBLISHED}")"
    sleep 2.5
    assert_equal "$(cat "${PUBLISHED}")" "${ended}"
}

@test "without --status-url, no heartbeat" {
    # Nothing tells it behind: nothing is stored, and it succeeds.
    run bash "${PROJECT}/scripts/forecast.sh" --project-dir "${PROJECT}" --res 1p0 --end 2026-11-25
    assert_success
    assert_file_not_exists "${PUBLISHED}"
    assert_file_not_exists "${PROJECT}/logs/forecast/status.json"
}

@test "a data root goes to the downloads and to the heartbeat" {
    # A local root: the heartbeat really reads there, offline.
    FAKE_LATEST="${STORED}" forecast --data-root "${PROJECT}/store"
    assert_success
    run calls
    assert_equal "${#lines[@]}" 2
    assert_line --index 0 --partial "--data-root ${PROJECT}/store"
    assert_line --index 1 --partial "--data-root ${PROJECT}/store"
    # The heartbeat reads the repositories where the downloads write them (in the state file,
    # not published).
    run grep -c "${PROJECT}/store/forecast/res=0p5" "${PROJECT}/logs/forecast/status.json"
    assert_output 1
    assert_equal "$(published 'd["resolutions"][1]["latest_run"]')" 2026-11-24
    run grep -c "${PROJECT}/store" "${PUBLISHED}"
    assert_output 0
}

@test "the runner's options go to every download, as given" {
    FAKE_LATEST="${STORED}" forecast --image x.sif --bind /data --log-level debug
    assert_success
    run calls
    assert_line --index 0 --partial "--image x.sif --bind /data --log-level debug forecast_res-0p5"
}

@test "an empty data root, or a missing_after not positive, is refused" {
    # Empty, the root would fall back to the local disk silently; 0 would fail every collection
    # a day behind, the normal wait for today's run (the page reads it as two days).
    forecast --data-root=
    assert_failure 1
    assert_output --partial "--data-root"
    local value
    for value in 0 0.0 -1 two; do
        forecast --missing-after "${value}"
        assert_failure 1
        assert_output --partial "takes a positive number of days"
    done
    assert_file_not_exists "${CALLS}"
}

@test "the heartbeat runs in the checkout's environment" {
    # As the unit runs it: the checkout's forecast.sh, its heartbeat through `uv run` (no
    # ARCO_OCEAN_CLI), its downloads through download.sh with a stand-in arco-make, nothing stored.
    command -v uv >/dev/null || skip "needs uv"
    unset ARCO_OCEAN_CLI
    stub_at "${PROJECT}/venv/bin/arco-make"
    mkdir -p "${PROJECT}/configs/download"
    touch "${PROJECT}/configs/download/forecast_res-1p0.toml"
    PYTHONPATH="${PROJECT}" DATA_ROOT="${PROJECT}/store" run bash "${REPO}/scripts/forecast.sh" \
        --project-dir "${PROJECT}" --virtual-env "${PROJECT}/venv" --env-file "" --attempts 1 \
        --status-url "${PUBLISHED}" --res 1p0 --end 2026-11-25
    assert_failure 3
    assert_output --partial "1.0° has no run stored"
    assert_equal "$(published 'd["state"], d["resolutions"][0]["state"]')" "('finished', 'finished')"
}

@test "its own options are checked before the collection starts" {
    run timeout 20 bash "${PROJECT}/scripts/forecast.sh" --project-dir "${PROJECT}" --res
    assert_failure 1
    assert_output "Error: --res needs a value."
    # Refused by every download after the start, --attempts 0 would abort the collection and
    # open an issue: a usage error instead (review of #33).
    forecast --attempts 0
    assert_failure 1
    assert_output "Error: --attempts takes a positive integer (got '0')."
    forecast --retry-delay soon
    assert_output "Error: --retry-delay takes a number of seconds (got 'soon')."
    assert_file_not_exists "${PUBLISHED}"
    assert_file_not_exists "${CALLS}"
}
