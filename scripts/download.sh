#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT

# scripts/download.sh
#
# Download one ARCO-OCEAN dataset with arco-make, in one resumable run.
#
# The recipes have no dates: [--start, --end) is written to one Icechunk repository, or, with
# --extend, the days after the repository's last up to --end. Block after block, each block a
# commit on the run's own branch; the repository's `main` moves to the new version only when
# every block is written. If the run fails, it is attempted again with `arco-make download
# --resume` (`--extend --resume` for an extension), which keeps the blocks already committed and
# writes the others (up to --attempts runs in all). A forecast download stopped at a run its
# sources have not published yet (exit status 75: the runs before are stored) is attempted again
# with --extend. Transient network errors are already retried inside arco-make, block by block
# (the recipe's [retries]).
#
# With --status-url, the download publishes its progress, a JSON document the ARCO-OCEAN web page
# shows (for the historical download, run once): "running" with the end of the newest block
# committed, read from the repository at the start, every --heartbeat seconds and at the end, then
# "finished" or "failed". A download killed outright stops updating it: the page calls it stale.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh" || { echo "Error: ${SCRIPT_DIR}/lib/common.sh is missing." >&2; exit 1; }

usage() {
    cat <<EOF
download.sh
    Download one dataset with arco-make into one Icechunk repository, resuming after failures.

SYNOPSIS
    $0 [options] RECIPE
    $0 --help

DESCRIPTION
    Positional arguments:
        RECIPE                  Recipe name (looked up as CONFIG_DIR/RECIPE.toml) or path, named
                                <product>_res-<res>.toml (e.g. historical_res-0p25).

    Options:
        --output PATH           Output repository: a directory, s3:// or gs:// URL (default:
                                DATA_ROOT/<product>/res=<res>, from the recipe name). Not with
                                --data-root.
        --start DATE            First day (YYYY-MM-DD): the recipes have no dates. Not with --extend.
        --end DATE              The day after the last (YYYY-MM-DD). Required.
        --extend                Append the days after the output's last, up to --end, as a new
                                version (arco-make --extend; resumed with --resume).
        --replace               Write a new version of an existing output (arco-make --replace).
        --resume                Continue a run that failed earlier (arco-make --resume).
        --attempts N            Runs in all, the later ones resuming (default: 3).
        --retry-delay SECONDS   Wait between runs (default: 60).
        --status-url URL        Publish the progress there: an s3:// URL (through arco-make's
                                AWS profile) or a local path (default: none). It is
                                "arco-ocean progress", run with uv in this checkout; its state
                                file is LOG_DIR/progress_RECIPE.json.
        --heartbeat SECONDS     Between updates of the progress (default: 300).
$(common_usage download)
        -h, --help              Show this help.

    Exit status: 0 the download finished; 75 a forecast run is not published yet (the runs
    before are stored); 1 otherwise.

    Examples:
        $0 --start 1993-01-01 --end 2026-07-01 historical_res-0p25
        $0 --extend --end 2026-08-01 historical_res-0p25
        $0 --start 1993-01-01 --end 2026-07-01 \\
            --status-url s3://BUCKET/status/historical.json historical_res-0p25
EOF
}

common_defaults
OUTPUT=""
START_DATE=""
END_DATE=""
REPLACE=false
RESUME=false
EXTEND=false
ATTEMPTS=3
RETRY_DELAY=60
STATUS_URL=""
HEARTBEAT=300
POSITIONAL_ARGS=()

