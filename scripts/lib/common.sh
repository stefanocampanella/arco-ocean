# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
# The variables set here are the sourcing scripts': not unused (SC2034).
# shellcheck shell=bash disable=SC2034
#
# scripts/lib/common.sh: what the scripts share, sourced by each of them. Sourcing it defines
# constants and functions and does nothing else.
#
# Where outputs go. The root of the outputs is DATA_ROOT: the repositories are
# DATA_ROOT/<product>/res=<res> (s3://ogs-arco-ocean for the bucket's layout). It comes, the first
# given winning, from the scripts' --data-root, the environment, the scripts' settings file, the
# environment file (scripts/.env: under $SCRATCH on clusters that have one), else the project's
# data/ (resolve_data_root).
#
# The settings file, $ARCO_OCEAN_SETTINGS or ~/.config/arco-ocean/settings (an empty
# ARCO_OCEAN_SETTINGS disables it), holds KEY=VALUE lines, `export`, quotes and comments allowed;
# it is read, not sourced: nothing in it is expanded, and a line it cannot read is an error (a
# mistake there would send terabytes to the local disk). Its one key is DATA_ROOT. The systemd
# units read it too, which do not have the shell's environment. arco-make's own settings
# (credentials, the AWS profile, TMPDIR, DASK_*) are in ~/.arcomakerc, which the scripts do not
# read: it holds secrets.

# The image of the arco-make version pinned in pyproject.toml (tests/python/test_image.py).
DEFAULT_IMAGE="oras://ghcr.io/stefanocampanella/arco-make:v0.2.0"
# arco-make's and download.sh's exit status when a forecast run is not published yet: the runs
# before it are stored.
NOT_PUBLISHED=75
# forecast.sh's exit status, and `arco-ocean status overdue`'s, for a collection finished behind.
BEHIND=3
# The checkout these scripts are in.
CHECKOUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Print an error and exit with 1.
die() {
    echo "Error: $*" >&2
    exit 1
}

# --- Options ---------------------------------------------------------------------------------

# The options download.sh and climatology.sh share (forecast.sh passes them on to download.sh):
# where the project and its recipes and logs are, where outputs go, and how arco-make runs. Their
# variables, with their defaults.
common_defaults() {
    PROJECT_ROOT=""
    CONFIG_DIR=""
    LOG_DIR=""
    LOG_LEVEL="info"
    ROOT_OPTION=""
    ROOT_GIVEN=false
    IMAGE="${DEFAULT_IMAGE}"
    VENV=""
    ENV_FILE="scripts/.env"
    BINDS=()
    # The runner's options as given, for a script that passes them on.
    RUNNER_OPTIONS=()
}

# The value of the option at the start of "$@", as `--option VALUE` or `--option=VALUE`: set VALUE,
# and SHIFT_BY to the number of arguments it took; exit if there is none (`shift 2` would not
# shift, and the caller's loop would not end).
option_value() {
    if [[ "$1" == *=* ]]; then
        VALUE="${1#*=}"
        SHIFT_BY=1
    elif [[ $# -ge 2 ]]; then
        VALUE="$2"
        SHIFT_BY=2
    else
        die "$1 needs a value."
    fi
}

# Read one of the shared options at the start of "$@": set its variable and SHIFT_BY to the
# number of arguments it took (0: not a shared option).
common_option() {
    local option="${1%%=*}" value
    case "${option}" in
        --project-dir|--config-dir|--log-dir|--log-level|--data-root|--image|--virtual-env|--env-file|--bind) ;;
        *) SHIFT_BY=0; return 0 ;;
    esac
    option_value "$@"
    value="${VALUE}"
    case "${option}" in
        --project-dir) PROJECT_ROOT="${value}" ;;
        --config-dir) CONFIG_DIR="${value}"; RUNNER_OPTIONS+=(--config-dir "${value}") ;;
        --log-dir) LOG_DIR="${value}" ;;
        --log-level) LOG_LEVEL="${value}"; RUNNER_OPTIONS+=(--log-level "${value}") ;;
        --data-root) ROOT_OPTION="${value}"; ROOT_GIVEN=true ;;
        --image) IMAGE="${value}"; RUNNER_OPTIONS+=(--image "${value}") ;;
        --virtual-env) VENV="${value}"; RUNNER_OPTIONS+=(--virtual-env "${value}") ;;
        --env-file) ENV_FILE="${value}"; RUNNER_OPTIONS+=(--env-file "${value}") ;;
        --bind) BINDS+=("${value}"); RUNNER_OPTIONS+=(--bind "${value}") ;;
    esac
}

