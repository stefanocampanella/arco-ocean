#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT

# scripts/install_units.sh
#
# Install the daily forecast collection as systemd user units, from this checkout: the units in
# systemd/ are linked (so a git pull changes them; then systemctl --user daemon-reload), and a
# drop-in per service gives this machine's part, the checkout and the options of forecast.sh.
# With --alerts, the collection's failures and recoveries are reported on GitHub
# (arco-ocean-alert@.service, scripts/alert.sh). Run it again to change the options; --uninstall
# removes everything it installed.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh" || { echo "Error: ${SCRIPT_DIR}/lib/common.sh is missing." >&2; exit 1; }

usage() {
    cat <<EOF
install_units.sh
    Install (or remove) the ARCO-OCEAN forecast collection's systemd user units.

SYNOPSIS
    $0 [--alerts [--alert-repo OWNER/REPO]] [--no-start] [-- FORECAST.SH OPTIONS...]
    $0 --uninstall

DESCRIPTION
    Options:
        --alerts        Report the collection's failures and recoveries as a GitHub issue
                        (scripts/alert.sh; needs its token file).
        --alert-repo OWNER/REPO
                        The repository of the issues (default: stefanocampanella/arco-ocean).
        --no-start      Install and enable the timer, but do not start it now.
        --uninstall     Stop the timer and a collection running, and remove the units and the
                        drop-ins this script wrote (other drop-ins stay).
        -h, --help      Show this help.

    Run from another checkout, it moves the units there. The options after -- go to every
    collection (scripts/forecast.sh), e.g. --bind /data, --data-root s3://BUCKET, --image FILE
    or --virtual-env DIR, and --env-file FILE; relative paths are from the checkout. They cannot
    hold spaces, quotes, backslashes or dollar signs.

    The units run only while their user is logged in, unless lingering is on (once, by root):
        sudo loginctl enable-linger \$USER
EOF
}

ALERTS=false
ALERT_REPO=""
START=true
UNINSTALL=false
OPTIONS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --alerts) ALERTS=true; shift ;;
        --alert-repo|--alert-repo=*) option_value "$@"; ALERT_REPO="${VALUE}"; shift "${SHIFT_BY}" ;;
        --no-start) START=false; shift ;;
        --uninstall) UNINSTALL=true; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; OPTIONS=("$@"); break ;;
        *) echo "Error: unrecognized argument '$1' (options of forecast.sh go after --)." >&2
           usage >&2; exit 1 ;;
    esac
done

set -euo pipefail

ROOT="${CHECKOUT}"
UNIT_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
FORECAST=arco-ocean-forecast
ALERT=arco-ocean-alert@
# Installed until 26 Nov 2026 (the GitHub watchdog's keepalive): removed whenever found.
KEEPER=arco-ocean-watchdog-keepalive

# systemd expands % specifiers in unit files: a literal % is %%.
escape() {
    printf '%s' "${1//%/%%}"
}

# The links made by systemctl --user link (to this checkout or another): removed before linking
# again, as systemctl refuses to replace them.
unlink_units() {
    local UNIT
    for UNIT in "$1.service" "$1.timer"; do
        if [[ -L "${UNIT_DIR}/${UNIT}" ]]; then rm -f "${UNIT_DIR}/${UNIT}"; fi
    done
}

# Stop and remove a unit (and its timer) with the drop-in this script wrote.
remove_units() {
    systemctl --user disable --now "$1.timer" 2>/dev/null || true
    # A collection running ends as stopped by a signal (its heartbeat: aborted); the next one, if
    # installed again, resumes it.
    systemctl --user stop "$1.service" 2>/dev/null || true
    unlink_units "$1"
    rm -f "${UNIT_DIR}/$1.service.d/local.conf"
    rmdir "${UNIT_DIR}/$1.service.d" 2>/dev/null || true
}

if [[ -n "${ALERT_REPO}" ]]; then github_repo --alert-repo "${ALERT_REPO}"; fi
if [[ -n "${ALERT_REPO}" ]] && ! ${ALERTS}; then
    echo "Error: --alert-repo goes with --alerts." >&2
    exit 1
fi

