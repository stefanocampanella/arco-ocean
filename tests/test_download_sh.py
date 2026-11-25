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


def run_resume(project: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
  """download.sh --extend --resume (the stand-in accepts it at once) with the options given."""
  return subprocess.run(
    [
      "bash", str(project / "scripts" / "download.sh"), "--project-dir", str(project),
      "--virtual-env", str(project / "venv"), "--env-file", "", "--extend", "--resume",
      "--end", "2026-11-25", "--attempts", "1", *args, "forecast_res-1p0",
    ],
    env={**os.environ, "CALLS": str(project / "calls"), "DATA_ROOT": str(project / "root")},
    capture_output=True,
    text=True,
    timeout=120,
  )  # fmt: skip


def test_the_default_output_is_under_the_data_root(project: pathlib.Path):
  result = run_resume(project)
  assert result.returncode == 0, result.stdout + result.stderr
  assert f" {project}/root/data/forecast/res=1p0" in (project / "calls").read_text()


def test_an_output_root_holds_the_bucket_layout(project: pathlib.Path):
  # The bucket's layout, <product>/res=<res> at its root, without data/ in between: the
  # forecast units could not write there (25 Nov).
  result = run_resume(project, "--output-root", "s3://bucket/")
  assert result.returncode == 0, result.stdout + result.stderr
  call = (project / "calls").read_text()
  assert call.rstrip().endswith(" s3://bucket/forecast/res=1p0")


def test_output_and_output_root_are_exclusive(project: pathlib.Path):
  result = run_resume(project, "--output", "s3://bucket/x", "--output-root", "s3://bucket")
  assert result.returncode == 1
  assert "not both" in result.stderr


def test_an_empty_output_root_is_refused(project: pathlib.Path):
  # Empty (a variable that expanded to nothing, say), it would fall back to the local disk.
  result = run_resume(project, "--output-root=")
  assert result.returncode == 1
  assert "--output-root is empty" in result.stderr
  assert not (project / "calls").exists()
