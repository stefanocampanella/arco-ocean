#!/usr/bin/env bats
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
#
# scripts/install_units.sh, with stand-ins for systemctl and loginctl that record their calls.

setup() {
    load common
    common_setup
    stub systemctl
    stub loginctl 'echo "${FAKE_LINGER:-no}"'
    export HOME="${BATS_TEST_TMPDIR}/home" XDG_CONFIG_HOME="${BATS_TEST_TMPDIR}/config" USER=someone
    UNITS="${XDG_CONFIG_HOME}/systemd/user"
}

install() {
    run bash "${REPO}/scripts/install_units.sh" "$@"
}

@test "it links the units and writes the drop-ins" {
    install --alerts -- --image a%b.sif
    assert_success
    assert_output --partial "sudo loginctl enable-linger someone"
    local forecast="${UNITS}/arco-ocean-forecast.service.d/local.conf"
    assert_file_contains "${forecast}" "^WorkingDirectory=${REPO}$"
    # % doubled: systemd would read it as a specifier.
    assert_file_contains "${forecast}" '^Environment="FORECAST_OPTIONS=--image a%%b.sif"$'
    # The collection's outcome starts its alert.
    assert_file_contains "${forecast}" "^OnFailure=arco-ocean-alert@failed.service$"
    assert_file_contains "${forecast}" "^OnSuccess=arco-ocean-alert@finished.service$"
    local alert="${UNITS}/arco-ocean-alert@.service.d/local.conf"
    assert_file_contains "${alert}" "^WorkingDirectory=${REPO}$"
    # The heartbeat's state file where forecast.sh writes it, whatever directory systemd starts in.
    assert_file_contains "${alert}" "^Environment=\"ALERT_OPTIONS=--state-file ${REPO}/logs/forecast/status.json\"$"
    run calls
    assert_line "systemctl --user link ${REPO}/systemd/arco-ocean-forecast.service ${REPO}/systemd/arco-ocean-forecast.timer"
    assert_line "systemctl --user link ${REPO}/systemd/arco-ocean-alert@.service"
    assert_line "systemctl --user enable --now arco-ocean-forecast.timer"
    # Reloaded before the timer is enabled.
    local reload enable
    reload="$(calls | grep -n 'daemon-reload' | head -1 | cut -d: -f1)"
    enable="$(calls | grep -n 'enable --now' | cut -d: -f1)"
    [[ ${reload} -lt ${enable} ]]
}

@test "the alert's options: the repository, and the state file of the collection's directories" {
    install --alerts --alert-repo someone/arco-ocean -- --log-dir /var/forecast
    assert_success
    assert_file_contains "${UNITS}/arco-ocean-alert@.service.d/local.conf" \
        '^Environment="ALERT_OPTIONS=--repo someone/arco-ocean --state-file /var/forecast/status.json"$'
    install --alerts -- --project-dir elsewhere
    assert_success
    assert_file_contains "${UNITS}/arco-ocean-alert@.service.d/local.conf" \
        "ALERT_OPTIONS=--state-file ${REPO}/elsewhere/logs/forecast/status.json"
    install --alerts --alert-repo "a b"
    assert_failure 1
    assert_output --partial "takes OWNER/REPO"
    install --alert-repo someone/arco-ocean
    assert_failure 1
    assert_output --partial "goes with --alerts"
}

@test "without alerts, or without starting" {
    install --alerts
    ln -s "${REPO}/systemd/arco-ocean-alert@.service" "${UNITS}/arco-ocean-alert@.service"
    install --no-start
    assert_success
    assert_output --partial "without alerts"
    run calls
    assert_line "systemctl --user enable arco-ocean-forecast.timer"
    local drop_in="${UNITS}/arco-ocean-forecast.service.d/local.conf"
    assert_file_contains "${drop_in}" '^Environment="FORECAST_OPTIONS="$'
    assert_file_not_contains "${drop_in}" "OnFailure"
    # The alerts installed before are gone.
    assert_not_exists "${UNITS}/arco-ocean-alert@.service"
    assert_not_exists "${UNITS}/arco-ocean-alert@.service.d"
}

