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
  assert "live examples" not in result.stdout


def test_the_measurements_check_their_arguments(tmp_path: pathlib.Path) -> None:
  # Before any measurement (hours, with credentials): --out is needed, the tables' files given.
  result = run("--", "--measure", "0.25")
  assert result.returncode != 0 and "--measure RES needs --out" in result.stderr
  one, two = tmp_path / "a.json", tmp_path / "b.json"
  one.write_text('{"resolution": 0.25}')
  two.write_text('{"resolution": 1.0}')
  result = run("--", "--tables", f"{one} {two}")
  assert result.returncode == 0, result.stderr
  assert "| | 0.25 deg | 1.0 deg |" in result.stdout


@pytest.mark.live
def test_the_examples_on_the_real_sources() -> None:
  from arcomake import settings

  settings.load()
  result = run("--", "--live")
  assert result.returncode == 0, result.stdout + result.stderr
  # They stop quietly without --live: they ran.
  assert "live examples: checked" in result.stdout