PROJECT_DIR=""
LOG_DIR=""
for (( i = 0; i < ${#OPTIONS[@]}; i++ )); do
    OPTION="${OPTIONS[i]}"
    if [[ "${OPTION}" =~ [[:space:]\"\'\\\$] ]]; then
        echo "Error: option '${OPTION}' holds a space, a quote, a backslash or a dollar sign." >&2
        exit 1
    fi
    # The alert reads the heartbeat's state file where the collection writes it.
    case "${OPTION}" in
        --project-dir) PROJECT_DIR="${OPTIONS[i + 1]:-}" ;;
        --project-dir=*) PROJECT_DIR="${OPTION#*=}" ;;
        --log-dir) LOG_DIR="${OPTIONS[i + 1]:-}" ;;
        --log-dir=*) LOG_DIR="${OPTION#*=}" ;;
    esac
done
# As forecast.sh: the project directory from the checkout (the units' working directory), the log
# directory from the project directory, by default its logs/forecast.
case "${PROJECT_DIR}" in
    "") PROJECT_DIR="${ROOT}" ;;
    /*) ;;
    *) PROJECT_DIR="${ROOT}/${PROJECT_DIR}" ;;
esac
case "${LOG_DIR}" in
    "") LOG_DIR="${PROJECT_DIR}/logs/forecast" ;;
    /*) ;;
    *) LOG_DIR="${PROJECT_DIR}/${LOG_DIR}" ;;
esac

# The keepalive's units (gone from the checkout: their links dangle), its timer's link included.
if [[ -L "${UNIT_DIR}/${KEEPER}.service" || -e "${UNIT_DIR}/${KEEPER}.service.d/local.conf" ]]; then
    remove_units "${KEEPER}"
    rm -f "${UNIT_DIR}/timers.target.wants/${KEEPER}.timer"
    echo "Removed the watchdog's keepalive installed before (${KEEPER}): the alerts replace it."
fi

if ${UNINSTALL}; then
    # The alerts first: stopping a collection running fails its unit, which would report it.
    rm -f "${UNIT_DIR}/${FORECAST}.service.d/local.conf"
    systemctl --user stop "${ALERT}*.service" 2>/dev/null || true
    unlink_units "${ALERT}"
    rm -f "${UNIT_DIR}/${ALERT}.service.d/local.conf"
    rmdir "${UNIT_DIR}/${ALERT}.service.d" 2>/dev/null || true
    systemctl --user daemon-reload
    remove_units "${FORECAST}"
    systemctl --user daemon-reload
    echo "Removed the units of ${FORECAST} and ${ALERT}."
    exit 0
fi

for UNIT in "${FORECAST}.service" "${FORECAST}.timer" "${ALERT}.service"; do
    if [[ -e "${UNIT_DIR}/${UNIT}" && ! -L "${UNIT_DIR}/${UNIT}" ]]; then
        echo "Error: ${UNIT_DIR}/${UNIT} is a file of its own, not a link: move it away." >&2
        exit 1
    fi
done

mkdir -p "${UNIT_DIR}"
# Installed before: the timer's links (timers.target.wants) may point to another checkout.
systemctl --user disable "${FORECAST}.timer" 2>/dev/null || true
unlink_units "${FORECAST}"
systemctl --user link "${ROOT}/systemd/${FORECAST}.service" "${ROOT}/systemd/${FORECAST}.timer"
mkdir -p "${UNIT_DIR}/${FORECAST}.service.d"
{
    echo "# Written by ${ROOT}/scripts/install_units.sh: this machine's part."
    if ${ALERTS}; then
        echo "[Unit]"
        echo "OnFailure=${ALERT}failed.service"
        echo "OnSuccess=${ALERT}finished.service"
    fi
    echo "[Service]"
    echo "WorkingDirectory=$(escape "${ROOT}")"
    echo "Environment=\"FORECAST_OPTIONS=$(escape "${OPTIONS[*]+"${OPTIONS[*]}"}")\""
} > "${UNIT_DIR}/${FORECAST}.service.d/local.conf"

unlink_units "${ALERT}"
if ${ALERTS}; then
    ALERT_OPTIONS=()
    if [[ -n "${ALERT_REPO}" ]]; then ALERT_OPTIONS+=(--repo "${ALERT_REPO}"); fi
    ALERT_OPTIONS+=(--state-file "${LOG_DIR}/status.json")
    systemctl --user link "${ROOT}/systemd/${ALERT}.service"
    mkdir -p "${UNIT_DIR}/${ALERT}.service.d"
    {
        echo "# Written by ${ROOT}/scripts/install_units.sh: this machine's part."
        echo "[Service]"
        echo "WorkingDirectory=$(escape "${ROOT}")"
        echo "Environment=\"ALERT_OPTIONS=$(escape "${ALERT_OPTIONS[*]+"${ALERT_OPTIONS[*]}"}")\""
    } > "${UNIT_DIR}/${ALERT}.service.d/local.conf"
else
    # Alerts installed before and not asked for now: removed, with the drop-in's OnFailure=.
    rm -f "${UNIT_DIR}/${ALERT}.service.d/local.conf"
    rmdir "${UNIT_DIR}/${ALERT}.service.d" 2>/dev/null || true
fi

systemctl --user daemon-reload
if ${START}; then
    systemctl --user enable --now "${FORECAST}.timer"
else
    systemctl --user enable "${FORECAST}.timer"
fi

if ${ALERTS}; then
    echo "Installed: ${FORECAST}, with its alerts (${ALERT}failed, ${ALERT}finished)" \
        "(systemctl --user list-timers; journalctl --user -u ${FORECAST})."
else
    echo "Installed: ${FORECAST}, without alerts (systemctl --user list-timers;" \
        "journalctl --user -u ${FORECAST})."
fi
if [[ "$(loginctl show-user "${USER:-$(id -un)}" --property=Linger --value 2>/dev/null)" != "yes" ]]; then
    echo "Lingering is off: the timers run only while you are logged in. Turn it on, once:"
    echo "    sudo loginctl enable-linger ${USER:-$(id -un)}"
fi
