#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT

# scripts/forecast.sh
#
# Collect the ARCO-OCEAN forecast runs, at every resolution, with scripts/download.sh.
#
# Daily (systemd/arco-ocean-forecast.timer), it adds the runs after each repository's last one
# up to today's (arco-make download --extend: a day missed is caught up the next time, its
# GLO12 values then from later releases, flagged). The first time, --start backfills from that day (the end of the historical
# dataset). The forecast recipes (configs/download/forecast_res-<res>.toml) keep the last five
# years of runs. A run fails while one of its sources has not published it yet (a release
# late): it is attempted again (--attempts, --retry-delay), and else caught up the next day.
# Runs of this script never overlap (a lock in the log directory): a late run makes the next
# one wait. With --status-url, the collection publishes a heartbeat, a JSON document the
# ARCO-OCEAN web page reads (`arco-ocean status`, src/arco_ocean/status.py): its state, each
# resolution's, the newest run stored, updated every few minutes while it runs.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh" || { echo "Error: ${SCRIPT_DIR}/lib/common.sh is missing." >&2; exit 1; }

usage() {
    cat <<EOF
forecast.sh
    Add the forecast runs up to today's to the ARCO-OCEAN forecast repositories.

SYNOPSIS
    $0 [options]
    $0 --help

DESCRIPTION
    Options:
        --res LIST              Resolutions, comma-separated (default: 0p25,0p5,1p0).
        --start DATE            Backfill from this run (YYYY-MM-DD) into new repositories, instead
                                of extending existing ones (the first time).
        --end DATE              The day after the last run (default: tomorrow, UTC: today's run).
        --attempts N            Runs per resolution, the later ones resuming (default: 6).
        --retry-delay SECONDS   Wait between them (default: 1800: a late release).
        --project-dir DIR       Project root directory (default: current working directory).
        --log-dir DIR           Where the logs go (default: \${PROJECT_ROOT}/logs/forecast).
        --status-url URL        Publish the heartbeat there: an s3:// URL (through arco-make's
                                AWS profile) or a local path (default: none, no heartbeat).
        --heartbeat SECONDS     Between heartbeats while the collection runs (default: 300).
        --missing-after DAYS    Published with the heartbeat: the recipes' [forecast]
                                missing_after; the page calls the collection stale when a
                                resolution's newest run is older, or has waited longer for its
                                sources (default: 2).
        --stale-after HOURS     Published with the heartbeat: the page calls the collection
                                stale when none finished for that long (default: 30).
        -h, --help              Show this help.

    Other options (--image, --virtual-env, --env-file, --bind, --config-dir, --log-level) go to
    scripts/download.sh, as given. Outputs are DATA_ROOT/forecast/res=<res>: --data-root ROOT
    gives it, else scripts/lib/common.sh (resolved once, and given to every download); the
    heartbeat reads them there. The heartbeat is "arco-ocean status", run with uv in this
    checkout's environment (ARCO_OCEAN_CLI names another arco-ocean command): it reads the
    repositories with the arco-make pinned there, the default image's; with another --image or
    --virtual-env, keep the two in step.

    Exit status: 0 every run stored; 75 a source has not published the newest run yet (the
    runs before are stored); 3 the collection finished behind (see the heartbeat); 1 otherwise.

    Examples:
        $0 --start 2026-07-01                 # the first time: backfill to today's run
        $0                                    # every day, from systemd (docs/forecasts.md)
        $0 --status-url s3://BUCKET/status/forecast.json   # with the web page's heartbeat
        $0 --data-root s3://BUCKET            # the repositories at s3://BUCKET/forecast/res=<res>
EOF
}

common_defaults
RESOLUTIONS="0p25,0p5,1p0"
START_DATE=""
END_DATE=""
ATTEMPTS=6
RETRY_DELAY=1800
STATUS_URL=""
HEARTBEAT=300
STALE_AFTER=30
MISSING_AFTER=2

