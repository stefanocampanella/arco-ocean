# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""The coarsening notes (notebooks/coarsening.py) run: their examples check their results with
asserts, on synthetic data; with `--live`, also those on the real sources (Copernicus Marine
credentials: environment, `~/.arcomakerc` or the toolbox's file)."""

import os
import pathlib
import subprocess
import sys

import pytest

NOTEBOOK = pathlib.Path(__file__).parents[2] / "notebooks" / "coarsening.py"


def run(*args: str) -> subprocess.CompletedProcess:
  return subprocess.run(
    [sys.executable, str(NOTEBOOK), *args],
    capture_output=True,
    text=True,
    timeout=900,
    env=os.environ,
  )


def test_the_examples_of_the_coarsening_notes() -> None:
  result = run()
  assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.live
def test_the_examples_on_the_real_sources() -> None:
  from arcomake import settings

  settings.load()
  result = run("--", "--live")
  assert result.returncode == 0, result.stdout + result.stderr
