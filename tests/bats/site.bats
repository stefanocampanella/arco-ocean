#!/usr/bin/env bats
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
#
# scripts/site.sh, with a stand-in for uvx that records its calls (the notebooks exported, then
# mystmd).

setup() {
    load common
    common_setup
    stub uvx
    # A checkout of its own: site.sh writes into docs/notebooks.
    mkdir -p "${PROJECT}/notebooks" "${PROJECT}/docs"
    cp -r "${REPO}/scripts" "${PROJECT}/scripts"
    touch "${PROJECT}/notebooks/one.py" "${PROJECT}/notebooks/two.py"
}

site() {
    run bash "${PROJECT}/scripts/site.sh" "$@"
}

@test "build exports every notebook, then builds the site" {
    site build --strict
    assert_success
    run calls
    assert_line --index 0 --regexp "^uvx --from marimo==[0-9.]+ --with nbformat marimo export ipynb --sort top-down ${PROJECT}/notebooks/one.py -o ${PROJECT}/docs/notebooks/one.ipynb$"
    assert_line --index 1 --partial "${PROJECT}/notebooks/two.py -o ${PROJECT}/docs/notebooks/two.ipynb"
    assert_line --index 2 --regexp "^uvx --from mystmd==[0-9.]+ --with nodejs-wheel==[0-9.]+ myst build --html --strict --ci$"
}

@test "start previews, without --strict" {
    site start
    assert_success
    run calls
    assert_line --index 2 --regexp "myst start$"
    site start --strict
    assert_failure 1
    assert_output --partial "--strict goes with build"
}

@test "an unknown argument is refused" {
    site deploy
    assert_failure 1
    assert_output --partial "unrecognized argument 'deploy'"
    assert_file_not_exists "${CALLS}"
}
