#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT

# scripts/climatology.sh
#
# Compute the climatology and the anomaly standard deviation of one ARCO-OCEAN dataset with
# arco-make, on one machine (the project VM).
#
# Reads the dataset <product>/res=<res> and writes statistics/res=<res>, one Icechunk repository
# with the groups climatology and anomaly_std, from a recipe named <product>_res-<res>.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh" || { echo "Error: ${SCRIPT_DIR}/lib/common.sh is missing." >&2; exit 1; }

usage() {
    cat <<EOF
climatology.sh
    Compute the climatology and the anomaly standard deviation of one dataset with arco-make.

SYNOPSIS
    $0 [options] RECIPE
    $0 --help

DESCRIPTION
    Positional arguments:
        RECIPE                  Recipe name (looked up as CONFIG_DIR/RECIPE.toml) or path, named
                                <product>_res-<res>.toml (e.g. historical_res-0p25).

    Options:
        --input PATH            Input dataset (default: DATA_ROOT/<product>/res=<res>).
        --output PATH           Statistics output, groups climatology and anomaly_std
                                (default: DATA_ROOT/statistics/res=<res>). Neither with
                                --data-root.
        --replace               Write a new version of an existing output (arco-make --replace).
        --graph                 One Dask graph (arco-make --graph) instead of streaming the series
                                of the recipe's split_dims, as many at once as fit in memory
                                (arco-make --streaming, the default: the graph's memory grows
                                with the years, beyond the project VM's at 0.25 deg).
        --streaming             The default (accepted, as before).
        --dask-setup SETUP      arco-make's Dask scheduler (default: threads).
$(common_usage climatology)
        -h, --help              Show this help.
EOF
}

common_defaults
INPUT=""
OUTPUT=""
STREAMING=true
REPLACE=false
DASK_SETUP="threads"
POSITIONAL_ARGS=()

while [[ $# -gt 0 ]]; do
    common_option "$@"
    if [[ ${SHIFT_BY} -gt 0 ]]; then shift "${SHIFT_BY}"; continue; fi
    case "$1" in
        --input) INPUT="$2"; shift 2 ;;
        --input=*) INPUT="${1#*=}"; shift ;;
        --output) OUTPUT="$2"; shift 2 ;;
        --output=*) OUTPUT="${1#*=}"; shift ;;
        --streaming) STREAMING=true; shift ;;
        --graph) STREAMING=false; shift ;;
        --replace) REPLACE=true; shift ;;
        --dask-setup) DASK_SETUP="$2"; shift 2 ;;
        --dask-setup=*) DASK_SETUP="${1#*=}"; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; POSITIONAL_ARGS+=("$@"); break ;;
        -*) echo "Error: unrecognized option '$1'." >&2; usage >&2; exit 1 ;;
        *) POSITIONAL_ARGS+=("$1"); shift ;;
    esac
done

if [[ "${ROOT_GIVEN}" == true && ( -n "${INPUT}" || -n "${OUTPUT}" ) ]]; then
    die "give --input and --output, or --data-root, not both."
fi
RECIPE="${POSITIONAL_ARGS[0]:-}"
if [[ -z "${RECIPE}" || ${#POSITIONAL_ARGS[@]} -gt 1 ]]; then
    echo "Error: give exactly one RECIPE." >&2
    usage >&2
    exit 1
fi

enter_project
resolve_recipe climatology "${RECIPE}"

# Default paths: <product>/res=<res> in, statistics/ at the same resolution out.
if [[ -z "${INPUT}" || -z "${OUTPUT}" ]]; then
    recipe_product "${NAME}" \
        || die "cannot derive paths from '${NAME}' (expected <product>_res-<res>): give --input and --output."
    if [[ -z "${INPUT}" ]]; then
        INPUT="$(default_output "${PRODUCT}" "${RES}")" || exit 1
    fi
    if [[ -z "${OUTPUT}" ]]; then
        OUTPUT="$(default_output statistics "${RES}")" || exit 1
    fi
fi
make_parent "${OUTPUT}"
open_log climatology
arco_make_command

FLAGS=(--dask-setup="${DASK_SETUP}" --log-level="${LOG_LEVEL}")
if [[ "${REPLACE}" == true ]]; then
    FLAGS+=(--replace)
fi
if [[ "${STREAMING}" == true ]]; then
    FLAGS+=(--streaming)
else
    FLAGS+=(--graph)
fi

echo "Statistics of ${INPUT} to ${OUTPUT}, log: ${LOG_FILE} (started $(date -u), host $(hostname))"
"${RUN_CMD[@]}" compute-climatology "${FLAGS[@]}" -- \
    "${CONFIG_PATH}" "${INPUT}" "${OUTPUT}" >> "${LOG_FILE}" 2>&1
STATUS=$?
if [[ ${STATUS} -eq 0 ]]; then
    echo "Statistics of ${NAME} finished ($(date -u))."
else
    echo "Statistics of ${NAME} failed (exit code ${STATUS}): see ${LOG_FILE}." >&2
fi
exit ${STATUS}
