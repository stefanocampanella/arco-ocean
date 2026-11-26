#!/usr/bin/env bats
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
#
# scripts/download.sh and climatology.sh --status-url and --alert: the progress they publish (the
# package's `arco-ocean progress`, really run), read from the blocks a stand-in arco-make commits
# into the output repository as arco-make does (fixtures/blocks.py), and the reports they hand to
# a stand-in alert.sh.

setup() {
    load common
    common_setup
    needs_package
    mkdir -p "${PROJECT}/configs/download"
    touch "${PROJECT}/configs/download/historical_res-1p0.toml"
    # Commits the blocks of FAKE_BLOCKS (START/END, separated by spaces; with --running, the run
    # is left unfinished) into its output (the last argument), sleeps FAKE_SLEEP seconds, then
    # exits with FAKE_CODE (default 0).
    stub_at "${PROJECT}/venv/bin/arco-make" '
if [[ -n "${FAKE_BLOCKS:-}" ]]; then
    # shellcheck disable=SC2086 # the blocks, one word each
    "${TEST_CHECKOUT}/.venv/bin/python" "${FIXTURES}/blocks.py" "${*: -1}" ${FAKE_BLOCKS} || exit 1
fi
sleep "${FAKE_SLEEP:-0}"
exit "${FAKE_CODE:-0}"'
    export TEST_CHECKOUT="${REPO}" FIXTURES="${BATS_TEST_DIRNAME}/fixtures"
    export DATA_ROOT="${PROJECT}/root"
    PUBLISHED="${PROJECT}/www/historical.json"
}

# download.sh in the project, with the stand-in, publishing its progress locally.
download() {
    run bash "${REPO}/scripts/download.sh" --project-dir "${PROJECT}" \
        --virtual-env "${PROJECT}/venv" --env-file "" --status-url "${PUBLISHED}" \
        --start 1993-01-01 --end 1993-06-01 --attempts 1 --retry-delay 0 "$@" historical_res-1p0
}

@test "a download that finishes: its progress, to the last block" {
    FAKE_BLOCKS="1993-01-01/1993-02-02 1993-02-02/1993-03-06" download
    assert_success
    assert_equal "$(published 'd["state"], d["name"], d["start"], d["end"]')" \
        "('finished', 'historical_res-1p0', '1993-01-01', '1993-06-01')"
    assert_equal "$(published 'd["done_until"], d["ended_at"] is not None')" "('1993-03-06', True)"
    # The repository's path stays in the state file, out of the page.
    refute_output --partial "Warning"
    run cat "${PUBLISHED}"
    refute_output --partial "${PROJECT}"
    assert_file_exists "${PROJECT}/logs/download/progress_historical_res-1p0.json"
}

@test "a download that fails says so, and how to continue" {
    FAKE_BLOCKS="--running 1993-01-01/1993-02-02" FAKE_CODE=1 download
    assert_failure 1
    assert_equal "$(published 'd["state"], d["done_until"]')" "('failed', '1993-02-02')"
    assert_equal "$(published '"exit status 1" in d["detail"] and "--resume" in d["detail"]')" True
}

@test "the progress beats while the download runs, and a killed download fails" {
    # Its own process group, signalled as a whole; fd 3 closed, as bats asks of background
    # processes.
    FAKE_BLOCKS="--running 1993-01-01/1993-02-02" FAKE_SLEEP=30 setsid bash \
        "${REPO}/scripts/download.sh" --project-dir "${PROJECT}" --virtual-env "${PROJECT}/venv" \
        --env-file "" --status-url "${PUBLISHED}" --heartbeat 1 --start 1993-01-01 \
        --end 1993-06-01 --attempts 1 historical_res-1p0 > "${BATS_TEST_TMPDIR}/output" 2>&1 3>&- &
    local pid=$!
    # A beat reads the block committed while the download runs.
    for _ in $(seq 300); do
        if [[ -f "${PUBLISHED}" ]] && [[ "$(published 'd["done_until"]')" == 1993-02-02 ]]; then
            break
        fi
        sleep 0.2
    done
    assert_equal "$(published 'd["state"], d["done_until"]')" "('running', '1993-02-02')"
    assert_equal "$(published 'd["last_commit_at"] is not None')" True

    kill -TERM -- "-${pid}"
    local code=0
    wait "${pid}" || code=$?
    assert_equal "${code}" 143
    assert_equal "$(published 'd["state"], "exit status 143" in d["detail"]')" "('failed', True)"
    # No beat is left behind, and the progress stays as it ended.
    local ended
    ended="$(cat "${PUBLISHED}")"
    sleep 2.5
    assert_equal "$(cat "${PUBLISHED}")" "${ended}"
}

