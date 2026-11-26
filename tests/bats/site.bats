#!/usr/bin/env bats
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
#
# scripts/site.sh, with a stand-in for uvx that records its calls: the notebooks exported (it
# writes a notebook with marimo's cell ids), then mystmd (which warns with FAKE_WARN).

setup() {
    load common
    common_setup
    stub uvx '
if [[ "$*" == *"marimo export ipynb"* ]]; then
    while [[ $# -gt 0 ]]; do
        if [[ "$1" == -o ]]; then echo "{\"cells\": [{\"id\": \"Hbol\"}, {\"id\": \"MJUe\"}]}" > "$2"; fi
        shift
    done
fi
if [[ "$*" == *"myst build"* && -n "${FAKE_WARN:-}" ]]; then echo "⚠️  index.md Something to fix"; fi'
    # A checkout of its own: site.sh writes into docs/notebooks.
    copy_scripts site.sh
    mkdir -p "${PROJECT}/notebooks" "${PROJECT}/docs"
    touch "${PROJECT}/notebooks/one.py" "${PROJECT}/notebooks/two.py"
}

site() {
    run bash "${PROJECT}/scripts/site.sh" "$@"
}

@test "build exports every notebook, then builds the site" {
    site build --strict
    assert_success
    run calls
    assert_line --index 0 --regexp "^uvx --from marimo==[0-9.]+ --with nbformat marimo export ipynb --force --sort top-down ${PROJECT}/notebooks/one.py -o ${PROJECT}/docs/notebooks/one.ipynb$"
    assert_line --index 1 --partial "${PROJECT}/notebooks/two.py -o ${PROJECT}/docs/notebooks/two.ipynb"
    assert_line --index 2 --regexp "^uvx --from mystmd==[0-9.]+ --with nodejs-wheel==[0-9.]+ myst build --html --strict --ci$"
}

@test "the notebooks' cell ids are unique across the site" {
    # marimo names cells alike in every notebook; mystmd warns of duplicates.
    site build
    assert_success
    assert_file_contains "${PROJECT}/docs/notebooks/one.ipynb" '"id": "one-Hbol"'
    assert_file_contains "${PROJECT}/docs/notebooks/two.ipynb" '"id": "two-MJUe"'
}

@test "a strict build that warns fails" {
    # mystmd's own --strict exits 0 after its warnings (1.14.0).
    FAKE_WARN=1 site build --strict
    assert_failure 1
    assert_output --partial "the site's build warned"
    FAKE_WARN=1 site build
    assert_success
}

@test "an export left from a notebook removed goes" {
    mkdir -p "${PROJECT}/docs/notebooks"
    touch "${PROJECT}/docs/notebooks/gone.ipynb"
    site build
    assert_success
    assert_file_not_exists "${PROJECT}/docs/notebooks/gone.ipynb"
    assert_file_exists "${PROJECT}/docs/notebooks/one.ipynb"
}

@test "without notebooks, the site builds" {
    rm "${PROJECT}"/notebooks/*.py
    site build
    assert_success
    run calls
    assert_line --index 0 --partial "myst build"
}

@test "the tools' versions are those of the checks" {
    # marimo checks the notebooks it exports; Node.js tests the page that mystmd builds.
    local name version
    for name in MARIMO NODEJS; do
        version="$(sed -n "s/^${name}=\"[a-z-]*==\(.*\)\"$/\1/p" "${REPO}/scripts/site.sh")"
        [[ -n "${version}" ]]
        run grep -c -e "marimo@${version} " -e "nodejs-wheel==${version} " "${REPO}/.pre-commit-config.yaml"
        assert_output 1
    done
}

@test "start previews, without --strict" {
    site start
    assert_success
    run calls
    # The exports, again on every change of the notebooks while the preview runs.
    assert_line --regexp "marimo export ipynb --force --sort top-down --watch ${PROJECT}/notebooks/one.py"
    assert_line --regexp "myst start$"
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
