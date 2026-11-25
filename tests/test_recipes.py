# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""Every recipe loads with the models of the pinned arco-make, as its commands read it: unknown
keys, unknown steps and wrong arguments fail here, not at the start of a download (no data are
read)."""

import datetime
import pathlib
import re
import tomllib

import pytest
from arcomake.cli_utils import read_configs
from arcomake.climatology import ClimatologyConfig
from arcomake.download import DownloadConfig
from arcomake.validate import ValidateConfig

CONFIGS = pathlib.Path(__file__).parent.parent / "configs"
# The model of each recipe folder: the command that reads its recipes.
SCHEMAS = {"download": DownloadConfig, "climatology": ClimatologyConfig, "validate": ValidateConfig}
RECIPES = sorted(CONFIGS.rglob("*.toml"))


def test_every_folder_has_a_model():
  """A recipe in a folder without a model would go unchecked."""
  assert RECIPES
  assert {path.parent.name for path in RECIPES} <= set(SCHEMAS)


@pytest.mark.parametrize("path", RECIPES, ids=lambda path: str(path.relative_to(CONFIGS)))
def test_the_recipe_loads(path: pathlib.Path):
  read_configs(str(path), schema=SCHEMAS[path.parent.name])


DOWNLOADS = sorted((CONFIGS / "download").glob("*.toml"))
ROOT = CONFIGS.parent


def _forecast_sh_default(name: str) -> str:
  """The default of one of scripts/forecast.sh's settings (`NAME=value` at the top)."""
  text = (ROOT / "scripts" / "forecast.sh").read_text()
  match = re.search(rf'^{name}="?([^"\n]+)"?$', text, re.MULTILINE)
  assert match, name
  return match.group(1)


def _collection_timeout() -> datetime.timedelta:
  text = (ROOT / "systemd" / "arco-ocean-forecast.service").read_text()
  match = re.search(r"^TimeoutStartSec=(\d+)h$", text, re.MULTILINE)
  assert match
  return datetime.timedelta(hours=int(match.group(1)))


@pytest.mark.parametrize("path", DOWNLOADS, ids=lambda path: path.name)
def test_a_download_outlasts_an_outage(path: pathlib.Path):
  """Each download recipe gives its [retries] (arco-make's default may change). A historical
  block waits out an hour of outage of a source (scripts/download.sh then resumes the run). A
  forecast run's waits, times scripts/forecast.sh's attempts, outlast hours for each resolution;
  for all of them, they leave a third of the collection unit's time for the attempts."""
  assert "retries" in tomllib.loads(path.read_text()), "the recipe gives no [retries]"
  config = read_configs(str(path), schema=DownloadConfig)
  waited = sum(config.retries.waits(), datetime.timedelta())
  if config.forecast is None:
    assert waited >= datetime.timedelta(hours=1)
    return
  attempts = int(_forecast_sh_default("ATTEMPTS"))
  delay = datetime.timedelta(seconds=int(_forecast_sh_default("RETRY_DELAY")))
  resolutions = len(_forecast_sh_default("RESOLUTIONS").split(","))
  per_resolution = attempts * waited + (attempts - 1) * delay
  assert per_resolution >= datetime.timedelta(hours=2)
  assert resolutions * per_resolution <= 2 / 3 * _collection_timeout()