@test "a download killed outright stops beating" {
    # Only the script, with SIGKILL: no EXIT trap runs; its beat loop must not go on (the page
    # would show it downloading for ever).
    FAKE_SLEEP=30 setsid bash "${REPO}/scripts/download.sh" --project-dir "${PROJECT}" \
        --virtual-env "${PROJECT}/venv" --env-file "" --status-url "${PUBLISHED}" --heartbeat 1 \
        --start 1993-01-01 --end 1993-06-01 --attempts 1 historical_res-1p0 \
        > "${BATS_TEST_TMPDIR}/output" 2>&1 3>&- &
    local pid=$!
    for _ in $(seq 300); do
        [[ -f "${PUBLISHED}" ]] && break
        sleep 0.2
    done
    assert_file_exists "${PUBLISHED}"
    # A first beat: the loop runs.
    local started
    started="$(published 'd["updated_at"]')"
    for _ in $(seq 150); do
        [[ "$(published 'd["updated_at"]')" != "${started}" ]] && break
        sleep 0.2
    done
    assert_not_equal "$(published 'd["updated_at"]')" "${started}"
    kill -KILL "${pid}"
    wait "${pid}" || true
    # The loop notices within a beat; a beat already under way (each takes seconds: it starts
    # arco-ocean) may still land.
    sleep 5
    local last
    last="$(cat "${PUBLISHED}")"
    # Without the check, a beat at least every few seconds.
    sleep 8
    # The stand-in and its sleep are left: stop them with the process group.
    kill -TERM -- "-${pid}" 2>/dev/null || true
    assert_equal "$(cat "${PUBLISHED}")" "${last}"
    assert_equal "$(published 'd["state"]')" running
}

@test "an extension starts where the output ends" {
    "${REPO}/.venv/bin/python" "${FIXTURES}/blocks.py" "${DATA_ROOT}/historical/res=1p0" \
        1993-01-01/1993-02-02
    FAKE_BLOCKS="1993-02-02/1993-03-06" run bash "${REPO}/scripts/download.sh" \
        --project-dir "${PROJECT}" --virtual-env "${PROJECT}/venv" --env-file "" \
        --status-url "${PUBLISHED}" --extend --end 1993-06-01 --attempts 1 historical_res-1p0
    assert_success
    assert_equal "$(published 'd["start"], d["done_until"], d["state"]')" \
        "('1993-02-02', '1993-03-06', 'finished')"
}

@test "a progress that cannot be published does not stop the download" {
    # A directory where the document goes: it cannot be written.
    mkdir -p "${PUBLISHED}"
    download
    assert_success
    assert_output --partial "Warning: the progress (start) could not be updated"
    assert_output --partial "Download of historical_res-1p0 finished"
}

@test "an earlier download's state is not this one's" {
    # Its state file left by a download that finished; this one fails before its start writes.
    mkdir -p "${PROJECT}/logs/download"
    local state="${PROJECT}/logs/download/progress_historical_res-1p0.json"
    echo '{"left": "by an earlier download"}' > "${state}"
    # Its progress cannot even start: the trap's end must not end the earlier download's.
    stub arco-ocean 'exit 1'
    ARCO_OCEAN_CLI="${STUBS}/arco-ocean" download
    assert_success
    assert_file_not_exists "${state}"
    run calls
    assert_line --regexp "^arco-ocean progress .* end finished$"
}

@test "without --status-url, no progress" {
    run bash "${REPO}/scripts/download.sh" --project-dir "${PROJECT}" \
        --virtual-env "${PROJECT}/venv" --env-file "" --start 1993-01-01 --end 1993-06-01 \
        --attempts 1 historical_res-1p0
    assert_success
    assert_file_not_exists "${PROJECT}/logs/download/progress_historical_res-1p0.json"
    assert_file_not_exists "${PROJECT}/logs/download/progress.log"
}

@test "--heartbeat is checked" {
    download --heartbeat 0
    assert_failure 1
    assert_output --partial "--heartbeat"
}

# The scripts copied into the project with a stand-in alert.sh (the real one would reach GitHub),
# which records its arguments.
with_alert_stub() {
    copy_scripts download.sh climatology.sh
    stub_at "${PROJECT}/scripts/alert.sh"
}

# Wait for the stand-in alert.sh's call ending with EVENT (it runs in the background).
alerted() {
    for _ in $(seq 100); do
        if grep -q "^alert.sh .* $1$" "${CALLS}" 2>/dev/null; then return 0; fi
        sleep 0.1
    done
    calls
    return 1
}

