#!/usr/bin/env bats
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
#
# scripts/alert.sh, with stand-ins for gh and the `arco-ocean` command that record their calls.

setup() {
    load common
    common_setup
    # gh answers FAKE_ISSUE (numbers, one per line) to the issue list, fails with FAKE_GH_FAIL,
    # keeps what it reads from --body-file - in $CALLS.body and the token it sees in $CALLS.env.
    stub gh '
if [[ -n "${FAKE_GH_FAIL:-}" ]]; then exit 1; fi
if [[ "$*" == "issue list "* ]]; then printf "%b" "${FAKE_ISSUE:-}"; fi
if [[ "$*" == *"--body-file -"* ]]; then cat >> "${CALLS}.body"; fi
if [[ -n "${GH_TOKEN:-}" ]]; then echo "token ${GH_TOKEN}" >> "${CALLS}.env"; fi'
    stub arco-ocean 'echo "**Collection finished.** The heartbeat'"'"'s summary."'
    export ARCO_OCEAN_CLI="${STUBS}/arco-ocean" XDG_CONFIG_HOME="${BATS_TEST_TMPDIR}/config"
    TOKEN="${XDG_CONFIG_HOME}/arco-ocean/github-token"
    mkdir -p "$(dirname "${TOKEN}")"
    echo "not-a-real-token" > "${TOKEN}"
    chmod 600 "${TOKEN}"
    # What systemd gives an OnFailure= unit.
    export MONITOR_SERVICE_RESULT=exit-code MONITOR_EXIT_CODE=exited MONITOR_EXIT_STATUS=1 \
        MONITOR_INVOCATION_ID=0123abcd
}

alert() {
    run bash "${REPO}/scripts/alert.sh" "$@"
}

body() {
    cat "${CALLS}.body"
}

@test "a failure opens an issue" {
    mkdir -p "${PROJECT}/logs"
    echo "{}" > "${PROJECT}/logs/status.json"
    alert --state-file "${PROJECT}/logs/status.json" failed
    assert_success
    run calls
    local repo="--repo stefanocampanella/arco-ocean"
    assert_line --index 0 "gh issue list ${repo} --label forecast-alert --state open --limit 100 --json number --jq sort_by(.number) | .[].number"
    assert_line "arco-ocean status --state-file ${PROJECT}/logs/status.json summary"
    assert_line --regexp "^gh label create forecast-alert ${repo} "
    assert_line --index "$((${#lines[@]} - 1))" "gh issue create ${repo} --label forecast-alert --title Forecast collection failed --body-file -"
    run body
    assert_output --partial "A download failed, or the heartbeat could not be checked."
    assert_output --partial "systemd's result \`exit-code\`, exit \`exited\` \`1\`"
    assert_output --partial "The heartbeat's summary."
    assert_output --partial "_SYSTEMD_INVOCATION_ID=0123abcd"
    # No path of the machine: the issue is public.
    refute_output --partial "${BATS_TEST_TMPDIR}"
}

@test "the token reaches gh through its environment only" {
    alert failed
    assert_success
    refute_output --partial "not-a-real-token"
    run grep -c not-a-real-token "${CALLS}" "${CALLS}.body"
    assert_output --partial "${CALLS}:0"
    assert_output --partial "${CALLS}.body:0"
    run head -1 "${CALLS}.env"
    assert_output "token not-a-real-token"
}

@test "a failure with an open issue comments on it" {
    # Values systemd would not give are kept to the characters its own have.
    MONITOR_EXIT_STATUS='1`@x <y>' FAKE_ISSUE=7 alert --state-file /nowhere/status.json failed
    assert_success
    run calls
    assert_line --index "$((${#lines[@]} - 1))" "gh issue comment 7 --repo stefanocampanella/arco-ocean --body-file -"
    refute_line --partial "issue create"
    run body
    assert_output --partial "exit \`exited\` \`1xy\`"
    # Without a state file, the summary says so.
    assert_output --partial "The heartbeat's state could not be read."
}

@test "a collection behind says so" {
    MONITOR_EXIT_STATUS=3 alert failed
    assert_success
    run body
    assert_output --partial "The collection finished behind: a source may have stopped publishing"
}

@test "a success closes the open issues" {
    # Two open: one opened by hand with the label, say.
    FAKE_ISSUE='3\n7' alert --repo someone/x finished
    assert_success
    run grep "issue close" "${CALLS}"
    assert_line --index 0 --regexp "^gh issue close 3 --repo someone/x --comment Recovered: a collection"
    assert_line --index 1 --regexp "^gh issue close 7 "
    # Nothing open: nothing to do.
    rm "${CALLS}"
    alert finished
    assert_success
    assert_output --partial "nothing to close"
    run calls
    assert_equal "${#lines[@]}" 1
}

@test "a report GitHub refuses is tried again" {
    FAKE_GH_FAIL=1 alert --attempts 3 --retry-delay 0 failed
    assert_failure 1
    assert_output --partial "the report failed 3 times"
    run calls
    assert_equal "${#lines[@]}" 3
    assert_line --index 2 --regexp "^gh issue list "
    alert --attempts 0 failed
    assert_failure 1
    assert_output --partial "--attempts takes a positive number"
}

@test "one event is needed" {
    alert
    assert_failure 1
    assert_output --partial "give the event"
    alert failed finished
    assert_output --partial "one event only"
    alert "done"
    assert_output --partial "unrecognized"
    assert_file_not_exists "${CALLS}"
}

@test "the token's file must be private, there, and not empty" {
    chmod 644 "${TOKEN}"
    alert failed
    assert_failure 1
    assert_output --partial "readable by others"
    alert --token-file "${TOKEN}.missing" failed
    assert_output --partial "no token file"
    # Empty, gh would use its own login instead.
    chmod 600 "${TOKEN}"
    echo > "${TOKEN}"
    alert failed
    assert_output --partial "is empty"
    assert_file_not_exists "${CALLS}"
}

@test "a linked token file is followed" {
    ln -s "${TOKEN}" "${TOKEN}.link"
    alert --token-file "${TOKEN}.link" finished
    assert_success
}
