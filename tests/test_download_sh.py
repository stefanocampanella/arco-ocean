# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""scripts/download.sh's attempts, with a stand-in for arco-make (in a --virtual-env)."""

import os
import pathlib
import shutil
import subprocess
import sys
import time

import pytest

SCRIPTS = pathlib.Path(__file__).parents[1] / "scripts"

# Records its arguments; refuses, as arco-make does, a run while a failed one waits, unless
# resumed.
FAKE_ARCO_MAKE = """#!/usr/bin/env bash
echo "$*" >> "${CALLS}"
if [[ " $* " == *" --resume "* ]]; then exit 0; fi
echo "Error: A download run failed at out (run/download-extend-x, 3 blocks written):" \\
    "--extend --resume continues it; --replace (without --extend) rewrites the output"
exit 1
"""

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="needs Linux (date -d)")


@pytest.fixture
def project(tmp_path: pathlib.Path) -> pathlib.Path:
  (tmp_path / "scripts").mkdir()
  shutil.copy(SCRIPTS / "download.sh", tmp_path / "scripts" / "download.sh")
  (tmp_path / "configs" / "download").mkdir(parents=True)
  (tmp_path / "configs" / "download" / "forecast_res-1p0.toml").write_text("")
  arco_make = tmp_path / "venv" / "bin" / "arco-make"
  arco_make.parent.mkdir(parents=True)
  arco_make.write_text(FAKE_ARCO_MAKE)
  arco_make.chmod(0o755)
  return tmp_path


def test_a_run_refused_for_a_failed_one_resumes_it_at_once(project: pathlib.Path):
  calls = project / "calls"
  begun = time.monotonic()
  result = subprocess.run(
    [
      "bash", str(project / "scripts" / "download.sh"), "--project-dir", str(project),
      "--virtual-env", str(project / "venv"), "--env-file", "", "--extend",
      "--end", "2026-11-25", "--attempts", "3", "--retry-delay", "600", "forecast_res-1p0",
    ],
    env={**os.environ, "CALLS": str(calls), "DATA_ROOT": str(project)},
    capture_output=True,
    text=True,
    timeout=120,
  )  # fmt: skip
  assert result.returncode == 0, result.stdout + result.stderr
  # Not after the 600 s between attempts.
  assert time.monotonic() - begun < 60
  first, second = calls.read_text().splitlines()
  assert "--extend" in first and "--resume" not in first
  assert "--extend" in second and "--resume" in second
  assert "an earlier run failed and waits: resuming it" in result.stdout


# Records Dask's chunk size as arco-make gets it.
CHUNK_SIZE_ARCO_MAKE = """#!/usr/bin/env bash
echo "${DASK_ARRAY__CHUNK_SIZE:-unset}" >> "${CALLS}"
"""


@pytest.mark.parametrize(
  ("environment", "env_file", "expected"),
  [
    ({}, "", "256MiB"),
    ({"DASK_ARRAY__CHUNK_SIZE": "64MiB"}, "", "64MiB"),
    ({}, "DASK_ARRAY__CHUNK_SIZE=512MiB\n", "512MiB"),
  ],
  ids=["default", "environment", "environment file, not exported"],
)
def test_dask_chunks_of_256_mib_unless_given(
  project: pathlib.Path, environment: dict[str, str], env_file: str, expected: str
):
  (project / "venv" / "bin" / "arco-make").write_text(CHUNK_SIZE_ARCO_MAKE)
  (project / "env").write_text(env_file)
  calls = project / "calls"
  base = {k: v for k, v in os.environ.items() if k != "DASK_ARRAY__CHUNK_SIZE"}
  result = subprocess.run(
    [
      "bash", str(project / "scripts" / "download.sh"), "--project-dir", str(project),
      "--virtual-env", str(project / "venv"), "--env-file", str(project / "env"),
      "--start", "2026-11-01", "--end", "2026-11-02", "forecast_res-1p0",
    ],
    env={**base, **environment, "CALLS": str(calls), "DATA_ROOT": str(project)},
    capture_output=True,
    text=True,
    timeout=120,
  )  # fmt: skip
  assert result.returncode == 0, result.stdout + result.stderr
  assert calls.read_text().splitlines() == [expected]
