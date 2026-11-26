#!/usr/bin/env bats
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
#
# scripts/climatology.sh's default paths, with a stand-in for arco-make (in a --virtual-env).

setup() {
    load common
    common_setup
    mkdir -p "${PROJECT}/configs/climatology"
    touch "${PROJECT}/configs/climatology/historical_res-1p0.toml"
    stub_at "${PROJECT}/venv/bin/arco-make"
}

climatology() {
    DATA_ROOT="${PROJECT}/root" run bash "${REPO}/scripts/climatology.sh" \
        --project-dir "${PROJECT}" --virtual-env "${PROJECT}/venv" --env-file "" "$@" \
        historical_res-1p0
}

# The input and output climatology.sh gave arco-make.
paths() {
    calls | awk '{print $(NF - 1), $NF}'
}

@test "a data root empty, or given with paths, is refused" {
    # Either would put the statistics somewhere else than meant, silently.
    local args
    for args in "--data-root=" "--data-root s3://bucket --output s3://bucket/x" \
        "--data-root s3://bucket --input s3://bucket/x"; do
        # shellcheck disable=SC2086 # the options, split
        climatology ${args}
        assert_failure 1
        assert_output --partial "--data-root"
    done
    assert_file_not_exists "${CALLS}"
}

@test "the default paths are under the data root" {
    climatology
    assert_success
    run paths
    assert_output "${PROJECT}/root/historical/res=1p0 ${PROJECT}/root/statistics/res=1p0"
}

@test "a data root holds the bucket's layout" {
    climatology --data-root s3://bucket/
    assert_success
    run paths
    assert_output "s3://bucket/historical/res=1p0 s3://bucket/statistics/res=1p0"
}

@test "streaming by default, the graph when asked" {
    climatology
    climatology --graph --replace
    run calls
    assert_line --index 0 --partial "compute-climatology --dask-setup=threads --log-level=info --streaming --"
    assert_line --index 1 --partial "--replace --graph --"
}
