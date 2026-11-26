#!/usr/bin/env bats
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
#
# scripts/lib/common.sh: where the outputs go (DATA_ROOT, from --data-root, the environment, the
# scripts' settings file, the environment file, or the project's data/), and the shared options.

setup() {
    load common
    common_setup
    SETTINGS="${BATS_TEST_TMPDIR}/settings"
    export ARCO_OCEAN_SETTINGS="${SETTINGS}"
}

# resolve_data_root, then default_output historical 0p25, with ENV_FILE (or none) and
# --data-root OPTION (or none). The settings file is $SETTINGS, written by the test.
# Usage: resolve [ENV_FILE] [OPTION].
resolve() {
    local env_file="${1:-}" given=false option=""
    if [[ $# -ge 2 ]]; then given=true; option="$2"; fi
    run bash -c 'source "$1/scripts/lib/common.sh" && PROJECT_ROOT="$2" &&
        resolve_data_root "$3" "$4" "$5" && default_output historical 0p25' \
        _ "${REPO}" "${PROJECT}" "${env_file}" "${given}" "${option}"
}

@test "without settings, the project's data/" {
    resolve
    assert_success
    assert_output "${PROJECT}/data/historical/res=0p25"
}

@test "the settings file gives the root, as the maintainer writes it" {
    # export, quotes, comments, a trailing slash.
    printf '# Where outputs go\nexport DATA_ROOT="s3://ogs-arco-ocean/"  # the bucket\n' > "${SETTINGS}"
    resolve
    assert_success
    assert_output "s3://ogs-arco-ocean/historical/res=0p25"
}

@test "the last value wins, as in shell" {
    printf 'DATA_ROOT=/old\nDATA_ROOT=s3://new\n' > "${SETTINGS}"
    resolve
    assert_output "s3://new/historical/res=0p25"
}

@test "the order: option, environment, settings file, environment file" {
    echo "DATA_ROOT=s3://settings" > "${SETTINGS}"
    # The environment file assigns without ${DATA_ROOT:-...}: the order holds all the same.
    echo "DATA_ROOT=/scratch" > "${BATS_TEST_TMPDIR}/env"
    resolve "${BATS_TEST_TMPDIR}/env"
    assert_output --partial "s3://settings/"
    DATA_ROOT=/environment resolve "${BATS_TEST_TMPDIR}/env"
    assert_output --partial "/environment/"
    DATA_ROOT=/x resolve "${BATS_TEST_TMPDIR}/env" s3://option
    assert_output --partial "s3://option/"
    rm "${SETTINGS}"
    resolve "${BATS_TEST_TMPDIR}/env"
    assert_output --partial "/scratch/"
}

@test "a line that is not a setting fails, naming it" {
    # Each would send the outputs to the local disk, or to a path nobody meant, silently.
    local line message
    while IFS='|' read -r line message; do
        printf '%s\n' "${line}" > "${SETTINGS}"
        resolve
        assert_failure 1
        assert_output --partial "${message}"
        assert_output --partial "line 1"
        refute_output --partial "res=0p25"
    done <<'EOF'
DATA_ROOT = s3://bucket|not KEY=VALUE
DATA_ROOT=|DATA_ROOT is empty
DATA_ROOT=${SCRATCH}/arco-ocean|nothing is expanded
DATA_ROOT=~/arco|nothing is expanded
DATA_ROOT="s3://bucket|unbalanced quotes
EOF
}

@test "other keys are ignored with a warning" {
    # arco-make's settings belong in ~/.arcomakerc: the scripts do not export them.
    printf 'TMPDIR=/x\nDATA_ROOT= /data/arco-ocean \n' > "${SETTINGS}"
    resolve
    assert_success
    assert_line "/data/arco-ocean/historical/res=0p25"
    assert_output --partial "'TMPDIR' is not a setting of the scripts"
}

@test "an empty --data-root fails" {
    resolve "" ""
    assert_failure
    assert_output --partial "--data-root is empty"
}

@test "a repository in the layout before 25 Nov 2026 is not replaced" {
    mkdir -p "${PROJECT}/root/data/historical/res=0p25"
    DATA_ROOT="${PROJECT}/root" resolve
    assert_failure
    assert_output --partial "layout before 25 Nov 2026"
    # Moved, it is found.
    mv "${PROJECT}/root/data/historical" "${PROJECT}/root/historical"
    DATA_ROOT="${PROJECT}/root" resolve
    assert_success
    assert_output "${PROJECT}/root/historical/res=0p25"
}

@test "the default settings file, and an empty variable disabling it" {
    mkdir -p "${BATS_TEST_TMPDIR}/home/.config/arco-ocean"
    echo "DATA_ROOT=s3://bucket" > "${BATS_TEST_TMPDIR}/home/.config/arco-ocean/settings"
    run env -u ARCO_OCEAN_SETTINGS -u XDG_CONFIG_HOME HOME="${BATS_TEST_TMPDIR}/home" bash -c \
        'source "$1" && PROJECT_ROOT=/project && resolve_data_root "" false "" && echo "${DATA_ROOT}"' \
        _ "${REPO}/scripts/lib/common.sh"
    assert_output "s3://bucket"
    run env -u XDG_CONFIG_HOME HOME="${BATS_TEST_TMPDIR}/home" ARCO_OCEAN_SETTINGS="" bash -c \
        'source "$1" && PROJECT_ROOT=/project && resolve_data_root "" false "" && echo "${DATA_ROOT}"' \
        _ "${REPO}/scripts/lib/common.sh"
    assert_output "/project/data"
}

# common_option on the arguments given, then the variables it sets.
options() {
    run bash -c 'source "$1"; shift; common_defaults
        while [[ $# -gt 0 ]]; do common_option "$@"; [[ ${SHIFT_BY} -gt 0 ]] || break; shift "${SHIFT_BY}"; done
        echo "image=${IMAGE} venv=${VENV} binds=${BINDS[*]} root=${ROOT_OPTION}:${ROOT_GIVEN} left=$*"
        echo "runner=${RUNNER_OPTIONS[*]}"' _ "${REPO}/scripts/lib/common.sh" "$@"
}

@test "the shared options, as --option VALUE or --option=VALUE" {
    options --image x.sif --bind /a --bind=/b:/c --data-root=s3://r --log-dir l --own 1
    assert_success
    assert_line "image=x.sif venv= binds=/a /b:/c root=s3://r:true left=--own 1"
    # The runner's are kept as given, for forecast.sh to pass on; --data-root, --log-dir are not.
    assert_line "runner=--image x.sif --bind /a --bind /b:/c"
}

@test "a shared option without its value fails" {
    options --image
    assert_failure
    assert_output "Error: --image needs a value."
}

@test "the default image is the pinned one, shown in the help" {
    run bash "${REPO}/scripts/download.sh" --help
    assert_success
    assert_output --partial "--image IMAGE           Apptainer image (default: oras://ghcr.io/stefanocampanella/arco-make:v"
}

@test "numbers and repositories are checked, naming the option" {
    run bash -c 'source "$1" && positive_integer --attempts 0' _ "${REPO}/scripts/lib/common.sh"
    assert_failure
    assert_output "Error: --attempts takes a positive integer (got '0')."
    run bash -c 'source "$1" && seconds --retry-delay x' _ "${REPO}/scripts/lib/common.sh"
    assert_output "Error: --retry-delay takes a number of seconds (got 'x')."
    run bash -c 'source "$1" && github_repo --repo "a b"' _ "${REPO}/scripts/lib/common.sh"
    assert_output "Error: --repo takes OWNER/REPO (got 'a b')."
    run bash -c 'source "$1" && github_repo --repo o/r && echo fine' _ "${REPO}/scripts/lib/common.sh"
    assert_output "fine"
}

@test "the arco-ocean command: this checkout's, isolated, unless ARCO_OCEAN_CLI names one" {
    run env -u ARCO_OCEAN_CLI bash -c 'source "$1" && arco_ocean_command && echo "${ARCO_OCEAN[*]}"' \
        _ "${REPO}/scripts/lib/common.sh"
    assert_output "env -u PYTHONPATH -u PYTHONHOME uv run --quiet --frozen --no-default-groups --project ${REPO} arco-ocean"
    run env ARCO_OCEAN_CLI=/x/arco-ocean bash -c 'source "$1" && arco_ocean_command && echo "${ARCO_OCEAN[*]}"' \
        _ "${REPO}/scripts/lib/common.sh"
    assert_output "/x/arco-ocean"
}
