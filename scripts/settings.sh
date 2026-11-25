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
# (scripts/.env: under $SCRATCH on clusters that have one), else the project's data/.
#
# The settings file, $ARCO_OCEAN_SETTINGS or ~/.config/arco-ocean/settings (an empty
# ARCO_OCEAN_SETTINGS disables it), holds KEY=VALUE lines, `export` and comments allowed; it is
# read, not sourced. Its one key is DATA_ROOT. It is read by the systemd units too, which do not
# have the shell's environment. arco-make's own settings (credentials, the AWS profile, TMPDIR,
# DASK_*) are in ~/.arcomakerc, which the scripts do not read: it holds secrets.

# Fill DATA_ROOT from the settings file, unless the environment gives it.
read_settings() {
    local file="${ARCO_OCEAN_SETTINGS-${XDG_CONFIG_HOME:-${HOME}/.config}/arco-ocean/settings}"
    if [[ -z "${file}" || ! -f "${file}" ]]; then
        return 0
    fi
    local line key value
    while IFS= read -r line || [[ -n "${line}" ]]; do
        if [[ ! "${line}" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
            continue
        fi
        key="${BASH_REMATCH[2]}"
        value="${BASH_REMATCH[3]}"
        value="${value%%[[:space:]]#*}"
        value="${value%"${value##*[![:space:]]}"}"
        value="${value#\"}"; value="${value%\"}"; value="${value#\'}"; value="${value%\'}"
        case "${key}" in
            DATA_ROOT) DATA_ROOT="${DATA_ROOT:-${value}}" ;;
            *) echo "Warning: ${file}: '${key}' is not a setting of the scripts; ignored." >&2 ;;
        esac
    done < "${file}"
}

# The root of the outputs, without a trailing slash: the one given (DATA_ROOT), else
# PROJECT_ROOT/data. Usage: data_root "${DATA_ROOT:-}".
data_root() {
    local root="${1:-${PROJECT_ROOT}/data}"
    echo "${root%/}"
}