@test "the watchdog's keepalive of before is removed" {
    # Installed until 26 Nov 2026: its files left the checkout, its links dangle.
    mkdir -p "${UNITS}/arco-ocean-watchdog-keepalive.service.d" "${UNITS}/timers.target.wants"
    echo "[Service]" > "${UNITS}/arco-ocean-watchdog-keepalive.service.d/local.conf"
    local unit
    for unit in service timer; do
        ln -s "${BATS_TEST_TMPDIR}/gone.${unit}" "${UNITS}/arco-ocean-watchdog-keepalive.${unit}"
    done
    ln -s "${BATS_TEST_TMPDIR}/gone.timer" "${UNITS}/timers.target.wants/arco-ocean-watchdog-keepalive.timer"
    install
    assert_success
    assert_output --partial "Removed the watchdog's keepalive"
    run find "${UNITS}" -name 'arco-ocean-watchdog*'
    assert_output ""
    run calls
    assert_line "systemctl --user disable --now arco-ocean-watchdog-keepalive.timer"
}

@test "a refused install removes nothing" {
    mkdir -p "${UNITS}"
    ln -s "${BATS_TEST_TMPDIR}/gone.service" "${UNITS}/arco-ocean-watchdog-keepalive.service"
    install --alerts --alert-repo "a b"
    assert_failure 1
    assert_link_exists "${UNITS}/arco-ocean-watchdog-keepalive.service"
    assert_file_not_exists "${CALLS}"
}

@test "lingering on: no advice" {
    FAKE_LINGER=yes install
    assert_success
    refute_output --partial "enable-linger"
}

@test "options systemd would split or expand are refused" {
    local option
    for option in "a b" 'a"b' "a'b" 'a\b' '$HOME'; do
        install -- --env-file "${option}"
        assert_failure 1
        assert_output --partial "Error: option"
    done
    assert_file_not_exists "${CALLS}"
}

@test "forecast.sh's options go after the separator" {
    install --image x.sif
    assert_failure 1
    assert_output --partial "go after --"
}

@test "--uninstall removes the links and the drop-ins, the alerts first" {
    install --alerts
    local name
    for name in arco-ocean-forecast.service arco-ocean-alert@.service; do
        ln -s "${REPO}/systemd/${name}" "${UNITS}/${name}"
    done
    touch "${UNITS}/unrelated.service"
    # A drop-in of the user's own (systemctl --user edit) stays.
    echo "[Service]" > "${UNITS}/arco-ocean-forecast.service.d/override.conf"
    install --uninstall
    assert_success
    run ls "${UNITS}"
    assert_output "$(printf 'arco-ocean-forecast.service.d\nunrelated.service')"
    run ls "${UNITS}/arco-ocean-forecast.service.d"
    assert_output override.conf
    run calls
    assert_line "systemctl --user disable --now arco-ocean-forecast.timer"
    # A collection running is stopped too, after the alerts: stopped, it fails its unit, which
    # would report it.
    local alerts collection
    alerts="$(calls | grep -n 'stop arco-ocean-alert@\*.service' | cut -d: -f1)"
    collection="$(calls | grep -n 'stop arco-ocean-forecast.service' | cut -d: -f1)"
    [[ -n "${alerts}" && ${alerts} -lt ${collection} ]]
}

@test "from another checkout, it moves the units" {
    mkdir -p "${UNITS}" "${BATS_TEST_TMPDIR}/old-checkout"
    touch "${BATS_TEST_TMPDIR}/old-checkout/arco-ocean-forecast.service"
    ln -s "${BATS_TEST_TMPDIR}/old-checkout/arco-ocean-forecast.service" "${UNITS}/arco-ocean-forecast.service"
    install
    assert_success
    # The old link is gone (systemctl link, a stand-in here, would make the new one), the timer
    # disabled before.
    assert_link_not_exists "${UNITS}/arco-ocean-forecast.service"
    local disable link
    disable="$(calls | grep -n 'disable arco-ocean-forecast.timer' | cut -d: -f1)"
    link="$(calls | grep -n "link ${REPO}/systemd/arco-ocean-forecast.service" | cut -d: -f1)"
    [[ ${disable} -lt ${link} ]]
}

@test "a unit file of the user's own is not replaced" {
    mkdir -p "${UNITS}"
    echo "[Timer]" > "${UNITS}/arco-ocean-forecast.timer"
    install
    assert_failure 1
    assert_output --partial "a file of its own"
    assert_file_contains "${UNITS}/arco-ocean-forecast.timer" '^\[Timer\]$'
}
