#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT

# scripts/alert.sh
#
# Report on GitHub, as issues, from the machine that runs them:
# - the forecast collection (--kind forecast, the default): systemd runs it when the collection's
#   unit fails (OnFailure=, EVENT failed: download failed, collection behind, stopped, timed out)
#   or succeeds (OnSuccess=, EVENT finished), as arco-ocean-alert@EVENT.service
#   (scripts/install_units.sh --alerts). failed: a comment on the open issue labelled
#   forecast-alert, or a new one; finished: the open issues, if any, closed with a comment.
# - a one-off run (--kind download or statistics, --name RECIPE): download.sh and climatology.sh
#   --alert run it when they end, with their exit status. failed: a comment on the open issue of
#   that recipe (labelled download-alert or statistics-alert, its title naming the recipe, which
#   is how it is found: keep it), or a new one; finished: that recipe's open issues closed. A
#   report still trying when a later run of the recipe has started (--run-started, the run's start
#   in its state file) is dropped: it would reopen, or close, the later run's issue.
# --check checks what a report needs (gh, the token) and exits: the scripts run it when they
# start, so that a missing token fails then, not days later.
# GitHub notifies the repository's watchers of each. A report that fails (GitHub or the network
# down) is tried again (--attempts, --retry-delay), each attempt a run of this script with the
# same environment, MONITOR_* included.
#
# The issue tells what systemd tells (its MONITOR_* variables: the unit's result, exit code and
# status, the invocation, for journalctl), or the run's exit status, and the public content of the
# heartbeat or progress (arco-ocean status summary, arco-ocean progress summary); never logs,
# which may hold tokens, nor paths or host names: the repository is public.
#
# It needs gh (GitHub CLI) and a token in a file only its owner can read: a fine-grained personal
# access token for the repository alone, with the permission "Issues: Read and write".

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh" || { echo "Error: ${SCRIPT_DIR}/lib/common.sh is missing." >&2; exit 1; }

usage() {
    cat <<EOF
alert.sh
    Report the failure or recovery of the forecast collection, or of a one-off run, on GitHub,
    as an issue.

SYNOPSIS
    $0 [options] failed|finished

DESCRIPTION
    Options:
        --kind KIND          forecast (default; run by systemd), download or statistics (a
                             one-off run: download.sh, climatology.sh --alert).
        --name RECIPE        The one-off run's recipe (e.g. historical_res-0p25).
        --exit-status N      The one-off run's exit status.
        --run-started TIME   The one-off run's start, as its state file has it (started_at).
        --check              Check gh and the token, then exit (no event).
        --repo OWNER/REPO    The repository (default: stefanocampanella/arco-ocean).
        --token-file FILE    The token (default: \${XDG_CONFIG_HOME:-~/.config}/arco-ocean/github-token);
                             it must not be readable by group or others.
        --state-file FILE    The heartbeat's or progress's state file (forecast default:
                             logs/forecast/status.json in this checkout, forecast.sh's default;
                             install_units.sh gives the collection's own).
        --attempts N         Reports in all, when GitHub cannot be reached (default: 6).
        --retry-delay SECONDS
                             Wait between them (default: 300).
        -h, --help           Show this help.
EOF
}

REPO="stefanocampanella/arco-ocean"
TOKEN_FILE="${XDG_CONFIG_HOME:-${HOME}/.config}/arco-ocean/github-token"
STATE_FILE=""
KIND="forecast"
NAME=""
EXIT_STATUS=""
RUN_STARTED=""
CHECK=false
EVENT=""
ATTEMPTS=6
RETRY_DELAY=300
ARGUMENTS=("$@")

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kind|--kind=*) option_value "$@"; KIND="${VALUE}"; shift "${SHIFT_BY}" ;;
        --name|--name=*) option_value "$@"; NAME="${VALUE}"; shift "${SHIFT_BY}" ;;
        --exit-status|--exit-status=*) option_value "$@"; EXIT_STATUS="${VALUE}"; shift "${SHIFT_BY}" ;;
        --run-started|--run-started=*) option_value "$@"; RUN_STARTED="${VALUE}"; shift "${SHIFT_BY}" ;;
        --check) CHECK=true; shift ;;
        --repo|--repo=*) option_value "$@"; REPO="${VALUE}"; shift "${SHIFT_BY}" ;;
        --token-file|--token-file=*) option_value "$@"; TOKEN_FILE="${VALUE}"; shift "${SHIFT_BY}" ;;
        --state-file|--state-file=*) option_value "$@"; STATE_FILE="${VALUE}"; shift "${SHIFT_BY}" ;;
        --attempts|--attempts=*) option_value "$@"; ATTEMPTS="${VALUE}"; shift "${SHIFT_BY}" ;;
        --retry-delay|--retry-delay=*) option_value "$@"; RETRY_DELAY="${VALUE}"; shift "${SHIFT_BY}" ;;
        -h|--help) usage; exit 0 ;;
        failed|finished)
            if [[ -n "${EVENT}" ]]; then echo "Error: one event only." >&2; exit 1; fi
            EVENT="$1"; shift ;;
        *) echo "Error: unrecognized argument '$1'." >&2; usage >&2; exit 1 ;;
    esac
