#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT

# scripts/alert.sh
#
# Report the forecast collection on GitHub, from the machine that collects. systemd runs it when
# the collection's unit fails (OnFailure=, EVENT failed: download failed, collection behind,
# stopped, timed out) or succeeds (OnSuccess=, EVENT finished), as arco-ocean-alert@EVENT.service
# (scripts/install_units.sh --alerts). failed: a comment on the open issue labelled
# forecast-alert, or a new one; finished: the open issue, if any, closed with a comment. GitHub
# notifies the repository's watchers of each.
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
        --state-file FILE    The heartbeat's state file (default: logs/forecast/status.json, in
                             the checkout: forecast.sh's default log directory).
        -h, --help           Show this help.
EOF
}

REPO="stefanocampanella/arco-ocean"
TOKEN_FILE="${XDG_CONFIG_HOME:-${HOME}/.config}/arco-ocean/github-token"
STATE_FILE="logs/forecast/status.json"
EVENT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo) REPO="$2"; shift 2 ;;
        --repo=*) REPO="${1#*=}"; shift ;;
        --token-file) TOKEN_FILE="$2"; shift 2 ;;
        --token-file=*) TOKEN_FILE="${1#*=}"; shift ;;
        --state-file) STATE_FILE="$2"; shift 2 ;;
        --state-file=*) STATE_FILE="${1#*=}"; shift ;;
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

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
        COMMAND=(uv run --quiet --frozen --no-default-groups --project "${ROOT}" arco-ocean)
    fi
    if [[ -f "${STATE_FILE}" ]] && "${COMMAND[@]}" status --state-file "${STATE_FILE}" summary 2>/dev/null; then
        return 0
    fi
    echo "The heartbeat's state could not be read."
}

ISSUE="$(github issue list --repo "${REPO}" --label "${LABEL}" --state open --limit 1 \
    --json number --jq '.[0].number // empty')"

if [[ "${EVENT}" == finished ]]; then
    if [[ -z "${ISSUE}" ]]; then
        echo "${REPO}: no open ${LABEL} issue, nothing to close."
        exit 0
    fi
    github issue close "${ISSUE}" --repo "${REPO}" \
        --comment "Recovered: a collection succeeded at ${NOW}."
    echo "${REPO}: closed #${ISSUE}."
    exit 0
fi

BODY="$(cat <<EOF
**The forecast collection failed** at ${NOW}: systemd's result \`$(monitor MONITOR_SERVICE_RESULT)\`, exit \`$(monitor MONITOR_EXIT_CODE)\` \`$(monitor MONITOR_EXIT_STATUS)\`.

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
