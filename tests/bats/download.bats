#!/usr/bin/env bats
# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
#
# scripts/download.sh: its attempts and its outputs, with a stand-in for arco-make (in a
# --virtual-env).

setup() {
    load common
    common_setup
    mkdir -p "${PROJECT}/configs/download"
    touch "${PROJECT}/configs/download/forecast_res-1p0.toml"
    # Refuses, as arco-make does, a run while a failed one waits, unless resumed.
    stub_at "${PROJECT}/venv/bin/arco-make" '
if [[ " $* " == *" --resume "* ]]; then exit 0; fi
echo "Error: A download run failed at out (run/download-extend-x, 3 blocks written):" \
    "--extend --resume continues it; --replace (without --extend) rewrites the output"
exit 1'
}

# download.sh in the project, with the stand-in, no environment file, and the options given.
download() {
    run bash "${REPO}/scripts/download.sh" --project-dir "${PROJECT}" \
        --virtual-env "${PROJECT}/venv" --env-file "" "$@"
}

# download.sh --extend --resume (the stand-in accepts it at once), its outputs under DATA_ROOT.
resume() {
    DATA_ROOT="${PROJECT}/root" download --extend --resume --end 2026-11-25 --attempts 1 "$@" \
        forecast_res-1p0
}

@test "a run refused for a failed one resumes it at once" {
    SECONDS=0
    DATA_ROOT="${PROJECT}" download --extend --end 2026-11-25 --attempts 3 --retry-delay 600 \
        forecast_res-1p0
    assert_success
    # Not after the 600 s between attempts.
    [[ ${SECONDS} -lt 60 ]]
    assert_output --partial "an earlier run failed and waits: resuming it"
    run calls
    assert_line --index 0 --regexp "--extend -- "
    refute_line --index 0 --partial "--resume"
    assert_line --index 1 --partial "--extend --resume"
}

@test "the default output is under the data root" {
    resume
    assert_success
    run calls
    assert_output --partial " ${PROJECT}/root/forecast/res=1p0"
}

@test "a data root holds the bucket's layout" {
    # <product>/res=<res> at its root, without data/ in between: the forecast units could not
    # write there (25 Nov 2026).
    resume --data-root s3://bucket/
    assert_success
    run calls
    assert_output --regexp " s3://bucket/forecast/res=1p0$"
}

@test "--output and --data-root are exclusive" {
    resume --output s3://bucket/x --data-root s3://bucket
    assert_failure 1
    assert_output --partial "not both"
}

@test "an empty --data-root is refused" {
    # Empty (a variable that expanded to nothing, say), it would fall back to the local disk.
    resume --data-root=
    assert_failure 1
    assert_output --partial "--data-root is empty"
    assert_file_not_exists "${CALLS}"
}

@test "an option without its value is refused" {
    download --extend --end 2026-11-25 forecast_res-1p0 --image
    assert_failure 1
    assert_output --partial "--image needs a value"
    assert_file_not_exists "${CALLS}"
}

@test "the dates the recipes do not have are asked for" {
    download forecast_res-1p0
    assert_failure 1
    assert_output --partial "give --end"
    download --end 2026-11-25 forecast_res-1p0
    assert_output --partial "give --start"
    download --extend --start 2026-11-01 --end 2026-11-25 forecast_res-1p0
    assert_output --partial "not with --start nor --replace"
    assert_file_not_exists "${CALLS}"
}

@test "a forecast run not published yet ends with 75, the runs before stored" {
    stub_at "${PROJECT}/venv/bin/arco-make" 'exit 75'
    DATA_ROOT="${PROJECT}/root" download --extend --end 2026-11-25 --attempts 2 --retry-delay 0 \
        forecast_res-1p0
    assert_failure 75
    # The second run extends the output again, it does not resume.
    run calls
    assert_line --index 1 --partial "--extend --"
    refute_line --index 1 --partial "--resume"
}

@test "an option of its own given last without its value is refused, not looped on" {
    # `shift 2` on the last argument does not shift: the loop never ended (review of #33).
    run timeout 20 bash "${REPO}/scripts/download.sh" forecast_res-1p0 --end
    assert_failure 1
    assert_output "Error: --end needs a value."
}

@test "a relative --project-dir, from its parent" {
    # The paths made from it were resolved again from inside it (review of #33).
    cd "$(dirname "${PROJECT}")"
    run bash "${REPO}/scripts/download.sh" --project-dir "$(basename "${PROJECT}")" \
        --virtual-env "${PROJECT}/venv" --env-file "" --extend --resume --end 2026-11-25 \
        --attempts 1 forecast_res-1p0
    assert_success
    run calls
    assert_output --partial " ${PROJECT}/configs/download/forecast_res-1p0.toml ${PROJECT}/data/forecast/res=1p0"
}