done

set -euo pipefail

if [[ -z "${EVENT}" && "${CHECK}" == false ]]; then
    echo "Error: give the event, failed or finished." >&2
    usage >&2
    exit 1
fi
case "${KIND}" in
    forecast)
        if [[ -n "${NAME}" || -n "${EXIT_STATUS}" ]]; then
            die "--name and --exit-status are a one-off run's (--kind download or statistics)."
        fi ;;
    download|statistics)
        if [[ "${CHECK}" == false ]]; then
            # The name goes into the issue's title and the search for it: a recipe's characters
            # only.
            [[ "${NAME}" =~ ^[A-Za-z0-9_.-]+$ ]] || die "--kind ${KIND} needs --name RECIPE (letters, digits, _ . -)."
            [[ "${EXIT_STATUS}" =~ ^[0-9]+$ ]] || die "--kind ${KIND} needs --exit-status N."
        fi ;;
    *) die "--kind is forecast, download or statistics (got '${KIND}')." ;;
esac
positive_integer --attempts "${ATTEMPTS}"
seconds --retry-delay "${RETRY_DELAY}"
github_repo --repo "${REPO}"
if ! command -v gh >/dev/null 2>&1; then
    echo "Error: gh (GitHub CLI) is needed." >&2
    exit 1
fi
if [[ ! -f "${TOKEN_FILE}" ]]; then
    echo "Error: no token file '${TOKEN_FILE}'." >&2
    exit 1
fi
# The file's own mode, a link followed.
if [[ "$(stat -L -c %a "${TOKEN_FILE}")" != [4567]00 ]]; then
    echo "Error: '${TOKEN_FILE}' is readable by others: chmod 600 it." >&2
    exit 1
fi
# An empty token would let gh use its own login, with all its rights.
if ! grep -q '[^[:space:]]' "${TOKEN_FILE}"; then
    echo "Error: '${TOKEN_FILE}' is empty." >&2
    exit 1
fi

if [[ "${CHECK}" == true ]]; then
    echo "${REPO}: gh and the token are there for the reports."
    exit 0
fi

# The attempts: each a run of this script (ALERT_ATTEMPT set), which fails as a whole on any error
# (set -e), with the same arguments and environment.
if [[ -z "${ALERT_ATTEMPT:-}" ]]; then
    for (( attempt = 1; attempt <= ATTEMPTS; attempt++ )); do
        if ALERT_ATTEMPT="${attempt}" bash "${BASH_SOURCE[0]}" "${ARGUMENTS[@]}"; then
            exit 0
        fi
        if (( attempt < ATTEMPTS )); then
            echo "Report ${attempt} of ${ATTEMPTS} failed: trying again in ${RETRY_DELAY} s." >&2
            sleep "${RETRY_DELAY}"
        fi
    done
    echo "Error: the report failed ${ATTEMPTS} times." >&2
    exit 1
fi

LABEL="${KIND}-alert"
NOW="$(date -u '+%Y-%m-%d %H:%M UTC')"
case "${KIND}" in
    forecast)
        STATE_FILE="${STATE_FILE:-${CHECKOUT}/logs/forecast/status.json}"
        TITLE="Forecast collection failed"
        LABEL_DESCRIPTION="The forecast collection failed (scripts/alert.sh)"
        RECOVERED="Recovered: a collection succeeded at ${NOW}." ;;
    download)
        TITLE="Download ${NAME} failed"
        LABEL_DESCRIPTION="A download failed (scripts/download.sh --alert)"
        RECOVERED="Recovered: a download of ${NAME} succeeded at ${NOW}." ;;
    statistics)
        TITLE="Statistics ${NAME} failed"
        LABEL_DESCRIPTION="A computation of statistics failed (scripts/climatology.sh --alert)"
        RECOVERED="Recovered: the statistics of ${NAME} were computed at ${NOW}." ;;
esac

# The token goes to gh in its environment only, never on a command line.
github() {
    GH_TOKEN="$(< "${TOKEN_FILE}")" gh "$@"
}

# What systemd says about the unit, kept to the characters its values have.
monitor() {
    local VALUE="${!1:-}"
    VALUE="${VALUE//[^A-Za-z0-9_.-]/}"
    printf '%s' "${VALUE:-unknown}"
}

# The public content of the heartbeat (arco-ocean status summary, as forecast.sh runs it) or of
# the one-off run's progress (arco-ocean progress summary).
summary() {
    local command=status what="heartbeat"
    if [[ "${KIND}" != forecast ]]; then command=progress what="progress"; fi
    arco_ocean_command
    if [[ -f "${STATE_FILE}" ]] && "${ARCO_OCEAN[@]}" "${command}" --state-file "${STATE_FILE}" summary 2>/dev/null; then
        return 0
    fi
    echo "The ${what}'s state could not be read."
}