while [[ $# -gt 0 ]]; do
    # The shared options: --project-dir, --log-dir and --data-root are this script's; the
    # runner's (--image, --virtual-env, --env-file, --bind, --config-dir, --log-level) go on to
    # download.sh, as given (the environment file is read here too, for DATA_ROOT).
    common_option "$@"
    if [[ ${SHIFT_BY} -gt 0 ]]; then shift "${SHIFT_BY}"; continue; fi
    case "$1" in
        --res|--res=*) option_value "$@"; RESOLUTIONS="${VALUE}"; shift "${SHIFT_BY}" ;;
        --start|--start=*) option_value "$@"; START_DATE="${VALUE}"; shift "${SHIFT_BY}" ;;
        --end|--end=*) option_value "$@"; END_DATE="${VALUE}"; shift "${SHIFT_BY}" ;;
        --attempts|--attempts=*) option_value "$@"; ATTEMPTS="${VALUE}"; shift "${SHIFT_BY}" ;;
        --retry-delay|--retry-delay=*) option_value "$@"; RETRY_DELAY="${VALUE}"; shift "${SHIFT_BY}" ;;
        --status-url|--status-url=*) option_value "$@"; STATUS_URL="${VALUE}"; shift "${SHIFT_BY}" ;;
        --heartbeat|--heartbeat=*) option_value "$@"; HEARTBEAT="${VALUE}"; shift "${SHIFT_BY}" ;;
        --missing-after|--missing-after=*) option_value "$@"; MISSING_AFTER="${VALUE}"; shift "${SHIFT_BY}" ;;
        --stale-after|--stale-after=*) option_value "$@"; STALE_AFTER="${VALUE}"; shift "${SHIFT_BY}" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Error: unrecognized argument '$1'." >&2; usage >&2; exit 1 ;;
    esac
done

positive_integer --heartbeat "${HEARTBEAT}"
# Checked here too: download.sh would refuse them for every resolution, after the start.
positive_integer --attempts "${ATTEMPTS}"
seconds --retry-delay "${RETRY_DELAY}"
# Positive: the page and the heartbeat read 0 as their default, two days.
if ! [[ "${MISSING_AFTER}" =~ ^[0-9]+([.][0-9]+)?$ ]] || [[ "${MISSING_AFTER}" =~ ^0+([.]0+)?$ ]]; then
    die "--missing-after takes a positive number of days (got '${MISSING_AFTER}')."