@test "--alert reports a failed download, then its recovery" {
    with_alert_stub
    local state="${PROJECT}/logs/download/progress_historical_res-1p0.json"
    FAKE_CODE=1 run bash "${PROJECT}/scripts/download.sh" --project-dir "${PROJECT}" \
        --virtual-env "${PROJECT}/venv" --env-file "" --alert --start 1993-01-01 \
        --end 1993-06-01 --attempts 1 historical_res-1p0
    assert_failure 1
    alerted failed
    # --alert checked first, at the start; at the end, the run's start for the report.
    run grep "^alert.sh" "${CALLS}"
    assert_line --index 0 "alert.sh --check"
    assert_line --index 1 --regexp "^alert.sh --kind download --name historical_res-1p0 --state-file ${state} --exit-status 1 --run-started 20[0-9-]+T[0-9:.]+Z failed$"
    # The state is kept for the issue's summary, though nothing is published.
    assert_file_exists "${state}"
    assert_file_not_exists "${PUBLISHED}"
    rm "${CALLS}"
    run bash "${PROJECT}/scripts/download.sh" --project-dir "${PROJECT}" \
        --virtual-env "${PROJECT}/venv" --env-file "" --alert --start 1993-01-01 \
        --end 1993-06-01 --attempts 1 historical_res-1p0
    assert_success
    alerted finished
    run grep "^alert.sh" "${CALLS}"
    assert_output --regexp " --exit-status 0 --run-started [^ ]+ finished$"
}

@test "a download reports arco-make's exit status, and how to continue an extension" {
    with_alert_stub
    "${REPO}/.venv/bin/python" "${FIXTURES}/blocks.py" "${DATA_ROOT}/historical/res=1p0" \
        1993-01-01/1993-02-02
    # Killed for want of memory at every attempt: download.sh exits 1, arco-make 137.
    FAKE_CODE=137 run bash "${PROJECT}/scripts/download.sh" --project-dir "${PROJECT}" \
        --virtual-env "${PROJECT}/venv" --env-file "" --status-url "${PUBLISHED}" --alert \
        --extend --end 1993-06-01 --attempts 1 historical_res-1p0
    assert_failure 1
    assert_equal "$(published 'd["detail"]')" \
        "Stopped (exit status 137): rerun it with --extend --resume."
    alerted failed
    run grep "^alert.sh --kind" "${CALLS}"
    assert_output --partial " --exit-status 137 "
}

@test "--alert that cannot report stops the run before it starts" {
    with_alert_stub
    stub_at "${PROJECT}/scripts/alert.sh" 'echo "Error: no token file." >&2; exit 1'
    run bash "${PROJECT}/scripts/download.sh" --project-dir "${PROJECT}" \
        --virtual-env "${PROJECT}/venv" --env-file "" --alert --start 1993-01-01 \
        --end 1993-06-01 --attempts 1 historical_res-1p0
    assert_failure 1
    assert_output --partial "--alert cannot report"
    run calls
    refute_line --partial "arco-make"
}

@test "the statistics publish their state, and --alert reports a failure" {
    with_alert_stub
    mkdir -p "${PROJECT}/configs/climatology"
    touch "${PROJECT}/configs/climatology/historical_res-1p0.toml"
    local PUBLISHED="${PROJECT}/www/statistics.json"
    # The computation writes its output in one commit (an empty run here: the repository made).
    FAKE_BLOCKS=" " run bash "${PROJECT}/scripts/climatology.sh" --project-dir "${PROJECT}" \
        --virtual-env "${PROJECT}/venv" --env-file "" --status-url "${PUBLISHED}" \
        historical_res-1p0
    assert_success
    assert_equal "$(published 'd["kind"], d["state"], d["start"], d["end"], d["done_until"]')" \
        "('statistics', 'finished', None, None, None)"
    assert_equal "$(published 'd["last_commit_at"] is not None')" True
    FAKE_CODE=1 run bash "${PROJECT}/scripts/climatology.sh" --project-dir "${PROJECT}" \
        --virtual-env "${PROJECT}/venv" --env-file "" --status-url "${PUBLISHED}" --alert \
        historical_res-1p0
    assert_failure 1
    assert_equal "$(published 'd["state"], "rerun it." in d["detail"]')" "('failed', True)"
    alerted failed
    run grep "^alert.sh" "${CALLS}"
    assert_line --regexp "^alert.sh --kind statistics --name historical_res-1p0 --state-file .*/logs/climatology/progress_historical_res-1p0.json --exit-status 1 --run-started .* failed$"
}
