# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""The web page's tests (tests/js) judge heartbeats as `arco-ocean status` publishes them: their
fixtures are valid documents of the package's models."""

import json
import pathlib

import pytest

from arco_ocean import status

FIXTURES = sorted((pathlib.Path(__file__).parents[2] / "tests" / "js" / "fixtures").glob("*.json"))


def test_there_are_fixtures() -> None:
  assert FIXTURES


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.name)
def test_a_fixture_is_a_published_heartbeat(path: pathlib.Path) -> None:
  document = json.loads(path.read_text())
  heartbeat = status.Heartbeat.model_validate(document)
  # As published: every key, nothing more.
  assert heartbeat.model_dump(mode="json", by_alias=True) == document
