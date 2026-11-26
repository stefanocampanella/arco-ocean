# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""Tests marked `live` read the real sources: skipped unless pytest is given `--live`. Every other
test runs without arco-make's settings file, which holds credentials, and without the scripts'
settings file (scripts/lib/common.sh), which would send their outputs elsewhere."""

import pytest


@pytest.fixture(autouse=True)
def no_settings_file(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
  """Empty, ARCOMAKE_RC disables ~/.arcomakerc and ARCO_OCEAN_SETTINGS the scripts' settings
  file, in this process and in the scripts it runs."""
  if "live" not in request.keywords:
    monkeypatch.setenv("ARCOMAKE_RC", "")
  monkeypatch.setenv("ARCO_OCEAN_SETTINGS", "")


def pytest_addoption(parser: pytest.Parser) -> None:
  parser.addoption("--live", action="store_true", help="run the tests reading the real sources")


def pytest_configure(config: pytest.Config) -> None:
  config.addinivalue_line("markers", "live: reads the real sources (needs --live and credentials)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
  if config.getoption("--live"):
    return
  skip = pytest.mark.skip(reason="reads the real sources: run with --live")
  for item in items:
    if "live" in item.keywords:
      item.add_marker(skip)