while [[ $# -gt 0 ]]; do
    common_option "$@"
    if [[ ${SHIFT_BY} -gt 0 ]]; then shift "${SHIFT_BY}"; continue; fi
    case "$1" in
        --output|--output=*) option_value "$@"; OUTPUT="${VALUE}"; shift "${SHIFT_BY}" ;;
        --start|--start=*) option_value "$@"; START_DATE="${VALUE}"; shift "${SHIFT_BY}" ;;
        --end|--end=*) option_value "$@"; END_DATE="${VALUE}"; shift "${SHIFT_BY}" ;;
        --replace) REPLACE=true; shift ;;
        --extend) EXTEND=true; shift ;;
        --resume) RESUME=true; shift ;;
        --attempts|--attempts=*) option_value "$@"; ATTEMPTS="${VALUE}"; shift "${SHIFT_BY}" ;;
        --retry-delay|--retry-delay=*) option_value "$@"; RETRY_DELAY="${VALUE}"; shift "${SHIFT_BY}" ;;
        --status-url|--status-url=*) option_value "$@"; STATUS_URL="${VALUE}"; shift "${SHIFT_BY}" ;;
        --heartbeat|--heartbeat=*) option_value "$@"; HEARTBEAT="${VALUE}"; shift "${SHIFT_BY}" ;;
        -h|--help) usage; exit 0 ;;
        --) shift; POSITIONAL_ARGS+=("$@"); break ;;
        -*) echo "Error: unrecognized option '$1'." >&2; usage >&2; exit 1 ;;
        *) POSITIONAL_ARGS+=("$1"); shift ;;
    esac
done

if [[ -n "${OUTPUT}" && "${ROOT_GIVEN}" == true ]]; then
    die "give --output or --data-root, not both."
