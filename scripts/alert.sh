#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT

# scripts/alert.sh
#
# Report the forecast collection on GitHub, from the machine that collects. systemd runs it when
# the collection's unit fails (OnFailure=, EVENT failed: download failed, collection behind,
# stopped, timed out) or succeeds (OnSuccess=, EVENT finished), as arco-ocean-alert@EVENT.service
# (scripts/install_units.sh --alerts). failed: a comment on the open issue labelled
# forecast-alert, or a new one; finished: the open issues, if any, closed with a comment. GitHub
# notifies the repository's watchers of each. A report that fails (GitHub or the network down)
# is tried again (--attempts, --retry-delay), each attempt a run of this script with the same
# environment, MONITOR_* included.
#
# The issue tells what systemd tells (its MONITOR_* variables: the unit's result, exit code and
# status, the invocation, for journalctl) and the heartbeat's public content (arco-ocean status
# summary); never logs, which may hold tokens, nor paths or host names: the repository is public.
#
# It needs gh (GitHub CLI) and a token in a file only its owner can read: a fine-grained personal
# access token for the repository alone, with the permission "Issues: Read and write".

usage() {
    cat <<EOF
alert.sh
    Report the forecast collection's failure or recovery on GitHub, as an issue.

SYNOPSIS
    $0 [options] failed|finished

DESCRIPTION
    Options:
        --repo OWNER/REPO    The repository (default: stefanocampanella/arco-ocean).
        --token-file FILE    The token (default: \${XDG_CONFIG_HOME:-~/.config}/arco-ocean/github-token);
                             it must not be readable by group or others.
        --state-file FILE    The heartbeat's state file (default: logs/forecast/status.json in
                             this checkout, forecast.sh's default; install_units.sh gives the
                             collection's own).
        --attempts N         Reports in all, when GitHub cannot be reached (default: 6).
        --retry-delay SECONDS
                             Wait between them (default: 300).
        -h, --help           Show this help.
EOF
}

REPO="stefanocampanella/arco-ocean"
TOKEN_FILE="${XDG_CONFIG_HOME:-${HOME}/.config}/arco-ocean/github-token"
STATE_FILE=""
EVENT=""
ATTEMPTS=6
RETRY_DELAY=300
ARGUMENTS=("$@")

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo) REPO="$2"; shift 2 ;;
        --repo=*) REPO="${1#*=}"; shift ;;
        --token-file) TOKEN_FILE="$2"; shift 2 ;;
        --token-file=*) TOKEN_FILE="${1#*=}"; shift ;;
        --state-file) STATE_FILE="$2"; shift 2 ;;
        --state-file=*) STATE_FILE="${1#*=}"; shift ;;
        --attempts) ATTEMPTS="$2"; shift 2 ;;
        --attempts=*) ATTEMPTS="${1#*=}"; shift ;;
        --retry-delay) RETRY_DELAY="$2"; shift 2 ;;
        --retry-delay=*) RETRY_DELAY="${1#*=}"; shift ;;
        -h|--help) usage; exit 0 ;;
        failed|finished)
            if [[ -n "${EVENT}" ]]; then echo "Error: one event only." >&2; exit 1; fi
            EVENT="$1"; shift ;;
        *) echo "Error: unrecognized argument '$1'." >&2; usage >&2; exit 1 ;;
    esac
done

set -euo pipefail

if [[ -z "${EVENT}" ]]; then
    echo "Error: give the event, failed or finished." >&2
    usage >&2
    exit 1
fi
if ! [[ "${ATTEMPTS}" =~ ^[1-9][0-9]*$ && "${RETRY_DELAY}" =~ ^[0-9]+$ ]]; then
    echo "Error: --attempts takes a positive number, --retry-delay a number of seconds." >&2
    exit 1
fi
if [[ ! "${REPO}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    echo "Error: --repo takes OWNER/REPO (got '${REPO}')." >&2
    exit 1
fi
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

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_FILE="${STATE_FILE:-${ROOT}/logs/forecast/status.json}"
LABEL="forecast-alert"
UNIT="arco-ocean-forecast"
NOW="$(date -u '+%Y-%m-%d %H:%M UTC')"

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

# The heartbeat's public content (arco-ocean status summary, as forecast.sh runs it).
heartbeat() {
    local COMMAND
    if [[ -n "${ARCO_OCEAN_CLI:-}" ]]; then
        COMMAND=("${ARCO_OCEAN_CLI}")
    else
        COMMAND=(env -u PYTHONPATH -u PYTHONHOME
            uv run --quiet --frozen --no-default-groups --project "${ROOT}" arco-ocean)
    fi
    if [[ -f "${STATE_FILE}" ]] && "${COMMAND[@]}" status --state-file "${STATE_FILE}" summary 2>/dev/null; then
        return 0
    fi
    echo "The heartbeat's state could not be read."
}

# The open alert issues, oldest first (one, unless one was opened by hand). Listed into a
# variable, so that a failing gh fails the script (set -e), not an empty list.
LISTED="$(github issue list --repo "${REPO}" --label "${LABEL}" --state open \
    --limit 100 --json number --jq 'sort_by(.number) | .[].number')"
ISSUES=()
if [[ -n "${LISTED}" ]]; then mapfile -t ISSUES <<< "${LISTED}"; fi
ISSUE="${ISSUES[0]:-}"

if [[ "${EVENT}" == finished ]]; then
    if [[ -z "${ISSUE}" ]]; then
        echo "${REPO}: no open ${LABEL} issue, nothing to close."
        exit 0
    fi
    for NUMBER in "${ISSUES[@]}"; do
        github issue close "${NUMBER}" --repo "${REPO}" \
            --comment "Recovered: a collection succeeded at ${NOW}."
        echo "${REPO}: closed #${NUMBER}."
    done
    exit 0
fi

# What failed, from systemd's result and forecast.sh's exit status (see its --help).
RESULT="$(monitor MONITOR_SERVICE_RESULT)"
STATUS="$(monitor MONITOR_EXIT_STATUS)"
case "${RESULT}/${STATUS}" in
    exit-code/3) WHAT="The collection finished behind: a source may have stopped publishing (the flags tell which)." ;;
    exit-code/*) WHAT="A download failed, or the heartbeat could not be checked." ;;
    timeout/*) WHAT="The collection timed out (TimeoutStartSec): it hung." ;;
    signal/*|core-dump/*) WHAT="The collection was stopped by a signal." ;;
    *) WHAT="The collection did not succeed." ;;
esac

BODY="$(cat <<EOF
**The forecast collection failed** at ${NOW}. ${WHAT} systemd's result \`${RESULT}\`, exit \`$(monitor MONITOR_EXIT_CODE)\` \`${STATUS}\`.

$(heartbeat)

Logs, on the machine that collects: \`journalctl --user -u ${UNIT} _SYSTEMD_INVOCATION_ID=$(monitor MONITOR_INVOCATION_ID)\`, and \`logs/forecast/\` in the checkout.

This issue is closed when a collection succeeds; each failure until then adds a comment.
EOF
)"

if [[ -n "${ISSUE}" ]]; then
    printf '%s\n' "${BODY}" | github issue comment "${ISSUE}" --repo "${REPO}" --body-file -
    echo "${REPO}: commented on #${ISSUE}."
else
    github label create "${LABEL}" --repo "${REPO}" --color d03b3b --force \
        --description "The forecast collection failed (scripts/alert.sh)" >/dev/null
    printf '%s\n' "${BODY}" | github issue create --repo "${REPO}" --label "${LABEL}" \
        --title "Forecast collection failed" --body-file -
fi