fi
if ! [[ "${STALE_AFTER}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    die "--stale-after takes a number of hours (got '${STALE_AFTER}')."
fi

# Where outputs go (DATA_ROOT): resolved once, here, and given to every download (--data-root),
# so the heartbeat reads where they write.
enter_project
END_DATE="${END_DATE:-$(date -u -d tomorrow +%Y-%m-%d)}"
LOG_DIR="${LOG_DIR:-${PROJECT_ROOT}/logs/forecast}"
mkdir -p "${LOG_DIR}"

# One collection at a time: a collection by hand may meet the daily one.
exec 9> "${LOG_DIR}/.forecast.lock"
if ! flock -n 9; then
    echo "Another forecast collection is running (lock ${LOG_DIR}/.forecast.lock): waiting for it."
    flock 9
fi

# The heartbeat (--status-url): `arco-ocean status`, in this checkout's environment (uv; its
# arco-make is the release the image has), reads the repositories where scripts/download.sh
# writes them.
STATUS_FILE="${LOG_DIR}/status.json"
HEARTBEAT_PID=""
ENDED=false
arco_ocean_command

# Update the heartbeat (no-op without --status-url). It never stops the collection: a failure is
# logged in the log directory's status.log.
status() {
    [[ -n "${STATUS_URL}" ]] || return 0
    if ! "${ARCO_OCEAN[@]}" status --state-file "${STATUS_FILE}" --publish "${STATUS_URL}" "$@" \
        >> "${LOG_DIR}/status.log" 2>&1; then
        echo "Warning: the heartbeat ($1) could not be published: see ${LOG_DIR}/status.log." >&2
    fi
}

# Whatever ends the script (an error, a signal it can trap), the heartbeat says so: a collection
# that ends without ending its heartbeat was aborted. One killed outright stops beating, and the
# page calls it stale.
on_exit() {
    local code=$?
    local started=false
    [[ -n "${HEARTBEAT_PID}" ]] && started=true
    heartbeat_stop
    if [[ "${ENDED}" == false && "${started}" == true ]]; then
        status end aborted --detail "The collection stopped unexpectedly (exit status ${code})."
    fi
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ -n "${STATUS_URL}" ]]; then
    REPOS=()
    IFS=',' read -r -a RES_LIST <<< "${RESOLUTIONS}"
    # scripts/download.sh's default output for the recipe forecast_res-<res>.
    for RES in "${RES_LIST[@]}"; do
        REPO="$(default_output forecast "${RES}")" || exit 1
        REPOS+=(--repo "${RES}=${REPO}")
    done
    status start --target-run "$(date -u -d "${END_DATE} - 1 day" +%Y-%m-%d)" \
        --heartbeat-seconds "${HEARTBEAT}" --stale-after-hours "${STALE_AFTER}" \
        --missing-after-days "${MISSING_AFTER}" "${REPOS[@]}"
    # The beat, until the collection ends.
    heartbeat_start "${HEARTBEAT}" status beat
fi

if [[ -n "${START_DATE}" ]]; then
    MODE=(--start "${START_DATE}")
else
    MODE=(--extend)
fi

FAILED=()
WAITING=()
IFS=',' read -r -a RES_LIST <<< "${RESOLUTIONS}"
for RES in "${RES_LIST[@]}"; do
    echo "== forecast_res-${RES}: runs to ${END_DATE} (excluded) ($(date -u))"
    status res "${RES}" downloading
    CODE=0
    "${SCRIPT_DIR}/download.sh" --project-dir "${PROJECT_ROOT}" --log-dir "${LOG_DIR}" \
        "${MODE[@]}" --end "${END_DATE}" --attempts "${ATTEMPTS}" --retry-delay "${RETRY_DELAY}" \
        --data-root "${DATA_ROOT}" "${RUNNER_OPTIONS[@]+"${RUNNER_OPTIONS[@]}"}" \
        "forecast_res-${RES}" || CODE=$?
    if [[ ${CODE} -eq 0 ]]; then
        status res "${RES}" finished
    elif [[ ${CODE} -eq ${NOT_PUBLISHED} ]]; then
        WAITING+=("${RES}")
        status res "${RES}" not_published
    else
        FAILED+=("${RES}")
        status res "${RES}" failed
    fi
done

# A collection that ended with the runs stored, but behind (a source that stopped publishing: its
# runs are stored without it, days late, or wait every day; see `arco-ocean status overdue`),
# fails: the unit's alert (scripts/alert.sh) reports it, as the page shows it stale.
# `arco-ocean status overdue` exits with BEHIND for a collection that finished behind; this
# script too, so that the alert tells it from other failures.
overdue() {
    [[ -n "${STATUS_URL}" ]] || return 0
    local CODE=0
    "${ARCO_OCEAN[@]}" status --state-file "${STATUS_FILE}" overdue || CODE=$?
    if [[ ${CODE} -eq ${BEHIND} ]]; then
        echo "Forecast collection behind (see the heartbeat): reported as a failure." >&2
        exit "${BEHIND}"
    elif [[ ${CODE} -ne 0 ]]; then
        echo "The heartbeat could not tell whether the collection is behind: reported as a failure." >&2
        exit 1
    fi
}

ENDED=true
if [[ ${#FAILED[@]} -gt 0 ]]; then
    status end aborted --detail "The download failed at ${FAILED[*]}: the next collection resumes it."
    echo "Forecast collection failed at ${FAILED[*]} (see ${LOG_DIR}): the next run catches up." >&2
    exit 1
fi
if [[ ${#WAITING[@]} -gt 0 ]]; then
    status end finished --detail "A source has not published the newest run yet (${WAITING[*]}): the next collection adds it."
    echo "Forecast collection: the newest run is not published yet at ${WAITING[*]}; the next run catches up." >&2
    overdue
    # Not a failure (the unit counts it a success), but not every run stored: 75, as download.sh.
    exit "${NOT_PUBLISHED}"
fi
status end finished
overdue
echo "Forecast collection done ($(date -u))."
