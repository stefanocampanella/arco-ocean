# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""scripts/settings.sh: where the scripts' outputs go (DATA_ROOT), from --data-root, the
environment, the scripts' settings file, the environment file, or the project's data/."""

import os
import pathlib
import subprocess

import pytest

SETTINGS = pathlib.Path(__file__).parents[1] / "scripts" / "settings.sh"


def resolve(
  tmp_path: pathlib.Path,
  settings: str | None = None,
  env_file: str | None = None,
  option: str | None = None,
  **env: str,
) -> subprocess.CompletedProcess:
  """resolve_data_root, then default_output historical 0p25, with a settings file holding
  `settings` (none if None), an environment file holding `env_file`, --data-root `option`, and the
  environment's DATA_ROOT given in `env`."""
  path = tmp_path / "settings"
  if settings is None:
    path.unlink(missing_ok=True)
  else:
    path.write_text(settings)
  env_path = ""
  if env_file is not None:
    (tmp_path / "env").write_text(env_file)
    env_path = str(tmp_path / "env")
  given = "true" if option is not None else "false"
  script = (
    f'source "{SETTINGS}" && resolve_data_root "{env_path}" {given} "{option or ""}" '
    "&& default_output historical 0p25"
  )
  environ = {k: v for k, v in os.environ.items() if k != "DATA_ROOT"}
  return subprocess.run(
    ["bash", "-c", script],
    env={**environ, "ARCO_OCEAN_SETTINGS": str(path), "PROJECT_ROOT": str(tmp_path), **env},
    capture_output=True,
    text=True,
    timeout=30,
  )


def output(tmp_path: pathlib.Path, *args, **kwargs) -> str:
  result = resolve(tmp_path, *args, **kwargs)
  assert result.returncode == 0, result.stderr
  return result.stdout


def test_without_settings_the_project_data(tmp_path) -> None:
  assert output(tmp_path) == f"{tmp_path}/data/historical/res=0p25"


def test_the_settings_file_gives_the_root(tmp_path) -> None:
  # As the maintainer writes it: export, quotes, comments, a trailing slash.
  text = '# Where outputs go\nexport DATA_ROOT="s3://ogs-arco-ocean/"  # the bucket\n'
  assert output(tmp_path, text) == "s3://ogs-arco-ocean/historical/res=0p25"


def test_the_last_value_wins_as_in_shell(tmp_path) -> None:
  text = "DATA_ROOT=/old\nDATA_ROOT=s3://new\n"
  assert output(tmp_path, text) == "s3://new/historical/res=0p25"


def test_the_order(tmp_path) -> None:
  text = "DATA_ROOT=s3://settings\n"
  # The environment file assigns without ${DATA_ROOT:-...}: the order holds all the same.
  env_file = "DATA_ROOT=/scratch\n"
  assert output(tmp_path, text, env_file).startswith("s3://settings/")
  assert output(tmp_path, text, env_file, DATA_ROOT="/environment").startswith("/environment/")
  assert output(tmp_path, text, env_file, "s3://option", DATA_ROOT="/x").startswith("s3://option/")
  assert output(tmp_path, None, env_file).startswith("/scratch/")


@pytest.mark.parametrize(
  ("text", "message"),
  [
    ("DATA_ROOT = s3://bucket\n", "not KEY=VALUE"),
    ("DATA_ROOT=\n", "DATA_ROOT is empty"),
    ("DATA_ROOT=${SCRATCH}/arco-ocean\n", "nothing is expanded"),
    ("DATA_ROOT=~/arco\n", "nothing is expanded"),
    ('DATA_ROOT="s3://bucket\n', "unbalanced quotes"),
  ],
)
def test_a_line_that_is_not_a_setting_fails(tmp_path, text, message) -> None:
  # Each would send the outputs to the local disk, or to a path nobody meant, silently.
  result = resolve(tmp_path, text)
  assert result.returncode == 1
  assert message in result.stderr and "line 1" in result.stderr
  assert result.stdout == ""


def test_other_keys_are_ignored_with_a_warning(tmp_path) -> None:
  # arco-make's settings belong in ~/.arcomakerc: the scripts do not export them.
  result = resolve(tmp_path, "TMPDIR=/x\nDATA_ROOT= /data/arco-ocean \n")
  assert result.returncode == 0, result.stderr
  assert result.stdout == "/data/arco-ocean/historical/res=0p25"
  assert "'TMPDIR' is not a setting of the scripts" in result.stderr


def test_an_empty_data_root_option_fails(tmp_path) -> None:
  result = resolve(tmp_path, option="")
  assert result.returncode == 1
  assert "--data-root is empty" in result.stderr


def test_a_repository_in_the_layout_before_is_not_replaced(tmp_path) -> None:
  # Outputs went to DATA_ROOT/data/<product>/res=<res> until 25 Nov 2026.
  (tmp_path / "root" / "data" / "historical" / "res=0p25").mkdir(parents=True)
  result = resolve(tmp_path, DATA_ROOT=str(tmp_path / "root"))
  assert result.returncode == 1
  assert "layout before 25 Nov 2026" in result.stderr
  # Moved, it is found.
  (tmp_path / "root" / "data" / "historical").rename(tmp_path / "root" / "historical")
  assert output(tmp_path, DATA_ROOT=str(tmp_path / "root")).endswith("root/historical/res=0p25")


def test_the_default_file_and_an_empty_variable_disabling_it(tmp_path) -> None:
  default = tmp_path / ".config" / "arco-ocean" / "settings"
  default.parent.mkdir(parents=True)
  default.write_text("DATA_ROOT=s3://bucket\n")
  # ARCO_OCEAN_SETTINGS unset (tests/conftest.py empties it): the default file is read.
  unset = ("DATA_ROOT", "XDG_CONFIG_HOME", "ARCO_OCEAN_SETTINGS")
  environ = {k: v for k, v in os.environ.items() if k not in unset}
  environ |= {"PROJECT_ROOT": "/project", "HOME": str(tmp_path)}
  script = f'source "{SETTINGS}" && resolve_data_root "" false "" && echo "${{DATA_ROOT}}"'

  def run(**env: str) -> str:
    result = subprocess.run(
      ["bash", "-c", script], env={**environ, **env}, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()

  assert run() == "s3://bucket"
  assert run(ARCO_OCEAN_SETTINGS="") == "/project/data"
