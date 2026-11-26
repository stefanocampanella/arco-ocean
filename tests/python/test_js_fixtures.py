# SPDX-FileCopyrightText: 2026 Stefano Campanella
# SPDX-License-Identifier: MIT
"""The web page's tests (tests/js) judge documents as the package publishes them: their fixtures
are valid documents of its models, heartbeats of `arco-ocean status` (heartbeat*.json) and
progresses of `arco-ocean progress` (progress*.json)."""

import json
import pathlib

import pytest
from pydantic import BaseModel

from arco_ocean import progress, status

FIXTURES = sorted((pathlib.Path(__file__).parents[2] / "tests" / "js" / "fixtures").glob("*.json"))
MODELS: dict[str, type[BaseModel]] = {"heartbeat": status.Heartbeat, "progress": progress.Progress}


def model(path: pathlib.Path) -> type[BaseModel]:
  kinds = [kind for kind in MODELS if path.name.startswith(kind)]
  assert len(kinds) == 1, f"{path.name}: name it heartbeat*.json or progress*.json"
  return MODELS[kinds[0]]


def test_there_are_fixtures_of_each_kind() -> None:
  assert {model(path) for path in FIXTURES} == set(MODELS.values())


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.name)
def test_a_fixture_is_a_published_document(path: pathlib.Path) -> None:
  document = json.loads(path.read_text())
  parsed = model(path).model_validate(document)
  # As published: every key, nothing more.
  assert parsed.model_dump(mode="json", by_alias=True) == document
