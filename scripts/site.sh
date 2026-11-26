#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT

# scripts/site.sh
#
# Build the ARCO-OCEAN site (docs/, mystmd), or preview it. The marimo notebooks (notebooks/*.py)
# are exported first to docs/notebooks/<name>.ipynb (not committed), their text and code in their
# order, without running them (some read the whole dataset); mystmd renders them as pages.
# pages.yml builds the site this way, with --strict.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh" || { echo "Error: ${SCRIPT_DIR}/lib/common.sh is missing." >&2; exit 1; }

# The tools' versions: mystmd with the Node.js of the checks (.pre-commit-config.yaml), marimo
# of the notebooks.
MYSTMD="mystmd==1.14.0"
NODEJS="nodejs-wheel==24.19.0"
MARIMO="marimo==0.25.2"

usage() {
    cat <<EOF
site.sh
    Build the ARCO-OCEAN site from docs/ and the notebooks, or preview it.

SYNOPSIS
    $0 [build [--strict]]
    $0 start
    $0 --help

DESCRIPTION
    build       Write the site to docs/_build/html (BASE_URL from the environment: /arco-ocean
                on GitHub Pages). --strict: a warning fails the build.
    start       Serve it at http://localhost:3000, rebuilt on every change of docs/.

    Needs uv (uvx): mystmd, Node.js and marimo run from their packages ($MYSTMD, $NODEJS,
    $MARIMO).
EOF
}

COMMAND=build
STRICT=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        build|start) COMMAND="$1"; shift ;;
        --strict) STRICT=(--strict --ci); shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Error: unrecognized argument '$1'." >&2; usage >&2; exit 1 ;;
    esac
done

set -euo pipefail

[[ ${#STRICT[@]} -eq 0 || "${COMMAND}" == build ]] || die "--strict goes with build."
command -v uvx >/dev/null 2>&1 || die "uv (uvx) is needed."

# The notebooks, as pages.
mkdir -p "${CHECKOUT}/docs/notebooks"
for NOTEBOOK in "${CHECKOUT}"/notebooks/*.py; do
    NAME="$(basename "${NOTEBOOK}" .py)"
    uvx --from "${MARIMO}" --with nbformat marimo export ipynb --sort top-down \
        "${NOTEBOOK}" -o "${CHECKOUT}/docs/notebooks/${NAME}.ipynb"
done

cd "${CHECKOUT}/docs"
if [[ "${COMMAND}" == build ]]; then
    uvx --from "${MYSTMD}" --with "${NODEJS}" myst build --html "${STRICT[@]+"${STRICT[@]}"}" < /dev/null
else
    uvx --from "${MYSTMD}" --with "${NODEJS}" myst start < /dev/null
fi
