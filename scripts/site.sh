#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT

# scripts/site.sh
#
# Build the ARCO-OCEAN site (docs/, mystmd), or preview it. The marimo notebooks (notebooks/*.py)
# are exported first to docs/notebooks/<name>.ipynb (not committed), their text and code in their
# order, without running them (some read the whole dataset); mystmd renders them as pages, all
# of them (docs/myst.yml lists the folder). pages.yml builds the site this way, with --strict.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh" || { echo "Error: ${SCRIPT_DIR}/lib/common.sh is missing." >&2; exit 1; }

# The tools' versions: mystmd with the Node.js of the checks, marimo of the notebooks
# (.pre-commit-config.yaml has the same: tests/bats/site.bats checks it).
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
    start       Serve it at http://localhost:3000, rebuilt on every change of docs/ and of the
                notebooks.

    Needs uv (uvx): mystmd, Node.js and marimo run from their packages ($MYSTMD, $NODEJS,
    $MARIMO), and python3.
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
shopt -s nullglob

[[ ${#STRICT[@]} -eq 0 || "${COMMAND}" == build ]] || die "--strict goes with build."
command -v uvx >/dev/null 2>&1 || die "uv (uvx) is needed."

# marimo names cells alike in every notebook (Hbol, MJUe, ...): the ids take the notebook's
# name, which mystmd needs unique across the site.
unique_ids() {
    python3 -I - "$1" "$2" <<'EOF'
import json, sys
path, name = sys.argv[1:]
notebook = json.load(open(path))
for cell in notebook["cells"]:
    if "id" in cell:
        cell["id"] = f"{name}-{cell['id']}"
json.dump(notebook, open(path, "w"), indent=1)
EOF
}

# The notebooks, as pages: exported afresh (an export left from a notebook renamed or removed
# would still satisfy the site here, and not in CI); --force, as marimo asks before overwriting.
EXPORTS="${CHECKOUT}/docs/notebooks"
rm -rf "${EXPORTS}"
mkdir -p "${EXPORTS}"
NOTEBOOKS=("${CHECKOUT}"/notebooks/*.py)
for NOTEBOOK in "${NOTEBOOKS[@]+"${NOTEBOOKS[@]}"}"; do
    NAME="$(basename "${NOTEBOOK}" .py)"
    uvx --from "${MARIMO}" --with nbformat marimo export ipynb --force --sort top-down \
        "${NOTEBOOK}" -o "${EXPORTS}/${NAME}.ipynb"
    unique_ids "${EXPORTS}/${NAME}.ipynb" "${NAME}"
done

cd "${CHECKOUT}/docs"
if [[ "${COMMAND}" == start ]]; then
    # Edits to the notebooks reach the preview: each export is redone on change (its ids then
    # marimo's own: the preview may warn of duplicates, the build does not).
    WATCHERS=()
    trap 'kill "${WATCHERS[@]+"${WATCHERS[@]}"}" 2>/dev/null || true' EXIT
    for NOTEBOOK in "${NOTEBOOKS[@]+"${NOTEBOOKS[@]}"}"; do
        NAME="$(basename "${NOTEBOOK}" .py)"
        uvx --from "${MARIMO}" --with nbformat marimo export ipynb --force --sort top-down \
            --watch "${NOTEBOOK}" -o "${EXPORTS}/${NAME}.ipynb" > /dev/null 2>&1 &
        WATCHERS+=($!)
    done
    uvx --from "${MYSTMD}" --with "${NODEJS}" myst start < /dev/null
    exit
fi
LOG="$(mktemp)"
trap 'rm -f "${LOG}"' EXIT
uvx --from "${MYSTMD}" --with "${NODEJS}" myst build --html "${STRICT[@]+"${STRICT[@]}"}" < /dev/null \
    2>&1 | tee "${LOG}"
# mystmd's --strict summarizes the warnings, and exits 0 all the same (1.14.0): this script fails.
if [[ ${#STRICT[@]} -gt 0 ]] && grep -q -e '⚠️' -e '⛔' "${LOG}"; then
    die "the site's build warned (see above): --strict fails it."
fi