fi
RECIPE="${POSITIONAL_ARGS[0]:-}"
if [[ -z "${RECIPE}" || ${#POSITIONAL_ARGS[@]} -gt 1 ]]; then
    echo "Error: give exactly one RECIPE." >&2
    usage >&2
    exit 1
fi
[[ -n "${END_DATE}" ]] || die "give --end (the recipes have no dates)."
if [[ "${EXTEND}" == true && ( -n "${START_DATE}" || "${REPLACE}" == true ) ]]; then
    die "--extend starts the day after the output's last: not with --start nor --replace."
fi
if [[ "${EXTEND}" == false && -z "${START_DATE}" ]]; then
    die "give --start (the recipes have no dates), or --extend an existing output."
fi
if [[ "${REPLACE}" == true && "${RESUME}" == true ]]; then
    die "--replace starts over, --resume continues: give one of them."
fi
positive_integer --attempts "${ATTEMPTS}"
seconds --retry-delay "${RETRY_DELAY}"
positive_integer --heartbeat "${HEARTBEAT}"

enter_project
resolve_recipe download "${RECIPE}"

# Default output: DATA_ROOT/<product>/res=<res>, from a recipe named <product>_res-<res>.
if [[ -z "${OUTPUT}" ]]; then
    recipe_product "${NAME}" \
        || die "cannot derive the output from '${NAME}' (expected <product>_res-<res>): give --output."
    OUTPUT="$(default_output "${PRODUCT}" "${RES}")" || exit 1
fi
make_parent "${OUTPUT}"
open_log download
arco_make_command

echo "Download of ${NAME} to ${OUTPUT}, log: ${LOG_FILE} (started $(date -u), PID $$, host $(hostname))"

# The progress (--status-url): `arco-ocean progress`, in this checkout's environment, reads the
# output repository. It never stops the download: a failure is logged in LOG_DIR/progress.log.
PROGRESS_FILE="${LOG_DIR}/progress_${NAME}.json"
HEARTBEAT_PID=""
progress() {
    [[ -n "${STATUS_URL}" ]] || return 0
    if ! "${ARCO_OCEAN[@]}" progress --state-file "${PROGRESS_FILE}" --publish "${STATUS_URL}" \
        "$@" >> "${LOG_DIR}/progress.log" 2>&1; then
        echo "Warning: the progress ($1) could not be published: see ${LOG_DIR}/progress.log." >&2
    fi
}

# Whatever ends the script (its exits, an error, a signal it can trap), the progress says how.
# shellcheck disable=SC2329  # run by the EXIT trap, set with --status-url only
on_exit() {
    local code=$?
    heartbeat_stop
    if [[ ${code} -eq 0 ]]; then
        progress end finished
    elif [[ ${code} -eq ${NOT_PUBLISHED} ]]; then
        progress end failed --detail "Stopped at a forecast run not published yet: the runs before are stored."
    else
        progress end failed --detail "The download stopped (exit status ${code}): rerun it with --resume."
    fi
}

if [[ -n "${STATUS_URL}" ]]; then
    arco_ocean_command
    PROGRESS_START=()
    if [[ "${EXTEND}" == false ]]; then
        PROGRESS_START=(--start "${START_DATE}")
    fi
    progress start --name "${NAME}" --repo "${OUTPUT}" --end "${END_DATE}" \
        --heartbeat-seconds "${HEARTBEAT}" "${PROGRESS_START[@]+"${PROGRESS_START[@]}"}"
    trap on_exit EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    heartbeat_start "${HEARTBEAT}" progress beat
fi

STATUS=0
for (( attempt=1; attempt<=ATTEMPTS; attempt++ )); do
    FLAGS=(--no-progress --log-level="${LOG_LEVEL}" --end="${END_DATE}")
    MODE=()
    if [[ ${STATUS} -eq ${NOT_PUBLISHED} ]]; then
        # The runs before the one not published are stored: extend from there.
        EXTEND=true
        RESUME=false
        REPLACE=false
    fi
    if [[ "${EXTEND}" == true ]]; then
        MODE+=(--extend)
    else
        FLAGS+=(--start="${START_DATE}")
    fi
    if [[ ( ${attempt} -gt 1 && ${STATUS} -ne ${NOT_PUBLISHED} ) || "${RESUME}" == true ]]; then
        MODE+=(--resume)
    elif [[ "${REPLACE}" == true ]]; then
        MODE+=(--replace)
    fi
    echo "Run ${attempt}/${ATTEMPTS} ${MODE[*]+"${MODE[*]}"}"
    # Where this run's lines start in the log (none yet on the first run: the shell, not wc,
    # reported the missing file).
    RUN_START=0
    if [[ -f "${LOG_FILE}" ]]; then
        RUN_START=$(wc -l < "${LOG_FILE}")
    fi
    {
        echo "==== run ${attempt}/${ATTEMPTS} ${MODE[*]+"${MODE[*]}"} ($(date -u)) ===="
        "${RUN_CMD[@]}" download "${FLAGS[@]}" "${MODE[@]+"${MODE[@]}"}" -- "${CONFIG_PATH}" "${OUTPUT}"
    } >> "${LOG_FILE}" 2>&1
    STATUS=$?
    if [[ ${STATUS} -eq 0 ]]; then
        echo "Download of ${NAME} finished: ${OUTPUT} ($(date -u))."
        exit 0
    fi
    if [[ ${STATUS} -eq ${NOT_PUBLISHED} ]]; then
        echo "Run ${attempt}: a forecast run is not published yet; the runs before are stored."
    else
        echo "Run ${attempt} failed (exit code ${STATUS}): see ${LOG_FILE}."
    fi
    # A failed check of the recipe's [checks] fails again on the same data: no further attempt.
    if tail -n "+$((RUN_START + 1))" "${LOG_FILE}" | grep -q "A check of \[checks\] failed"; then
        echo "A check of the recipe failed (see the log): fix the cause, then rerun this command with --resume." >&2
        exit 1
    fi
    # Refused because an earlier run of this output failed (killed, say) and can be continued:
    # the next attempt resumes it (--resume, after the first), at once.
    if [[ ${attempt} -eq 1 ]] && tail -n "+$((RUN_START + 1))" "${LOG_FILE}" \
        | grep -q "A download run failed at .*--resume continues it"; then
        echo "Run 1: an earlier run failed and waits: resuming it."
        continue
    fi
    if [[ ${attempt} -lt ${ATTEMPTS} ]]; then
        sleep "${RETRY_DELAY}"
    fi
done
if [[ ${STATUS} -eq ${NOT_PUBLISHED} ]]; then
    echo "Download of ${NAME}: a forecast run is still not published after ${ATTEMPTS} runs; the runs before are stored, the next collection (--extend) continues." >&2
    exit "${NOT_PUBLISHED}"
fi
echo "Download of ${NAME} failed after ${ATTEMPTS} runs (see ${LOG_FILE}): rerun this command with --resume to continue, if the log shows a run waiting." >&2
exit 1