# A one-off run's report is dropped once a later run of the recipe has started (its state file,
# where every run writes, holds that run's start): it would reopen, or close, the later run's issue.
if [[ "${KIND}" != forecast && -n "${RUN_STARTED}" && -f "${STATE_FILE}" ]]; then
    arco_ocean_command
    NOW_STARTED="$("${ARCO_OCEAN[@]}" progress --state-file "${STATE_FILE}" get started_at 2>/dev/null || true)"
    if [[ -n "${NOW_STARTED}" && "${NOW_STARTED}" != "${RUN_STARTED}" ]]; then
        echo "${REPO}: a later run of ${NAME} has started (${NOW_STARTED}): this report (${EVENT}) is dropped."
        exit 0
    fi
fi

# The open alert issues, oldest first: the forecast's, all those of its label (one, unless one was
# opened by hand); a one-off run's, those of its label with its title. Listed into a variable, so
# that a failing gh fails the script (set -e), not an empty list.
if [[ "${KIND}" == forecast ]]; then
    SELECT='sort_by(.number) | .[].number'
else
    SELECT="map(select(.title == \"${TITLE}\")) | sort_by(.number) | .[].number"
fi
LISTED="$(github issue list --repo "${REPO}" --label "${LABEL}" --state open \
    --limit 100 --json number,title --jq "${SELECT}")"
ISSUES=()
if [[ -n "${LISTED}" ]]; then mapfile -t ISSUES <<< "${LISTED}"; fi
ISSUE="${ISSUES[0]:-}"

if [[ "${EVENT}" == finished ]]; then
    if [[ -z "${ISSUE}" ]]; then
        echo "${REPO}: no open ${LABEL} issue${NAME:+ for ${NAME}}, nothing to close."
        exit 0
    fi
    for NUMBER in "${ISSUES[@]}"; do
        github issue close "${NUMBER}" --repo "${REPO}" --comment "${RECOVERED}"
        echo "${REPO}: closed #${NUMBER}."
    done
    exit 0
fi

if [[ "${KIND}" == forecast ]]; then
    # What failed, from systemd's result and forecast.sh's exit status (see its --help).
    RESULT="$(monitor MONITOR_SERVICE_RESULT)"
    STATUS="$(monitor MONITOR_EXIT_STATUS)"
    case "${RESULT}/${STATUS}" in
        exit-code/"${BEHIND}") WHAT="The collection finished behind: a source may have stopped publishing (the flags tell which)." ;;
        exit-code/*) WHAT="A download failed, or the heartbeat could not be checked." ;;
        timeout/*) WHAT="The collection timed out (TimeoutStartSec): it hung." ;;
        signal/*|core-dump/*) WHAT="The collection was stopped by a signal." ;;
        *) WHAT="The collection did not succeed." ;;
    esac
    UNIT="arco-ocean-forecast"
    BODY="$(cat <<EOF
**The forecast collection failed** at ${NOW}. ${WHAT} systemd's result \`${RESULT}\`, exit \`$(monitor MONITOR_EXIT_CODE)\` \`${STATUS}\`.

$(summary)

Logs, on the machine that collects: \`journalctl --user -u ${UNIT} _SYSTEMD_INVOCATION_ID=$(monitor MONITOR_INVOCATION_ID)\`, and \`logs/forecast/\` in the checkout.

This issue is closed when a collection succeeds; each failure until then adds a comment.
EOF
)"
else
    case "${EXIT_STATUS}" in
        130) WHAT="It was interrupted (SIGINT)." ;;
        143) WHAT="It was stopped (SIGTERM)." ;;
        137) WHAT="It was killed (SIGKILL): out of memory, most likely." ;;
        "${NOT_PUBLISHED}") WHAT="A forecast run is not published yet: the runs before are stored." ;;
        *) WHAT="See its log." ;;
    esac
    if [[ "${KIND}" == download ]]; then
        RUN="The download of \`${NAME}\`" LOGS="logs/download/"
    else
        RUN="The statistics of \`${NAME}\`" LOGS="logs/climatology/"
    fi
    BODY="$(cat <<EOF
**${RUN} failed** at ${NOW}, exit status \`${EXIT_STATUS}\`. ${WHAT}

$(summary)

How to continue: the summary's first line. Logs, on the machine that ran it: in its log directory (\`${LOGS}\` in the checkout, unless \`--log-dir\` was given).

This issue is closed when a later run of \`${NAME}\` succeeds; each failure until then adds a comment.
EOF
)"
fi

if [[ -n "${ISSUE}" ]]; then
    printf '%s\n' "${BODY}" | github issue comment "${ISSUE}" --repo "${REPO}" --body-file -
    echo "${REPO}: commented on #${ISSUE}."
else
    github label create "${LABEL}" --repo "${REPO}" --color d03b3b --force \
        --description "${LABEL_DESCRIPTION}" >/dev/null
    printf '%s\n' "${BODY}" | github issue create --repo "${REPO}" --label "${LABEL}" \
        --title "${TITLE}" --body-file -
fi
