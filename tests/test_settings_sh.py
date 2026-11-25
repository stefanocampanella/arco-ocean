# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""scripts/settings.sh: where the scripts' outputs go (DATA_ROOT), from the environment, the
scripts' settings file, or the project's data/."""

import os
import pathlib
import subprocess

SETTINGS = pathlib.Path(__file__).parents[1] / "scripts" / "settings.sh"


def root(tmp_path: pathlib.Path, settings: str | None = None, **env: str) -> tuple[str, str]:
  """The root data_root gives after read_settings, and the warnings, for a settings file holding
  `settings` (none if None) and the environment's DATA_ROOT given in `env`."""
  path = tmp_path / "settings"
  if settings is not None:
    path.write_text(settings)
  environ = {k: v for k, v in os.environ.items() if k != "DATA_ROOT"}
  result = subprocess.run(
    ["bash", "-c", f'source "{SETTINGS}"; read_settings; data_root "${{DATA_ROOT:-}}"'],
    env={**environ, "ARCO_OCEAN_SETTINGS": str(path), "PROJECT_ROOT": "/project", **env},
    capture_output=True,
    text=True,
    timeout=30,
    check=True,
  )
  return result.stdout.strip(), result.stderr


def test_without_settings_the_project_data(tmp_path) -> None:
  assert root(tmp_path) == ("/project/data", "")


def test_the_settings_file_gives_the_root(tmp_path) -> None:
  # As the maintainer writes it: export, quotes, a comment, a trailing slash.
  text = '# Where outputs go\nexport DATA_ROOT="s3://ogs-arco-ocean/"  # the bucket\n'
  assert root(tmp_path, text) == ("s3://ogs-arco-ocean", "")


def test_the_environment_wins_over_the_settings_file(tmp_path) -> None:
  assert root(tmp_path, "DATA_ROOT=s3://bucket\n", DATA_ROOT="/elsewhere")[0] == "/elsewhere"


def test_other_keys_are_ignored_with_a_warning(tmp_path) -> None:
  # arco-make's settings belong in ~/.arcomakerc: the scripts do not export them.
  value, warnings = root(tmp_path, "TMPDIR=/x\nDATA_ROOT=/data/arco-ocean\n")
  assert value == "/data/arco-ocean"
  assert "'TMPDIR' is not a setting of the scripts" in warnings


def test_the_default_file_and_an_empty_variable_disabling_it(tmp_path) -> None:
  default = tmp_path / ".config" / "arco-ocean" / "settings"
  default.parent.mkdir(parents=True)
  default.write_text("DATA_ROOT=s3://bucket\n")
  # ARCO_OCEAN_SETTINGS unset (tests/conftest.py empties it): the default file is read.
  unset = ("DATA_ROOT", "XDG_CONFIG_HOME", "ARCO_OCEAN_SETTINGS")
  environ = {k: v for k, v in os.environ.items() if k not in unset}
  environ |= {"PROJECT_ROOT": "/project", "HOME": str(tmp_path)}
  command = ["bash", "-c", f'source "{SETTINGS}"; read_settings; data_root "${{DATA_ROOT:-}}"']

  def run(**env: str) -> str:
    result = subprocess.run(
      command, env={**environ, **env}, capture_output=True, text=True, timeout=30, check=True
    )
    return result.stdout.strip()

  assert run() == "s3://bucket"
  assert run(ARCO_OCEAN_SETTINGS="") == "/project/data"