# The shared options' help, for the scripts' usage. Usage: common_usage KIND (download, ...).
common_usage() {
    cat <<EOF
        --project-dir DIR       Project root directory (default: current working directory).
        --config-dir DIR        Where to look for recipes (default: \${PROJECT_ROOT}/configs/$1).
        --log-dir DIR           Where to write the log (default: \${PROJECT_ROOT}/logs/$1).
        --data-root ROOT        Where the default outputs go, DATA_ROOT: a directory, s3:// or
                                gs:// URL, e.g. s3://ogs-arco-ocean, the bucket's layout (default:
                                the environment's, the settings file's, scripts/.env's, else
                                the project's data/: scripts/lib/common.sh).
        --image IMAGE           Apptainer image (default: ${DEFAULT_IMAGE}).
        --virtual-env PATH      Run from a local virtual environment instead of Apptainer.
        --env-file FILE         Environment file to source (default: scripts/.env).
        --bind SRC[:DST[:OPTS]] Path to bind within the Apptainer container (repeatable).
        --log-level LEVEL       debug, info, warning, error or critical (default: info).
EOF
}

# A positive integer, else exit naming the option. Usage: positive_integer OPTION VALUE.
positive_integer() {
    [[ "$2" =~ ^[1-9][0-9]*$ ]] || die "$1 takes a positive integer (got '$2')."
}

# A number of seconds (0 included), else exit naming the option.
seconds() {
    [[ "$2" =~ ^[0-9]+$ ]] || die "$1 takes a number of seconds (got '$2')."
}

# --- The project, its recipes and logs -------------------------------------------------------

# Enter the project directory and resolve DATA_ROOT (after the options are read).
enter_project() {
    PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
    cd "${PROJECT_ROOT}" || die "cannot enter the project directory '${PROJECT_ROOT}'."
    # Absolute: the paths made from it are used from inside it (a relative one would be
    # resolved twice).
    PROJECT_ROOT="$(pwd)"
    resolve_data_root "${ENV_FILE}" "${ROOT_GIVEN}" "${ROOT_OPTION}" || exit 1
}

# Set CONFIG_PATH and NAME from a recipe's name or path. Usage: resolve_recipe KIND RECIPE
# (KIND: the folder of configs/, download or climatology).
resolve_recipe() {
    CONFIG_DIR="${CONFIG_DIR:-${PROJECT_ROOT}/configs/$1}"
    if [[ -f "$2" ]]; then
        CONFIG_PATH="$2"
    else
        CONFIG_PATH="${CONFIG_DIR}/${2%.toml}.toml"
    fi
    [[ -f "${CONFIG_PATH}" ]] || die "recipe '${CONFIG_PATH}' not found."
    NAME="$(basename "${CONFIG_PATH}" .toml)"
}

# Set PRODUCT and RES from a recipe named <product>_res-<res>; fail (1) for another name.
recipe_product() {
    [[ "$1" =~ ^([a-z0-9-]+)_res-([0-9]+p[0-9]+)$ ]] || return 1
    PRODUCT="${BASH_REMATCH[1]}"
    RES="${BASH_REMATCH[2]}"
}

# Set LOG_DIR (default: logs/KIND in the project), make it, and set LOG_FILE, named after the
# recipe and the time. Usage: open_log KIND.
open_log() {
    LOG_DIR="${LOG_DIR:-${PROJECT_ROOT}/logs/$1}"
    mkdir -p "${LOG_DIR}"
    LOG_FILE="${LOG_DIR}/${NAME}_$(date -u +%Y%m%dT%H%M%SZ).log"
}

