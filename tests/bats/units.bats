#!/usr/bin/env bats
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
#
# The systemd user units (systemd/) and the scripts as files.

setup() {
    load common
    common_setup
}

@test "the units carry no machine paths" {
    # The machine's part (checkout, options) goes into drop-ins, written at install.
    run grep -l -e /home/ -e /data/ "${REPO}"/systemd/*
    assert_failure
    assert_file_contains "${REPO}/systemd/arco-ocean-forecast.service" \
        "scripts/forecast.sh --status-url s3://ogs-arco-ocean/status/forecast.json"
}

@test "systemd verifies the units" {
    command -v systemd-analyze >/dev/null || skip "needs systemd-analyze"
    # systemd's own check (syntax, settings, the commands they run); the template as its two
    # instances.
    local dir="${BATS_TEST_TMPDIR}/units" unit event names=()
    mkdir -p "${dir}"
    for unit in "${REPO}"/systemd/*; do
        if [[ "$(basename "${unit}")" == arco-ocean-alert@.service ]]; then
            for event in failed finished; do
                cp "${unit}" "${dir}/arco-ocean-alert@${event}.service"
                names+=("${dir}/arco-ocean-alert@${event}.service")
            done
        else
            cp "${unit}" "${dir}/"
            names+=("${dir}/$(basename "${unit}")")
        fi
    done
    cd "${dir}"
    run systemd-analyze --user verify "${names[@]}"
    assert_success
    run systemd-analyze calendar "*-*-* 12:00:00 UTC"
    assert_success
    assert_output --partial "12:00:00 UTC"
}

@test "the scripts are executable" {
    local script
    for script in "${REPO}"/scripts/*.sh; do
        assert_file_executable "${script}"
    done
}
