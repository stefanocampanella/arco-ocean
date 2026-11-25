# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
#
# Where the scripts' outputs go, sourced by download.sh, climatology.sh and forecast.sh, so that
# the three agree.
#
# The root of the outputs is DATA_ROOT: the repositories are DATA_ROOT/<product>/res=<res>
# (s3://ogs-arco-ocean for the bucket's layout). It comes, the first given winning, from the
# scripts' --data-root, the environment, the scripts' settings file, the environment file
# (scripts/.env: under $SCRATCH on clusters that have one), else the project's data/
# (resolve_data_root).
#
# The settings file, $ARCO_OCEAN_SETTINGS or ~/.config/arco-ocean/settings (an empty
# ARCO_OCEAN_SETTINGS disables it), holds KEY=VALUE lines, `export`, quotes and comments allowed;
# it is read, not sourced: nothing in it is expanded, and a line it cannot read is an error (a
# mistake there would send terabytes to the local disk). Its one key is DATA_ROOT. The systemd
# units read it too, which do not have the shell's environment. arco-make's own settings
# (credentials, the AWS profile, TMPDIR, DASK_*) are in ~/.arcomakerc, which the scripts do not
# read: it holds secrets.

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
