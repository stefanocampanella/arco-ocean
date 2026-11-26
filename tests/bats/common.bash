# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
#
# What every test file shares, loaded by its setup (`load common`, then `common_setup`). The
# libraries are git submodules in helpers/ (bats-core's own layout): bats-support (output),
# bats-assert (assert_success, assert_output, assert_line, ...) and bats-file (assert_file_exists,
# ...). Run the tests with
#
#     tests/bats/helpers/bats-core/bin/bats tests/bats
#
# after `git submodule update --init` (and `uv sync` for the tests of the heartbeat, which run
# the package's `arco-ocean`).

# The checkout under test.
REPO="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

common_setup() {
    load "${BATS_TEST_DIRNAME}/helpers/bats-support/load"
    load "${BATS_TEST_DIRNAME}/helpers/bats-assert/load"
    load "${BATS_TEST_DIRNAME}/helpers/bats-file/load"
    # Each test has its own project directory, and its stand-ins first on PATH.
    PROJECT="${BATS_TEST_TMPDIR}/project"
    STUBS="${BATS_TEST_TMPDIR}/stubs"
    mkdir -p "${PROJECT}" "${STUBS}"
    PATH="${STUBS}:${PATH}"
    export CALLS="${BATS_TEST_TMPDIR}/calls"
    # Neither the maintainer's settings file nor arco-make's (it holds credentials), nor a
    # DATA_ROOT of the environment, reaches the scripts.
    export ARCO_OCEAN_SETTINGS="" ARCOMAKE_RC=""
    unset DATA_ROOT
}

# A stand-in for a command, first on PATH: it records its name and arguments, one call per line,
# in $CALLS, then runs BODY (shell code; "$@" are its arguments). Usage: stub NAME [BODY].
stub() {
    stub_at "${STUBS}/$1" "${2:-}"
}

# The same at a given path (an arco-make in a virtual environment, say).
# shellcheck disable=SC2094 # basename reads the path, not the file
stub_at() {
    mkdir -p "$(dirname "$1")"
    {
        echo '#!/usr/bin/env bash'
        echo "echo \"$(basename "$1") \$*\" >> \"\${CALLS}\""
        printf '%s\n' "${2:-}"
    } > "$1"
    chmod +x "$1"
}

# The calls the stand-ins recorded, one per line (none: nothing).
calls() {
    cat "${CALLS}" 2>/dev/null || true
}

# A copy of the scripts in the project, for a test that replaces one of them with a stand-in
# (forecast.sh runs the download.sh next to it).
copy_scripts() {
    mkdir -p "${PROJECT}/scripts"
    cp -r "${REPO}/scripts/lib" "${PROJECT}/scripts/lib"
    local name
    for name in "$@"; do
        cp "${REPO}/scripts/${name}" "${PROJECT}/scripts/${name}"
    done
}

# Skip a test that runs the package (`arco-ocean`, src/arco_ocean) without its environment.
needs_package() {
    [[ -x "${REPO}/.venv/bin/arco-ocean" ]] || skip "needs the project's environment: uv sync"
    export ARCO_OCEAN_CLI="${REPO}/.venv/bin/arco-ocean"
}