# Make a local output's parent directory (a URL needs none).
make_parent() {
    if [[ "$1" != *://* ]]; then
        mkdir -p "$(dirname "$1")"
    fi
}

# --- Commands --------------------------------------------------------------------------------

# Set RUN_CMD, the arco-make command: the virtual environment's (--virtual-env), else the
# image's, through Apptainer with the binds (--bind).
arco_make_command() {
    if [[ -n "${VENV}" ]]; then
        # The environment's own arco-make: `uv run` here would use this project's environment,
        # ignoring VIRTUAL_ENV.
        [[ -x "${VENV}/bin/arco-make" ]] || die "no arco-make in the virtual environment '${VENV}'."
        RUN_CMD=("${VENV}/bin/arco-make")
        return 0
    fi
    command -v apptainer >/dev/null 2>&1 || die "Apptainer is required without --virtual-env."
    local bind
    RUN_CMD=(apptainer run)
    for bind in "${BINDS[@]+"${BINDS[@]}"}"; do
        RUN_CMD+=(--bind "${bind}")
    done
    RUN_CMD+=("${IMAGE}")
}

# Set ARCO_OCEAN, the `arco-ocean` command (the package, src/arco_ocean): this checkout's, with
# uv in its environment, isolated from the caller's Python settings (its arco-make is the
# lock's); ARCO_OCEAN_CLI names another (the tests').
arco_ocean_command() {
    if [[ -n "${ARCO_OCEAN_CLI:-}" ]]; then
        ARCO_OCEAN=("${ARCO_OCEAN_CLI}")
    else
        ARCO_OCEAN=(env -u PYTHONPATH -u PYTHONHOME
            uv run --quiet --frozen --no-default-groups --project "${CHECKOUT}" arco-ocean)
    fi
}

# A GitHub repository's OWNER/REPO, else exit naming the option. Usage: github_repo OPTION VALUE.
github_repo() {
    [[ "$2" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "$1 takes OWNER/REPO (got '$2')."
}

# --- Where outputs go ------------------------------------------------------------------------

# Print DATA_ROOT from the settings file (its last value; nothing without one); fail, saying
# why, on a line that is not a setting.
settings_data_root() {
    local file="${ARCO_OCEAN_SETTINGS-${XDG_CONFIG_HOME:-${HOME}/.config}/arco-ocean/settings}"
    if [[ -z "${file}" || ! -f "${file}" ]]; then
        return 0
    fi
    local line key value number=0 found=""
    while IFS= read -r line || [[ -n "${line}" ]]; do
        number=$((number + 1))
        if [[ "${line}" =~ ^[[:space:]]*(#.*)?$ ]]; then
            continue
        fi
        if [[ ! "${line}" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
            echo "Error: ${file}, line ${number}: not KEY=VALUE (no spaces around =)." >&2
            return 1
        fi
        key="${BASH_REMATCH[2]}"
        value="${BASH_REMATCH[3]}"
        # A comment after a space, then the spaces around the value.
        value="${value%%[[:space:]]#*}"
        value="${value#"${value%%[![:space:]]*}"}"
        value="${value%"${value##*[![:space:]]}"}"
        if [[ "${value}" =~ ^\"(.*)\"$ || "${value}" =~ ^\'(.*)\'$ ]]; then
            value="${BASH_REMATCH[1]}"
        elif [[ "${value}" == [\"\']* || "${value}" == *[\"\'] ]]; then
            echo "Error: ${file}, line ${number}: unbalanced quotes." >&2
            return 1
        fi
        if [[ "${key}" != DATA_ROOT ]]; then
            echo "Warning: ${file}, line ${number}: '${key}' is not a setting of the scripts; ignored." >&2
            continue
        fi
        if [[ -z "${value}" ]]; then
            echo "Error: ${file}, line ${number}: DATA_ROOT is empty (it would fall back to the local disk)." >&2
            return 1
        fi
        if [[ "${value}" == *'$'* || "${value}" == '~'* ]]; then
            echo "Error: ${file}, line ${number}: nothing is expanded there: write the path out." >&2
            return 1
        fi
        found="${value}"
    done < "${file}"
    printf '%s' "${found}"
}

# Set DATA_ROOT, as the header says, sourcing the environment file (if any) on the way.
# Usage: resolve_data_root ENV_FILE ROOT_GIVEN ROOT_OPTION (from --env-file and --data-root).
resolve_data_root() {
    local env_file="$1" given="$2" option="$3"
    local from_environment="${DATA_ROOT:-}" from_settings=""
    if [[ "${given}" == true ]]; then
        if [[ -z "${option}" ]]; then
            echo "Error: --data-root is empty (it would fall back to the local disk)." >&2
            return 1
        fi
    elif [[ -z "${from_environment}" ]]; then
        from_settings="$(settings_data_root)" || return 1
    fi
    if [[ -n "${env_file}" ]]; then
        if [[ ! -f "${env_file}" ]]; then
            echo "Error: environment file '${env_file}' not found." >&2
            return 1
        fi
        # shellcheck source=/dev/null
        source "${env_file}"
    fi
    # Whatever the environment file assigns, the order above holds.
    if [[ "${given}" == true ]]; then
        DATA_ROOT="${option}"
    elif [[ -n "${from_environment}" ]]; then
        DATA_ROOT="${from_environment}"
    elif [[ -n "${from_settings}" ]]; then
        DATA_ROOT="${from_settings}"
    fi
    DATA_ROOT="${DATA_ROOT:-${PROJECT_ROOT}/data}"
    DATA_ROOT="${DATA_ROOT%/}"
}

# Print the default repository of PRODUCT at RES: DATA_ROOT/PRODUCT/res=RES. Until 25 Nov 2026 the
# outputs were DATA_ROOT/data/PRODUCT/res=RES: a local repository left there is not silently
# replaced by a new one. Usage: default_output PRODUCT RES (after resolve_data_root).
default_output() {
    local path="${DATA_ROOT}/$1/res=$2" old="${DATA_ROOT}/data/$1/res=$2"
    if [[ "${path}" != *://* && ! -e "${path}" && -e "${old}" ]]; then
        echo "Error: ${old} is in the layout before 25 Nov 2026 (DATA_ROOT/data/...): move it to ${path}, or give its path." >&2
        return 1
    fi
    printf '%s' "${path}"
}
