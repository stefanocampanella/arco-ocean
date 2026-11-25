# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""scripts/climatology.sh's default paths, with a stand-in for arco-make (in a --virtual-env)."""

import os
import pathlib
import shutil
import subprocess

import pytest

SCRIPTS = pathlib.Path(__file__).parents[1] / "scripts"

# Records its arguments.
FAKE_ARCO_MAKE = """#!/usr/bin/env bash
echo "$*" >> "${CALLS}"
"""


@pytest.fixture
def project(tmp_path: pathlib.Path) -> pathlib.Path:
  (tmp_path / "scripts").mkdir()
  shutil.copy(SCRIPTS / "climatology.sh", tmp_path / "scripts" / "climatology.sh")
  (tmp_path / "configs" / "climatology").mkdir(parents=True)
  (tmp_path / "configs" / "climatology" / "historical_res-1p0.toml").write_text("")
  arco_make = tmp_path / "venv" / "bin" / "arco-make"
  arco_make.parent.mkdir(parents=True)
  arco_make.write_text(FAKE_ARCO_MAKE)
  arco_make.chmod(0o755)
  return tmp_path


def paths(project: pathlib.Path, *args: str) -> list[str]:
  """The input and output climatology.sh gives arco-make."""
  result = subprocess.run(
    [
      "bash", str(project / "scripts" / "climatology.sh"), "--project-dir", str(project),
      "--virtual-env", str(project / "venv"), "--env-file", "", *args, "historical_res-1p0",
    ],
    env={**os.environ, "CALLS": str(project / "calls"), "DATA_ROOT": str(project / "root")},
    capture_output=True,
    text=True,
    timeout=60,
  )  # fmt: skip
  assert result.returncode == 0, result.stdout + result.stderr
  return (project / "calls").read_text().split()[-2:]


def test_the_default_paths_are_under_the_data_root(project: pathlib.Path):
  assert paths(project) == [
    f"{project}/root/data/historical/res=1p0",
    f"{project}/root/data/statistics/res=1p0",
  ]


def test_an_output_root_holds_the_bucket_layout(project: pathlib.Path):
  assert paths(project, "--output-root", "s3://bucket/") == [
    "s3://bucket/historical/res=1p0",
    "s3://bucket/statistics/res=1p0",
  ]
